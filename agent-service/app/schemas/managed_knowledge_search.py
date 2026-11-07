"""管理库内部检索范围与证据定位，不改变现有HTTP或旧库检索契约。"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.knowledge import (
    DocumentIdentifier,
    KnowledgeSchema,
    KnowledgeSearchFilter,
    MetadataText,
)
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge import ManagedIdentifier, NonnegativeCounter, PositiveRevision


class ManagedKnowledgeSearchFilter(KnowledgeSearchFilter):
    """沿用必选日期/权限，管理库另支持精确收窄处理级别。"""

    processing_level: MetadataText | None = None


class ManagedKnowledgeSearchOptions(KnowledgeSchema):
    """两路及融合数量有界，不接受布尔值冒充数量或阈值。"""

    channel_top_k: Annotated[int, Field(ge=1, le=100)] = 20
    hybrid_top_k: Annotated[int, Field(ge=1, le=100)] = 10
    min_vector_similarity: Annotated[float, Field(ge=-1.0, le=1.0, allow_inf_nan=False)] = -1.0


class ManagedKnowledgeReadContext(KnowledgeSchema):
    """显式读取管理库与当前默认配置分开，返回本次SQL快照的发布计数。"""

    source: Literal["MANAGED"] = "MANAGED"
    configured_source_mode: Literal["LEGACY", "MANAGED"]
    release_revision: NonnegativeCounter
    index: KnowledgePublicationIndexIdentity


class ManagedKnowledgeEvidence(KnowledgeSchema):
    """将原引用和稳定Chunk定位到本次实际封存修订及索引批次。"""

    citation_document_id: DocumentIdentifier
    chunk_id: Annotated[str, Field(min_length=1, max_length=128)]
    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    generation_id: ManagedIdentifier
