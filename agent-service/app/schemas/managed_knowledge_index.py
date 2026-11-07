"""按实际发布集合计算的管理库就绪契约，零发布不借用旧catalog计数。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.knowledge import MetadataText
from app.schemas.knowledge_index import (
    KnowledgeIndexCapabilitiesResponse,
    KnowledgeIndexIdentity,
    KnowledgeIndexStatus,
)
from app.schemas.managed_knowledge import NonnegativeCounter


class ManagedKnowledgeIndexIdentity(KnowledgeIndexIdentity):
    """保留已存分块版本，即使当前实现不支持也明确报告配置不匹配。"""

    chunking_version: MetadataText


MANAGED_INDEX_DESCRIPTIONS = {
    KnowledgeIndexStatus.NOT_INDEXED: ("NO_PUBLISHED_DOCUMENTS", "无已发布资料"),
    KnowledgeIndexStatus.INCOMPLETE: ("PUBLISHED_INDEX_INCOMPLETE", "已发布索引不完整"),
    KnowledgeIndexStatus.INDEX_MISMATCH: ("INDEX_IDENTITY_MISMATCH", "已发布索引与当前配置不匹配"),
    KnowledgeIndexStatus.READY: ("PUBLISHED_INDEX_READY", "已发布索引可用"),
}


class ManagedKnowledgeIndexCapabilities(KnowledgeIndexCapabilitiesResponse):
    """单次发布快照的全量索引检查，不代表真实问答质量或默认切源。"""

    source: Literal["MANAGED"] = "MANAGED"
    configured_source_mode: Literal["LEGACY", "MANAGED"]
    release_revision: NonnegativeCounter
    expected_document_count: Annotated[int, Field(ge=0)]
    expected_index: ManagedKnowledgeIndexIdentity
    stored_index: ManagedKnowledgeIndexIdentity | None
    reason: Literal[
        "NO_PUBLISHED_DOCUMENTS",
        "PUBLISHED_INDEX_INCOMPLETE",
        "INDEX_IDENTITY_MISMATCH",
        "PUBLISHED_INDEX_READY",
    ]
    message: Literal[
        "无已发布资料", "已发布索引不完整", "已发布索引与当前配置不匹配", "已发布索引可用"
    ]

    @model_validator(mode="after")
    def validate_published_state(self) -> Self:
        """状态、动态集合、计数和安全文案必须一致，不能用空集合宣称READY。"""

        if (self.reason, self.message) != MANAGED_INDEX_DESCRIPTIONS[self.status]:
            raise ValueError("managed readiness reason must match status")
        if self.document_count > self.expected_document_count:
            raise ValueError("resolved count cannot exceed published target count")
        if self.status == KnowledgeIndexStatus.NOT_INDEXED:
            if self.expected_document_count != 0:
                raise ValueError("not-indexed managed library must have no published targets")
        elif self.expected_document_count == 0:
            raise ValueError("nonempty managed readiness state requires published targets")
        if self.status == KnowledgeIndexStatus.INDEX_MISMATCH and (
            self.document_count != self.expected_document_count
            or self.chunk_count == 0
            or self.stored_index == self.expected_index
        ):
            raise ValueError("index mismatch requires complete published relationships")
        return self
