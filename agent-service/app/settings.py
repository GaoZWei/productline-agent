"""由环境变量提供的服务配置。"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
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
    model_provider: Literal["openai_compatible"] = "openai_compatible"  # 使用哪种模型调用协议
    model_name: str | None = Field(default=None, max_length=128)  # 空值表示未启用模型
    model_base_url: AnyHttpUrl | None = None  # 模型网关地址 OpenAI兼容API根地址
    model_api_key: SecretStr | None = None  # 访问密钥 本地无鉴权网关允许为空
    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)  # 控制生成结果的随机程度
    model_max_output_tokens: int = Field(default=2048, ge=1, le=65536)  # 模型最大输出令牌数
    model_timeout_seconds: float = Field(default=30.0, gt=0, le=120)  # 单次 HTTP 超时时间
    model_max_retries: int = Field(default=1, ge=0, le=3)  # 首次请求之外允许的重试次数
    model_initial_backoff_seconds: float = Field(default=0.2, gt=0, le=10)  # 指数退避边界时间
    model_max_backoff_seconds: float = Field(default=2.0, gt=0, le=30)
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

    @field_validator("model_provider", mode="before")
    @classmethod
    def normalize_model_provider(cls, value: object) -> object:
        """兼容旧的openai名称, 并把运行契约统一为openai_compatible。"""

        if isinstance(value, str):
            normalized = value.strip().lower()
            return "openai_compatible" if normalized == "openai" else normalized
        return value

    @field_validator("model_name", mode="before")
    @classmethod
    def empty_model_name_is_unconfigured(cls, value: object) -> object:
        """Compose的空字符串表示未启用模型, 非空名称统一去除首尾空白。"""

        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("model_base_url", mode="before")
    @classmethod
    def empty_model_base_url_is_unconfigured(cls, value: object) -> object:
        """允许Compose用空字符串表达尚未提供模型地址。"""

        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("model_api_key", mode="before")
    @classmethod
    def empty_model_api_key_is_absent(cls, value: object) -> object:
        """空密钥不构成配置, 非空值由SecretStr负责隐藏。"""

        if isinstance(value, SecretStr):
            return value if value.get_secret_value().strip() else None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value
    # 不完整配置直接报错
    @model_validator(mode="after")
    def validate_model_configuration(self) -> Self:
        """启用模型时必须有调用地址; 未启用时允许预先注入地址或密钥。"""

        if self.model_name is not None and self.model_base_url is None:
            raise ValueError("MODEL_BASE_URL is required when MODEL_NAME is configured")
        if self.model_max_backoff_seconds < self.model_initial_backoff_seconds:
            raise ValueError(
                "MODEL_MAX_BACKOFF_SECONDS must not be smaller than "
                "MODEL_INITIAL_BACKOFF_SECONDS"
            )
        return self
    # 判断模型是否已配置启用
    @property
    def model_configured(self) -> bool:
        """返回当前进程是否具备一个可寻址的模型配置。"""

        return self.model_name is not None

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
