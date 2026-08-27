"""由环境变量提供的服务配置。"""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
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
    session_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    approval_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    model_provider: str = Field(default="openai", min_length=1, max_length=128)  # 模型供应商
    model_name: str | None = Field(default=None, max_length=128)  # 模型名称
    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)  # 模型温度
    model_max_output_tokens: int = Field(default=2048, ge=1, le=65536)  # 模型最大输出令牌数
    embedding_provider: Literal["openai_compatible"] = "openai_compatible"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    embedding_api_key: SecretStr | None = None
    embedding_dimension: Literal[1536] = 1536
    embedding_batch_size: int = Field(default=32, ge=1, le=128)
    embedding_max_retries: int = Field(default=2, ge=0, le=3)
    embedding_initial_backoff_seconds: float = Field(default=0.2, gt=0, le=10)
    embedding_max_backoff_seconds: float = Field(default=2.0, gt=0, le=30)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    embedding_index_version: str = "text-embedding-3-small-1536-v1"

    @field_validator("embedding_dimension", mode="before")
    @classmethod
    def parse_embedding_dimension(cls, value: object) -> object:
        """把Compose传入的固定维度字符串转换为Literal可校验的整数。"""

        return 1536 if value == "1536" else value

    @field_validator("model_name", mode="before")
    @classmethod
    def empty_model_name_is_unconfigured(cls, value: object) -> object:
        """Compose 的空字符串表示尚未接入真实决策模型。"""

        if isinstance(value, str) and not value.strip():
            return None
        return value

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
