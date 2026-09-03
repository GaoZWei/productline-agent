"""Agent 服务的 FastAPI 应用入口。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.api.approvals import router as approvals_router
from app.api.knowledge_index_capabilities import router as knowledge_index_capabilities_router
from app.api.model_capabilities import router as model_capabilities_router
from app.api.order_diagnosis import router as order_diagnosis_router
from app.api.run_events import router as run_events_router
from app.api.runs import router as runs_router
from app.api.sessions import router as sessions_router
from app.api.tool_debug import ToolDebugRunContextStore
from app.api.tool_debug import router as tool_debug_router
from app.clients.business import BusinessHttpClient
from app.clients.model import OpenAICompatibleChatClient
from app.database import Database
from app.observability import TraceIdMiddleware, configure_logging
from app.services import (
    DatabaseApprovalExecutionStore,
    KnowledgeIndexCapabilityService,
    ModelCapabilityService,
    RunEventService,
)
from app.settings import Settings, get_settings
from app.tools import create_read_tool_registry, create_write_tool_registry
from app.versioning import build_run_version_snapshot

logger = logging.getLogger("agent-service.lifecycle")


# Pydantic 响应模型
class HealthResponse(BaseModel):
    """与现有 Compose 冒烟测试共享的稳定探针契约。"""

    service: str
    status: str


# 创建 FastAPI 应用主入口
def create_app(settings: Settings | None = None) -> FastAPI:
    """使用显式配置构建供生产环境和测试使用的应用。"""

    resolved_settings = settings or get_settings()

    # lifespan 表示应用从启动到停止的生命周期
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        database = Database(resolved_settings.database_url)
        # FastAPI lifespan 创建共享 Business HTTP Client 实例
        business_client = BusinessHttpClient(resolved_settings)
        model_client = OpenAICompatibleChatClient(resolved_settings)
        # FastAPI 应用级共享状态供路由处理访问数据库和业务客户端。
        application.state.database = database
        application.state.business_client = business_client
        application.state.model_client = model_client
        application.state.run_event_service = RunEventService()
        # 使用同一个 Client 创建七个 Tool并放入 Registry 中, 共同使用连接池。
        application.state.tool_registry = create_read_tool_registry(business_client)
        application.state.write_tool_registry = create_write_tool_registry(
            business_client,
            DatabaseApprovalExecutionStore(database),
        )
        # 在应用启动时生成运行版本快照
        application.state.run_version_snapshot = build_run_version_snapshot(
            resolved_settings,
            application.state.tool_registry,
        )
        logger.info(
            "service_started",
            extra={
                "service": resolved_settings.service_name,
                "environment": resolved_settings.environment,
            },
        )
        # 释放 HTTP 连接池和数据库 Engine
        try:
            yield
        finally:
            try:
                await application.state.run_event_service.close()
            finally:
                try:
                    await model_client.aclose()
                finally:
                    try:
                        await business_client.aclose()
                    finally:
                        await database.dispose()
            logger.info("service_stopped", extra={"service": resolved_settings.service_name})

    application = FastAPI(
        title="Productline Agent Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    # 启动时使用同一个已经校验过的 Settings 创建服务实例
    application.state.model_capability_service = ModelCapabilityService(resolved_settings)
    application.state.knowledge_index_capability_service = KnowledgeIndexCapabilityService(
        resolved_settings
    )
    application.include_router(model_capabilities_router)
    application.include_router(knowledge_index_capabilities_router)
    application.include_router(order_diagnosis_router)
    application.include_router(run_events_router)
    application.include_router(runs_router)
    application.include_router(sessions_router)
    application.include_router(approvals_router)
    # 根据环境决定是否注册路由
    if resolved_settings.environment == "development":
        application.state.tool_debug_context_store = ToolDebugRunContextStore()
        application.include_router(tool_debug_router)
    # 注册中间件为每个请求添加跟踪 ID。
    application.add_middleware(TraceIdMiddleware)

    # 定义 HTTP接口
    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(service=resolved_settings.service_name, status="UP")

    return application


# 供 Uvicorn查找的应用实例
app = create_app()


def main() -> None:
    """使用校验后的主机和端口配置启动 Uvicorn。"""

    settings = get_settings()
    # Uvicorn是真正监听8000端口的服务器。
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
