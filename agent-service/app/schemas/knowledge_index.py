"""知识索引入库结果与只读就绪能力契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeIndexSchema(BaseModel):
    """拒绝额外字段和隐式类型转换的知识索引公共Schema。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class KnowledgeIndexIdentity(KnowledgeIndexSchema):
    """一套可安全公开且必须整体匹配的Embedding索引身份。"""

    provider: Annotated[str, Field(min_length=1, max_length=64)]
    model: Annotated[str, Field(min_length=1, max_length=128)]
    dimension: Annotated[int, Field(gt=0)]
    index_version: Annotated[str, Field(min_length=1, max_length=128)]


class KnowledgeIngestionSummary(KnowledgeIndexSchema):
    """一次全量目录入库成功后的确定性摘要。"""

    document_count: Annotated[int, Field(gt=0)]
    chunk_count: Annotated[int, Field(gt=0)]
    removed_document_count: Annotated[int, Field(ge=0)]
    index: KnowledgeIndexIdentity


class KnowledgeIndexStatus(StrEnum):
    """区分空索引、目录不完整、身份不匹配和可用状态。"""

    NOT_INDEXED = "NOT_INDEXED"
    INCOMPLETE = "INCOMPLETE"
    INDEX_MISMATCH = "INDEX_MISMATCH"
    READY = "READY"


class KnowledgeIndexCapabilitiesResponse(KnowledgeIndexSchema):
    """知识索引当前状态、规模和预期/已存索引身份。"""

    ready: bool
    status: KnowledgeIndexStatus
    expected_document_count: Annotated[int, Field(gt=0)]
    document_count: Annotated[int, Field(ge=0)]
    chunk_count: Annotated[int, Field(ge=0)]
    expected_index: KnowledgeIndexIdentity
    stored_index: KnowledgeIndexIdentity | None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """防止就绪布尔值、状态和空索引统计互相矛盾。"""

        if self.ready is not (self.status is KnowledgeIndexStatus.READY):
            raise ValueError("ready must match knowledge index status")
        if self.status is KnowledgeIndexStatus.NOT_INDEXED and (
            self.document_count != 0 or self.chunk_count != 0 or self.stored_index is not None
        ):
            raise ValueError("not-indexed status requires empty index statistics")
        if self.ready and (
            self.document_count != self.expected_document_count
            or self.chunk_count == 0
            or self.stored_index != self.expected_index
        ):
            raise ValueError("ready knowledge index must match expected catalog and identity")
        return self


__all__ = [
    "KnowledgeIndexCapabilitiesResponse",
    "KnowledgeIndexIdentity",
    "KnowledgeIndexStatus",
    "KnowledgeIngestionSummary",
]
