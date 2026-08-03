"""由环境变量提供的服务配置。"""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# BaseSettings 会自动从环境变量读取数据
class Settings(BaseSettings):
    """经过校验的进程配置。启动日志不会包含密钥。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    # 字段约束限制配置的取值范围。
    service_name: str = "agent-service"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "postgresql://agent:agent-local-only@localhost:5432/remote_sensing_agent"
    business_service_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8080")
    business_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=60)
    business_read_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    business_write_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    business_pool_timeout_seconds: float = Field(default=1.0, gt=0, le=60)
    # 数据库 URL转换
    @property
    def async_database_url(self) -> str:
        """在接受仓库常规 PostgreSQL 地址的同时改用 asyncpg 驱动。"""

        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        raise ValueError("DATABASE_URL must use postgresql:// or postgresql+asyncpg://")

# 第一次读取环境变量后缓存 Settings。后续调用返回同一个对象。
@lru_cache
def get_settings() -> Settings:
    """每个应用进程只读取并校验一次配置。"""

    return Settings()
