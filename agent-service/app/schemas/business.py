"""调用 Java 业务服务时使用的已校验传输契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

SafeHeaderValue = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[^\r\n]+$")]
type BusinessErrorCode = Literal[
    "PARAM_VALIDATION_ERROR",
    "RESOURCE_NOT_FOUND",
    "PERMISSION_DENIED",
    "BUSINESS_CONFLICT",
    "INTERNAL_SERVER_ERROR",
]


# Java 调用相关 Schema
# BusinessIdentity: 用户、角色和可选 Token; Token 使用 SecretStr。
class BusinessIdentity(BaseModel):
    """单次调用中透传给 Java 的身份。可选令牌不会显示在对象表示中。"""

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


# BusinessSuccessEnvelope: 严格要求 success/code/message/data/trace_id/retryable 六个字段
class BusinessSuccessEnvelope(BaseModel):
    """在校验端点业务数据前使用的严格 Java 成功信封。"""

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

# Java 失败信封 Schema: Java 返回的错误响应先用这个校验一遍。
class BusinessErrorEnvelope(BaseModel):
    """映射 Tool 错误前使用的严格 Java 失败信封。"""
    #  不会自动把字符串或数字转换成布尔值。 
    model_config = ConfigDict(extra="forbid", strict=True)  

    success: Literal[False]
    code: BusinessErrorCode  # 只允许Java当前已经约定的错误码
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    data: None
    trace_id: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ]
    retryable: Literal[False]


# BusinessResponse: 返回经过端点 Schema 校验的强类型 data
@dataclass(frozen=True, slots=True)
class BusinessResponse[DataT]:
    """已校验的 Java 响应元数据和端点专用强类型数据。"""

    data: DataT
    trace_id: str
    message: str
