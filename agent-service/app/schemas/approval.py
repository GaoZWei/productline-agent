"""人工确认阶段使用的强类型复核草稿契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.knowledge import Citation
from app.schemas.tools import BusinessIdentifier, TaskIdentifier


# 复核结论枚举
class Conclusion(StrEnum):
    """Java允许写入的最终复核结论, 明确排除非终态PENDING。"""

    APPROVED = "APPROVED"  # 复核通过
    REJECTED = "REJECTED"  # 复核拒绝
    REWORK_REQUIRED = "REWORK_REQUIRED"  # 复核需要返工

# 返工类型枚举
class ReworkType(StrEnum):
    """当前黄金场景允许生成的稳定返工建议类型。"""
    # 当前只实现了黄金场景中的坐标系统返工
    COORDINATE_SYSTEM_FIX = "COORDINATE_SYSTEM_FIX"

# 字段类型和长度限制
ConclusionValue = Annotated[Conclusion, Field(strict=False)]  # 复核结论, strict=False允许Pydantic把合法字符串转换为枚举值
ReworkTypeValue = Annotated[ReworkType, Field(strict=False)]
ProblemSummary = Annotated[str, Field(min_length=1, max_length=2048)]  # 用于描述本次复核发现的问题
ReviewComment = Annotated[str, Field(min_length=1, max_length=1000)]  # 复核评论
SpecificationReferences = Annotated[
    tuple[Citation, ...],
    Field(strict=False),
]

# 公共配置 所有Approval草稿对象的公共安全规则
class ApprovalDraftSchema(BaseModel):
    """草稿拒绝额外字段和隐式类型转换, 创建后保持不可变。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 返工建议对象
class ReworkSuggestion(ApprovalDraftSchema):
    """表达是否建议返工及其稳定类型, 两个字段必须语义一致。"""

    required: bool  # 是否需要返工
    type: ReworkTypeValue | None = None  # 返工类型
    # 校验规则
    @model_validator(mode="after")
    def validate_required_type_pair(self) -> Self:
        """需要返工时必须给类型, 不需要返工时不得残留类型。"""

        if self.required != (self.type is not None):
            raise ValueError("rework type must be present if and only if rework is required")
        return self

# 复核草稿对象
class ReviewDraft(ApprovalDraftSchema):
    """保存复核结论、说明、规范依据和可选返工建议的完整草稿。"""

    task_id: TaskIdentifier  # 草稿作用于哪个生产任务
    issue_id: BusinessIdentifier  # 草稿作用于哪个质检问题, 写Tool不得临时猜测
    conclusion: ConclusionValue  # 复核结论
    problem_summary: ProblemSummary  # 问题事实的摘要
    review_comment: ReviewComment  # 将写入Java复核记录的意见
    specification_references: SpecificationReferences = ()  # 支撑意见的规范版本和Chunk来源
    suggested_rework: ReworkSuggestion  # 是否建议创建返工任务

    @field_validator("specification_references", mode="before")
    @classmethod
    def normalize_json_reference_sequences(cls, value: object) -> object:
        """只把JSON数组恢复成Citation严格契约要求的元组。"""

        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[object] = []
        for reference in value:
            if not isinstance(reference, dict):
                normalized.append(reference)
                continue
            normalized_reference = dict(reference)
            # 只把JSON数组恢复成Citation严格契约要求的元组
            for field_name in ("section", "chunk_ids"):
                field_value = normalized_reference.get(field_name)
                if isinstance(field_value, list):
                    normalized_reference[field_name] = tuple(field_value)
            normalized.append(normalized_reference)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_conclusion_and_references(self) -> Self:
        """让结论、返工建议和引用身份保持一致且无重复来源。"""
        # 校验结论和返工建议是否一致
        requires_rework = self.conclusion is Conclusion.REWORK_REQUIRED
        if self.suggested_rework.required != requires_rework:
            raise ValueError("REWORK_REQUIRED conclusion must match the rework suggestion")

        seen_chunks: set[tuple[str, str, str]] = set()
        for reference in self.specification_references:
            for chunk_id in reference.chunk_ids:
                # 重复规范引用校验
                identity = (
                    reference.document_id,
                    reference.document_version,
                    chunk_id,
                )
                if identity in seen_chunks:
                    raise ValueError("specification references must not repeat source chunks")
                seen_chunks.add(identity)
        return self
