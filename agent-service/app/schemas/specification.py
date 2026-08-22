"""规范问答模型输出和最终带引用结果契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.knowledge import Citation


class SpecificationQaStatus(StrEnum):
    """区分正常回答与三类不产生规范结论的安全结果。"""

    ANSWERED = "ANSWERED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    RERANK_UNAVAILABLE = "RERANK_UNAVAILABLE"
    GENERATION_FAILED = "GENERATION_FAILED"


class _SpecificationSchema(BaseModel):
    """规范问答禁止额外字段、隐式标量转换和结果修改。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class SpecificationAnswerDraft(_SpecificationSchema):
    """模型只返回回答文案及其使用的既有引用身份。"""

    answer: Annotated[str, Field(min_length=1, max_length=8000)]
    citation_ids: Annotated[tuple[str, ...], Field(min_length=1, strict=False)]

# 最终结果定义
class SpecificationQaResult(_SpecificationSchema):
    """规范问答对调用方返回的状态、文本、引用和降级标记。"""

    status: SpecificationQaStatus = Field(strict=False)
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    rewritten_query: Annotated[str, Field(min_length=1, max_length=2000)]
    answer: Annotated[str, Field(min_length=1, max_length=8000)]
    citations: tuple[Citation, ...]
    rerank_degraded: bool = False

    @model_validator(mode="after")
    def validate_answer_boundary(self) -> Self:
        """只有正常回答可以携带规范引用, 安全回答不得伪装结论。"""
        # 正常回答必须携带引用
        if self.status is SpecificationQaStatus.ANSWERED and not self.citations:
            raise ValueError("answered specification response requires citations")
        # 安全回答不得携带引用
        if self.status is not SpecificationQaStatus.ANSWERED and self.citations:
            raise ValueError("safe specification response must not contain citations")
        if self.rerank_degraded != (
            self.status is SpecificationQaStatus.RERANK_UNAVAILABLE
        ):
            raise ValueError("rerank degradation must match response status")
        return self
