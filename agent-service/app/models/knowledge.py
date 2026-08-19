"""知识文档和可检索分块的SQLAlchemy持久化模型。"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.schemas.knowledge import (
    EMBEDDING_DIMENSION,
    DocumentLifecycle,
    DocumentType,
    PermissionScope,
)


def _enum_column(enum_type: type[StrEnum], constraint_name: str, length: int) -> Enum:
    """使用可迁移的字符串枚举和数据库Check Constraint。"""

    return Enum(
        enum_type,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        length=length,
    )

# 保存文档级信息, 不保存切分后的正文内容
class KnowledgeDocument(Base):
    """一份已登记规范的身份、来源哈希、过滤元数据和版本状态。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "char_length(document_id) > 0",
            name="ck_knowledge_documents_id_not_blank",
        ),
        CheckConstraint(
            "char_length(title) > 0",
            name="ck_knowledge_documents_title_not_blank",
        ),
        CheckConstraint(
            "char_length(file_path) > 0",
            name="ck_knowledge_documents_path_not_blank",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_knowledge_documents_hash_length",
        ),
        CheckConstraint(
            "expiry_date IS NULL OR expiry_date >= effective_date",
            name="ck_knowledge_documents_date_order",
        ),
        CheckConstraint(
            "(lifecycle = 'ACTIVE' AND expiry_date IS NULL AND replaced_by IS NULL) "
            "OR (lifecycle = 'HISTORICAL' AND expiry_date IS NOT NULL "
            "AND replaced_by IS NOT NULL)",
            name="ck_knowledge_documents_lifecycle_fields",
        ),
        CheckConstraint(
            "(index_version IS NULL AND embedding_provider IS NULL "
            "AND embedding_model IS NULL AND embedding_dimension IS NULL "
            "AND indexed_at IS NULL) OR "
            "(index_version IS NOT NULL AND embedding_provider IS NOT NULL "
            "AND embedding_model IS NOT NULL AND embedding_dimension = 1536 "
            "AND indexed_at IS NOT NULL)",
            name="ck_knowledge_documents_embedding_index_fields",
        ),
        UniqueConstraint("file_path", name="uq_knowledge_documents_file_path"),
        UniqueConstraint("content_hash", name="uq_knowledge_documents_content_hash"),
        Index(
            "ix_knowledge_documents_filter",
            "lifecycle",
            "document_type",
            "product_type",
            "satellite_type",
            "processing_level",
        ),
    )

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # 保存文档正文的SHA-256值, 长度固定为64
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[DocumentLifecycle] = mapped_column(
        _enum_column(DocumentLifecycle, "ck_knowledge_documents_lifecycle", 16),
        nullable=False,
    )
    # replaced_by自关联外键 用于表示历史版本替代关系
    replaced_by: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_documents.document_id"),
        nullable=True,
    )
    document_type: Mapped[DocumentType] = mapped_column(
        _enum_column(DocumentType, "ck_knowledge_documents_type", 32),
        nullable=False,
    )
    satellite_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_level: Mapped[str | None] = mapped_column(String(128), nullable=True)
    specification_version: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    permission_scope: Mapped[PermissionScope] = mapped_column(
        _enum_column(PermissionScope, "ck_knowledge_documents_permission", 32),
        nullable=False,
    )
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    replacement: Mapped[KnowledgeDocument | None] = relationship(
        remote_side=[document_id],
        foreign_keys=[replaced_by],
    )
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

# 一份文档会被拆成多个分块的信息, 每个分块都有一个唯一的索引和路径标识
class KnowledgeChunk(Base):
    """文档中的稳定分块、全文检索字段和可空Embedding。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint(
            "char_length(chunk_id) > 0",
            name="ck_knowledge_chunks_id_not_blank",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_chunks_index_nonnegative",
        ),
        CheckConstraint(
            "char_length(content) > 0",
            name="ck_knowledge_chunks_content_not_blank",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_knowledge_chunks_hash_length",
        ),
        CheckConstraint(
            "token_count > 0",
            name="ck_knowledge_chunks_token_count_positive",
        ),
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_index",
        ),
        Index(
            "ix_knowledge_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_knowledge_chunks_embedding_cosine",
            "embedding",
            postgresql_using="hnsw",  # 近似最近邻索引类型
            # m控制图中每个节点的连接数量, ef_construction控制构建时的候选集合规模
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},  # 按余弦距离组织索引
        ),
    )

    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    # 保证同一文档不能出现两个“第0块”
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 它记录分块在Markdown中的标题位置
    section_path: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    search_document: Mapped[str] = mapped_column(Text, nullable=False)
    # 向量维度与M4.4选定的索引契约一致, 防止不同模型结果混写。
    embedding: Mapped[list[float] | None] = mapped_column(
        VECTOR(EMBEDDING_DIMENSION), nullable=True
    )
    # 全文检索字段 用于后续的全文检索
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', search_document)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
