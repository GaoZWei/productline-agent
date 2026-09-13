"""对业务 Tool 和 Workflow 暴露稳定的基础协议。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.tools.base import BaseTool, ToolRiskLevel
from app.tools.deduplication import RunToolCallLedger, build_tool_call_fingerprint
from app.tools.models import ToolContext, ToolError, ToolResult
from app.tools.readonly import (
    READ_TOOL_NAMES,
    GetDeliveryStatusTool,
    GetOrderDetailTool,
    GetProductionProgressTool,
    GetQualityIssuesTool,
    GetRelatedTasksTool,
    GetReviewResultTool,
    GetTaskDetailTool,
    create_read_tool_registry,
)
from app.tools.registry import (
    DuplicateToolRegistrationError,
    ToolNotRegisteredError,
    ToolRegistry,
)
from app.tools.retry import RetryPolicy

if TYPE_CHECKING:
    from app.tools.write import (
        WRITE_TOOL_NAMES,
        CreateReworkTaskTool,
        WriteReviewResultTool,
        create_write_tool_registry,
    )

_WRITE_EXPORTS = frozenset(
    {
        "WRITE_TOOL_NAMES",
        "CreateReworkTaskTool",
        "WriteReviewResultTool",
        "create_write_tool_registry",
    }
)


def __getattr__(name: str) -> object:
    """按需加载写Tool, 避免只读Workflow导入时触发Approval服务环。"""

    if name not in _WRITE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from app.tools import write

    value = getattr(write, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """让交互式检查仍能发现惰性公共符号。"""

    return sorted({*globals(), *_WRITE_EXPORTS})

__all__ = [
    "READ_TOOL_NAMES",
    "WRITE_TOOL_NAMES",
    "BaseTool",
    "CreateReworkTaskTool",
    "DuplicateToolRegistrationError",
    "GetDeliveryStatusTool",
    "GetOrderDetailTool",
    "GetProductionProgressTool",
    "GetQualityIssuesTool",
    "GetRelatedTasksTool",
    "GetReviewResultTool",
    "GetTaskDetailTool",
    "RetryPolicy",
    "RunToolCallLedger",
    "ToolContext",
    "ToolError",
    "ToolNotRegisteredError",
    "ToolRegistry",
    "ToolResult",
    "ToolRiskLevel",
    "WriteReviewResultTool",
    "build_tool_call_fingerprint",
    "create_read_tool_registry",
    "create_write_tool_registry",
]
