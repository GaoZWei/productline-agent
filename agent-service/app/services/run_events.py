"""有界内存SSE事件流、回放、心跳和订阅清理。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic

from pydantic import JsonValue

from app.schemas.events import RunEvent, RunEventType

_TERMINAL_EVENT_TYPES = frozenset(
    {
        RunEventType.RUN_COMPLETED,
        RunEventType.RUN_FAILED,
        RunEventType.WRITEBACK_COMPLETED,
    }
)
_STREAM_END = object()
type _QueueItem = RunEvent | object


class RunEventServiceError(Exception):
    """SSE事件服务错误基类。"""


class EventStreamNotFoundError(RunEventServiceError):
    """目标事件流尚未建立或已经过期。"""


class EventStreamAccessDeniedError(RunEventServiceError):
    """当前用户不是事件流创建者。"""


class EventReplayUnavailableError(RunEventServiceError):
    """Last-Event-ID早于有界历史, 无法提供连续回放。"""


class EventStreamCapacityError(RunEventServiceError):
    """活动事件流已经达到内存安全上限。"""

# 事件流的内存状态，包含事件历史、订阅者队列、下一个事件序号、是否终态时间
@dataclass(slots=True)
class _EventStreamState:
    stream_id: str
    owner_user_id: str # 用于用户隔离
    created_at: float
    updated_at: float
    history: deque[RunEvent]  # 事件历史记录
    subscribers: set[asyncio.Queue[_QueueItem]] = field(default_factory=set)  # 异步队列
    next_sequence_number: int = 1  # 发布一条事件递增一次
    terminal_at: float | None = None

# 一个流只能绑定一个Run事件
class RunEventPublisher:
    """绑定一个用户事件流和Trace, 按顺序发布Run相关事件。"""

    def __init__(
        self,
        service: RunEventService,
        *,
        stream_id: str,
        owner_user_id: str,
        trace_id: str,
    ) -> None:
        self._service = service
        self._stream_id = stream_id
        self._owner_user_id = owner_user_id
        self._trace_id = trace_id
        self._run_id: str | None = None
        self._terminal = False

    @property
    def terminal(self) -> bool:
        """返回当前发布器是否已经发布终态。"""

        return self._terminal

    async def publish(
        self,
        event_type: RunEventType,
        *,
        run_id: str | None = None,
        step_id: str | None = None,
        data: Mapping[str, JsonValue] | None = None,
    ) -> None:
        """绑定首个Run标识并拒绝同一流混入另一个Run。"""

        if self._terminal:
            return
        if run_id is not None:
            # 防止同一流混入另一个Run
            if self._run_id is not None and self._run_id != run_id:
                raise ValueError("one event publisher cannot mix multiple run identifiers")
            self._run_id = run_id
        await self._service.publish(
            stream_id=self._stream_id,
            owner_user_id=self._owner_user_id,
            trace_id=self._trace_id,
            event_type=event_type,
            run_id=self._run_id,
            step_id=step_id,
            data=data,
        )
        if event_type in _TERMINAL_EVENT_TYPES:
            self._terminal = True

# 订阅、心跳与断线清理
class RunEventSubscription:
    """一个可关闭订阅, 负责SSE编码、心跳和断开检查。"""

    def __init__(
        self,
        service: RunEventService,
        *,
        stream_id: str,
        queue: asyncio.Queue[_QueueItem],
        heartbeat_seconds: float,
    ) -> None:
        self._service = service
        self._stream_id = stream_id
        self._queue = queue
        self._heartbeat_seconds = heartbeat_seconds
        self._closed = False

    async def iter_sse(
        self,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[str]:
        """先确认连接, 再持续输出事件或注释心跳, 最终确保移除订阅。"""

        try:
            # 确认连接
            yield f": connected {self._stream_id}\nretry: 3000\n\n"
            while True:
                # 断线检查
                if await is_disconnected():
                    return
                try:
                    # 等待事件或心跳超时
                    item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=self._heartbeat_seconds,
                    )
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is _STREAM_END:
                    return
                assert isinstance(item, RunEvent)
                yield encode_sse_event(item)
                if item.event_type in _TERMINAL_EVENT_TYPES:
                    return
        # 最后处理
        finally:
            await self.close()

    async def close(self) -> None:
        """幂等移除订阅队列, 避免断开连接继续累积事件。"""

        if self._closed:
            return
        self._closed = True
        await self._service.remove_subscription(self._stream_id, self._queue)


class RunEventService:
    """按stream_id管理有界事件历史和实时订阅。"""

    def __init__(
        self,
        *,
        heartbeat_seconds: float = 15.0,
        history_limit: int = 256,
        stream_limit: int = 256,
        retention_seconds: float = 60.0,
        idle_seconds: float = 60.0,
        clock: Callable[[], float] = monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if history_limit < 1 or stream_limit < 1:
            raise ValueError("history_limit and stream_limit must be positive")
        if retention_seconds <= 0 or idle_seconds <= 0:
            raise ValueError("stream retention values must be positive")
        self._heartbeat_seconds = heartbeat_seconds
        self._history_limit = history_limit
        self._stream_limit = stream_limit
        self._retention_seconds = retention_seconds
        self._idle_seconds = idle_seconds
        self._clock = clock
        self._now = now
        self._streams: dict[str, _EventStreamState] = {}
        self._lock = asyncio.Lock()
    # 创建事件流
    async def open_stream(self, stream_id: str, *, owner_user_id: str) -> None:
        """创建或重新打开属于同一用户的事件流。"""

        async with self._lock:
            self._cleanup_locked()
            existing = self._streams.get(stream_id)
            if existing is not None:
                self._require_owner(existing, owner_user_id)
                existing.updated_at = self._clock()
                return
            if len(self._streams) >= self._stream_limit:
                raise EventStreamCapacityError("active event stream limit was reached")
            timestamp = self._clock()
            self._streams[stream_id] = _EventStreamState(
                stream_id=stream_id,
                owner_user_id=owner_user_id,
                created_at=timestamp,
                updated_at=timestamp,
                history=deque(maxlen=self._history_limit),
            )
    # 创建发布器
    async def publisher(
        self,
        stream_id: str,
        *,
        owner_user_id: str,
        trace_id: str,
    ) -> RunEventPublisher:
        """只为已经建立且归属匹配的流创建发布器。"""

        async with self._lock:
            self._cleanup_locked()
            stream = self._streams.get(stream_id)
            if stream is None:
                raise EventStreamNotFoundError(stream_id)
            self._require_owner(stream, owner_user_id)
            if stream.terminal_at is not None:
                raise EventStreamNotFoundError(stream_id)
        return RunEventPublisher(
            self,
            stream_id=stream_id,
            owner_user_id=owner_user_id,
            trace_id=trace_id,
        )
    # 创建订阅
    async def subscribe(
        self,
        stream_id: str,
        *,
        owner_user_id: str,
        last_event_id: int = 0,
    ) -> RunEventSubscription:
        """订阅实时事件并把Last-Event-ID之后的有界历史先放入队列。"""

        if last_event_id < 0:
            raise ValueError("last_event_id must not be negative")
        async with self._lock:
            self._cleanup_locked()
            stream = self._streams.get(stream_id)
            if stream is None:
                raise EventStreamNotFoundError(stream_id)
            self._require_owner(stream, owner_user_id)
            if stream.history:
                oldest_sequence = stream.history[0].sequence_number
                if last_event_id and last_event_id < oldest_sequence - 1:
                    raise EventReplayUnavailableError(stream_id)
            queue: asyncio.Queue[_QueueItem] = asyncio.Queue(
                maxsize=self._history_limit + 1
            )
            for event in stream.history:
                if event.sequence_number > last_event_id:
                    queue.put_nowait(event)
            if stream.terminal_at is not None:
                queue.put_nowait(_STREAM_END)
            else:
                stream.subscribers.add(queue)
            stream.updated_at = self._clock()
        return RunEventSubscription(
            self,
            stream_id=stream_id,
            queue=queue,
            heartbeat_seconds=self._heartbeat_seconds,
        )
    # 发布事件
    async def publish(
        self,
        *,
        stream_id: str,
        owner_user_id: str,
        trace_id: str,
        event_type: RunEventType,
        run_id: str | None,
        step_id: str | None,
        data: Mapping[str, JsonValue] | None,
    ) -> RunEvent:
        """原子分配序号、保存有界历史并广播给当前订阅者。"""

        async with self._lock:
            stream = self._streams.get(stream_id)
            if stream is None:
                raise EventStreamNotFoundError(stream_id)
            self._require_owner(stream, owner_user_id)
            if stream.terminal_at is not None:
                raise EventStreamNotFoundError(stream_id)
            sequence_number = stream.next_sequence_number
            event = RunEvent(
                event_id=str(sequence_number),
                event_type=event_type,
                stream_id=stream_id,
                run_id=run_id,
                sequence_number=sequence_number,
                occurred_at=self._timestamp(),
                trace_id=trace_id,
                step_id=step_id,
                data=dict(data or {}),
            )
            stream.next_sequence_number += 1
            stream.updated_at = self._clock()
            stream.history.append(event)
            terminal = event_type in _TERMINAL_EVENT_TYPES
            if terminal:
                stream.terminal_at = stream.updated_at
            subscribers = tuple(stream.subscribers)
            for queue in subscribers:
                try:
                    queue.put_nowait(event)
                    if terminal:
                        queue.put_nowait(_STREAM_END)
                except asyncio.QueueFull:
                    stream.subscribers.discard(queue)
            if terminal:
                stream.subscribers.clear()
            return event
    # 慢消费者除订阅
    async def remove_subscription(
        self,
        stream_id: str,
        queue: asyncio.Queue[_QueueItem],
    ) -> None:
        """从流中移除一个断开的订阅者并刷新空闲时间。"""

        async with self._lock:
            stream = self._streams.get(stream_id)
            if stream is None:
                return
            stream.subscribers.discard(queue)
            stream.updated_at = self._clock()
            self._cleanup_locked()

    async def active_subscriber_count(self, stream_id: str) -> int:
        """仅供健康检查和测试观察订阅是否已经清理。"""

        async with self._lock:
            stream = self._streams.get(stream_id)
            return len(stream.subscribers) if stream is not None else 0

    async def close(self) -> None:
        """应用停止时通知全部订阅结束并释放历史。"""

        async with self._lock:
            for stream in self._streams.values():
                for queue in stream.subscribers:
                    try:
                        queue.put_nowait(_STREAM_END)
                    except asyncio.QueueFull:
                        pass
            self._streams.clear()
    # 过期清理事件流
    def _cleanup_locked(self) -> None:
        now = self._clock()
        expired = [
            stream_id
            for stream_id, stream in self._streams.items()
            if not stream.subscribers
            and (
                (
                    stream.terminal_at is not None
                    and now - stream.terminal_at >= self._retention_seconds
                )
                or (
                    stream.terminal_at is None
                    and now - stream.updated_at >= self._idle_seconds
                )
            )
        ]
        for stream_id in expired:
            del self._streams[stream_id]

    @staticmethod
    def _require_owner(stream: _EventStreamState, owner_user_id: str) -> None:
        if stream.owner_user_id != owner_user_id:
            raise EventStreamAccessDeniedError(stream.stream_id)

    def _timestamp(self) -> datetime:
        timestamp = self._now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("event clock must include timezone information")
        return timestamp

# SSE编码事件
def encode_sse_event(event: RunEvent) -> str:
    """按SSE标准编码id、event和单行JSON data字段。"""

    return (
        f"id: {event.event_id}\n"
        f"event: {event.event_type.value}\n"
        f"data: {event.model_dump_json()}\n\n"
    )
