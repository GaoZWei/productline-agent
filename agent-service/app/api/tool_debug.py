"""仅在开发环境注册的 Tool 手工调试接口。"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.observability import get_trace_id
from app.schemas.business import BusinessIdentity
from app.tools import ToolContext, ToolNotRegisteredError, ToolRegistry, ToolResult
from app.tools.models import ContextIdentifier, PermissionName

# Store最多保存128个Run上下文
_MAX_DEBUG_RUN_CONTEXTS = 128
# 路径参数定义
_TOOL_NAME_PATH = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
        examples=["get_order_detail"],
        description="ToolRegistry 中注册的稳定 Tool 名称",
    ),
]

# 请求模型 
class ToolDebugInvokeRequest(BaseModel):
    """把 Swagger 中的调试输入转换为 ToolContext 和 Tool 业务参数。"""

    model_config = ConfigDict(
        extra="forbid",  # 不允许请求包含未知字段
        strict=True,  # 要求字段类型尽量严格匹配
        json_schema_extra={
            "examples": [
                {
                    "arguments": {"order_id": "ORDER-003"},
                    "identity": {
                        "user_id": "debug-user-001",
                        "role": "REVIEWER",
                    },
                    "permissions": ["ORDER_READ"],
                    "run_id": "debug-run-order-003",
                    "force_refresh": False,
                }
            ]
        },
    )

    arguments: dict[str, object] = Field(
        description="传给目标 Tool input_model 的原始 JSON 参数",
    )
    identity: BusinessIdentity = Field(
        description="透传给 Java 服务重新校验的调试身份",
    )
    permissions: list[PermissionName] = Field(
        description="Python Tool 快速门禁使用的权限名称; 允许空列表以验证拒绝分支",
    )
    run_id: ContextIdentifier = Field(
        description="调试 Run 标识; 相同 Run 会复用 M1.7 调用账本",
    )
    force_refresh: bool = Field(
        default=False,
        description="显式绕过当前一次重复调用门禁并重新读取 Java 事实",
    )


class DebugRunContextConflictError(ValueError):
    """表示调用方试图在同一调试 Run 中更换身份或权限。"""

# 调试上下文存储 同一个run_id后续请求会取回同一Run的上下文
class ToolDebugRunContextStore:
    """为最近的开发调试 Run 保存有界 ToolContext, 支持跨 HTTP 请求去重。"""

    def __init__(self, *, capacity: int = _MAX_DEBUG_RUN_CONTEXTS) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self._capacity = capacity
        self._contexts: OrderedDict[str, ToolContext] = OrderedDict()
        self._lock = Lock()

    def resolve(
        self,
        invoke_request: ToolDebugInvokeRequest,
        *,
        trace_id: str,
    ) -> ToolContext:
        """创建或复用调试上下文, 并为当前 HTTP 请求替换 Trace ID。"""
        # 规范权限集合
        permissions = frozenset(invoke_request.permissions)
        # 使用Lock保护Store, 避免并发访问导致的不一致状态
        with self._lock:
            existing = self._contexts.get(invoke_request.run_id)
            if existing is not None:
                if (
                    existing.identity != invoke_request.identity 
                    or existing.permissions != permissions
                ):  # 同一Run禁止更换身份或权限
                    raise DebugRunContextConflictError
                self._contexts.move_to_end(invoke_request.run_id)
                # model_copy 默认浅复制 PrivateAttr, 因此新 Trace 仍共享原 Run 的调用账本。
                return existing.model_copy(update={"trace_id": trace_id})

            context = ToolContext(
                identity=invoke_request.identity,
                permissions=permissions,
                trace_id=trace_id,
                run_id=invoke_request.run_id,
            )
            self._contexts[invoke_request.run_id] = context
            if len(self._contexts) > self._capacity:
                self._contexts.popitem(last=False)
            return context

    @property
    def size(self) -> int:
        """返回当前保留的调试 Run 数量。"""

        with self._lock:
            return len(self._contexts)

# 响应示例
_STANDARD_RESULT_EXAMPLES: dict[str, dict[str, object]] = {
    "success": {
        "summary": "订单 Tool 调用成功",
        "value": {
            "success": True,
            "data": {
                "orderId": "ORDER-003",
                "productType": "DOM",
                "status": "QUALITY_CHECKING",
            },
            "error": None,
        },
    },
    "tool_error": {
        "summary": "Tool 标准错误",
        "value": {
            "success": False,
            "data": None,
            "error": {
                "code": "PARAM_VALIDATION_ERROR",
                "message": "tool input validation failed",
                "retryable": False,
                "trace_id": "trace-debug-001",
                "status_code": None,
            },
        },
    },
}
# 路由配置
router = APIRouter(prefix="/internal/tools", tags=["internal-tools"])


@router.post(
    "/{tool_name}/invoke",
    response_model=ToolResult[Any],
    summary="调试调用只读 Tool",
    description=(
        "仅在 development 环境注册。请求直接进入现有 Tool 权限、输入、重复检测、重试、"
        "Java Client 和输出校验链路; Tool 失败仍返回标准 ToolResult。"
    ),
    responses={
        200: {
            "description": "标准 ToolResult; success=false 仍表示调试 HTTP 请求已正常完成",
            "content": {"application/json": {"examples": _STANDARD_RESULT_EXAMPLES}},
        },
        404: {"description": "ToolRegistry 中不存在该 Tool"},
        409: {"description": "同一 run_id 的身份或权限与首次调用不一致"},
    },
)
async def invoke_tool(
    tool_name: _TOOL_NAME_PATH,
    invoke_request: ToolDebugInvokeRequest,
    request: Request,
) -> ToolResult[Any]:
    """解析调试上下文并通过注册表执行目标 Tool。"""
    # 第一步: 取得应用级对象
    registry: ToolRegistry = request.app.state.tool_registry
    context_store: ToolDebugRunContextStore = request.app.state.tool_debug_context_store
    try: 
        # 第二步: 查找ToolRegistry中的Tool
        tool = registry.get(tool_name)
    except ToolNotRegisteredError as exception:
        raise HTTPException(status_code=404, detail="tool is not registered") from exception
    # 第三步: 恢复Run上下文
    try:
        context = context_store.resolve(invoke_request, trace_id=get_trace_id())
    except DebugRunContextConflictError as exception:
        raise HTTPException(
            status_code=409,
            detail="run context does not match its first invocation",
        ) from exception
    # 第四步: 调用现有BaseTool
    return await tool.execute(
        invoke_request.arguments,
        context,
        force_refresh=invoke_request.force_refresh,
    )
