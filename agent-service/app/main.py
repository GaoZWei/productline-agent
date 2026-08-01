"""FastAPI application entry point for the Agent service."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.database import Database
from app.observability import TraceIdMiddleware, configure_logging
from app.settings import Settings, get_settings

logger = logging.getLogger("agent-service.lifecycle")

# Pydantic 响应模型
class HealthResponse(BaseModel):
    """Stable probe contract shared with the existing Compose smoke test."""

    service: str
    status: str

# 应用工厂，负责创建 FastAPI应用
def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with explicit settings for production and tests."""

    resolved_settings = settings or get_settings()
    # lifespan 表示应用从启动到停止的生命周期
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        database = Database(resolved_settings.database_url)
        # FastAPI 应用级共享状态，用于在路由处理中访问数据库连接
        application.state.database = database
        logger.info(
            "service_started",
            extra={
                "service": resolved_settings.service_name,
                "environment": resolved_settings.environment,
            },
        )
        try:
            yield
        finally:
            await database.dispose()
            logger.info("service_stopped", extra={"service": resolved_settings.service_name})

    application = FastAPI(
        title="Productline Agent Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    # 注册中间件，用于在每个请求中添加跟踪 ID
    application.add_middleware(TraceIdMiddleware)
    # 定义 HTTP接口
    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(service=resolved_settings.service_name, status="UP")

    return application

# 供 Uvicorn查找的应用实例
app = create_app()


def main() -> None:
    """Start Uvicorn with host and port supplied by validated settings."""

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
