"""M7.6-A 模型能力查询的安全传输契约。"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ModelName = Annotated[str, Field(min_length=1, max_length=128)]

# 响应 Schema
class ModelCapabilitiesResponse(BaseModel):
    """只公开模型启用状态和非敏感身份, 不代表模型可达或已被调用。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    configured: bool # 模型配置是否完整
    provider: Literal["openai_compatible"] | None # 当前使用的调用协议
    model_name: ModelName | None # 模型名称

    @model_validator(mode="after")
    def validate_configuration_state(self) -> Self:
        """启用状态必须身份完整, 关闭状态不得暗示仍有可用模型。"""
        # 校验配置状态是否一致
        if self.configured:
            if self.provider is None or self.model_name is None:
                raise ValueError("configured model capabilities require provider and model_name")
        elif self.provider is not None or self.model_name is not None:
            raise ValueError("unconfigured model capabilities must not expose model identity")
        return self
