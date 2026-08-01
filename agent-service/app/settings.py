"""Environment-backed service configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# BaseSettings 会自动从环境变量读取数据
class Settings(BaseSettings):
    """Validated process settings; secrets are never included in startup logs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    # 字段约束，用于约束字段的取值范围
    service_name: str = "agent-service"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "postgresql://agent:agent-local-only@localhost:5432/remote_sensing_agent"
    # 数据库 URL转换
    @property
    def async_database_url(self) -> str:
        """Use asyncpg while accepting the repository's conventional PostgreSQL URL."""

        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        raise ValueError("DATABASE_URL must use postgresql:// or postgresql+asyncpg://")

# 该函数作用是第一次读取环境变量后缓存 Settings，后续调用返回同一个对象
@lru_cache
def get_settings() -> Settings:
    """Read and validate process settings once per application process."""

    return Settings()
