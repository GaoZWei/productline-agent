"""Validated transport contracts for calls to the Java business service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

SafeHeaderValue = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[^\r\n]+$")]

# Java 调用相关 Schema
# BusinessIdentity：用户、角色和可选 Token；Token 使用 SecretStr。
class BusinessIdentity(BaseModel):
    """Per-call identity forwarded to Java; the optional token is hidden from repr."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    user_id: SafeHeaderValue
    role: SafeHeaderValue
    token: SecretStr | None = None

    @field_validator("token")
    @classmethod
    def validate_token(cls, token: SecretStr | None) -> SecretStr | None:
        if token is None:
            return None
        raw_token = token.get_secret_value()
        if not raw_token or "\r" in raw_token or "\n" in raw_token:
            raise ValueError("token must be non-empty and must not contain newlines")
        return token

# BusinessSuccessEnvelope：严格要求 success/code/message/data/trace_id/retryable 六个字段
class BusinessSuccessEnvelope(BaseModel):
    """Strict Java success envelope before the endpoint-specific data is validated."""

    model_config = ConfigDict(extra="forbid", strict=True)

    success: Literal[True]
    code: Literal["SUCCESS"]
    message: str
    data: object
    trace_id: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ]
    retryable: Literal[False]

# BusinessResponse：返回经过端点 Schema 校验的强类型 data
@dataclass(frozen=True, slots=True)
class BusinessResponse[DataT]:
    """Validated Java response metadata plus endpoint-specific typed data."""

    data: DataT
    trace_id: str
    message: str
