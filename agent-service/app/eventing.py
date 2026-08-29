"""业务组件与具体SSE实现之间的最小异步事件协议。"""

from collections.abc import Mapping
from typing import Protocol

from pydantic import JsonValue

from app.schemas.events import RunEventType

# 解耦耦业务代码和SSE实现
class RunEventSink(Protocol):
    """允许Workflow和Service发布受控事件而不依赖内存Broker。"""

    async def publish(
        self,
        event_type: RunEventType,
        *,
        run_id: str | None = None,
        step_id: str | None = None,
        data: Mapping[str, JsonValue] | None = None,
    ) -> None:
        """按当前流内稳定序号发布一条事件。"""

        ...
