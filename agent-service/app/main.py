"""Agent 服务的 FastAPI 应用入口。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.clients.business import BusinessHttpClient
from app.database import Database
from app.observability import TraceIdMiddleware, configure_logging
from app.settings import Settings, get_settings
from app.tools import create_read_tool_registry

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
        # FastAPI 应用级共享状态供路由处理访问数据库和业务客户端。
        application.state.database = database
        application.state.business_client = business_client
        # 使用同一个 Client 创建七个 Tool，并放入 Registry 中(公用连接池)
        application.state.tool_registry = create_read_tool_registry(business_client)
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
