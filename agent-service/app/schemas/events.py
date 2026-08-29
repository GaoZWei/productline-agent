"""SSE运行事件、流标识和安全数据边界。"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator
# 事件Schema stream_id：页面在执行前生成，用于先建立连接
EventStreamIdentifier = Annotated[
    str,
    Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
EventIdentifier = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[1-9][0-9]*$")]

_MAX_EVENT_DATA_DEPTH = 6
_MAX_EVENT_DATA_ITEMS = 256
_MAX_EVENT_STRING_LENGTH = 4096
_MAX_EVENT_DATA_BYTES = 32768
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "password",
        "api_key",
        "token",
        "secret",
        "cookie",
        "set_cookie",
    }
)

# 事件类型
class RunEventType(StrEnum):
    """页面可稳定消费的Agent运行事件类型。"""

    RUN_STARTED = "run_started"
    CONTEXT_LOADED = "context_loaded"
    INTENT_DETECTED = "intent_detected"
    CLARIFICATION_REQUIRED = "clarification_required"
    AGENT_ACTION_SELECTED = "agent_action_selected"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    DIAGNOSIS_GENERATED = "diagnosis_generated"
    APPROVAL_REQUIRED = "approval_required"
    WRITEBACK_STARTED = "writeback_started"
    WRITEBACK_COMPLETED = "writeback_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"

# 事件模型
class RunEvent(BaseModel):
    """一条可回放SSE事件, 只携带受控结构化数据。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    event_id: EventIdentifier  # SSE协议中的事件ID，用于断线续接
    event_type: RunEventType
    stream_id: EventStreamIdentifier  # 属于哪条页面事件流
    run_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None  # 对应哪个持久化Run
    sequence_number: Annotated[int, Field(ge=1)]  # 流内严格递增顺序
    occurred_at: AwareDatetime
    trace_id: Annotated[str, Field(min_length=1, max_length=128)]  # 对应触发该事件的HTTP请求ID
    step_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None  # Tool事件对应哪个数据库Step
    data: dict[str, JsonValue] = Field(default_factory=dict)  # 受控的阶段摘要
    # 安全校校验data字段
    @field_validator("data")
    @classmethod
    def validate_safe_data(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """限制事件体积并拒绝常见凭据键, 避免SSE成为旁路日志。"""

        item_count = _validate_event_value(value, depth=0)
        if item_count > _MAX_EVENT_DATA_ITEMS:
            raise ValueError("event data contains too many items")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_EVENT_DATA_BYTES:
            raise ValueError("event data is too large")
        return value


class RunEventStreamErrorResponse(BaseModel):
    """SSE连接建立前返回的稳定JSON错误。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    stream_id: EventStreamIdentifier
    trace_id: Annotated[str, Field(min_length=1, max_length=128)]
    code: Annotated[str, Field(min_length=1, max_length=64)]
    message: Annotated[str, Field(min_length=1, max_length=512)]


def _validate_event_value(value: JsonValue, *, depth: int) -> int:
    """递归校验事件数据深度、字符串长度和敏感键并返回元素数量。"""

    if depth > _MAX_EVENT_DATA_DEPTH:
        raise ValueError("event data nesting is too deep")
    if isinstance(value, str):
        if len(value) > _MAX_EVENT_STRING_LENGTH:
            raise ValueError("event data string is too long")
        return 1
    if isinstance(value, list):
        return 1 + sum(_validate_event_value(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        total = 1
        for key, item in value.items():
            normalized_key = key.lower().replace("-", "_")
            if (
                normalized_key in _SENSITIVE_KEYS
                or normalized_key.endswith("_token")
                or normalized_key.endswith("_secret")
            ):
                raise ValueError(f"event data contains sensitive key: {key}")
            if len(key) > 128:
                raise ValueError("event data key is too long")
            total += _validate_event_value(item, depth=depth + 1)
        return total
    return 1
