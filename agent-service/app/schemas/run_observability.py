"""Run级上下文、用量和终止摘要契约。"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RunCount = Annotated[int, Field(ge=0, le=2_147_483_647)]


class RunObservabilitySchema(BaseModel):
    """运行元数据使用严格、不可变且禁止额外字段的共同边界。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class RunTokenUsage(RunObservabilitySchema):
    """一次Run内可归属模型调用的输入、输出和总Token。"""
    # 数值必须非负
    input_tokens: RunCount = 0
    output_tokens: RunCount = 0
    total_tokens: RunCount = 0

    @model_validator(mode="after")
    def require_exact_total(self) -> Self:
        """总量必须等于输入与输出之和, 避免三个计数互相矛盾。"""
        # 总数必须准确
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        return self

    @classmethod
    def from_counts(cls, *, input_tokens: int, output_tokens: int) -> RunTokenUsage:
        """从输入输出计数构造自洽统计。"""

        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
