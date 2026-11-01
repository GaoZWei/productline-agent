"""与旧CLI隔离的资料及版本表，不执行授权、任务或发布操作。"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ManagedKnowledgeLibrary(Base):
    """单例内部库，当前迁移禁止切换检索源。"""

    __tablename__ = "managed_knowledge_libraries"
    __table_args__ = (
        CheckConstraint("library_id = 'DEFAULT'", name="ck_mkl_singleton"),
        CheckConstraint("source_mode = 'LEGACY'", name="ck_mkl_source_mode"),
        CheckConstraint("release_revision >= 0", name="ck_mkl_release_revision"),
        CheckConstraint(
            "source_catalog_hash IS NULL OR source_catalog_hash ~ '^[0-9a-f]{64}$'",
            name="ck_mkl_catalog_hash",
        ),
        CheckConstraint("activated_at IS NULL", name="ck_mkl_not_activated"),
    )

    library_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_mode: Mapped[str] = mapped_column(String(16), server_default="LEGACY")
    release_revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    source_catalog_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManagedKnowledgeDocument(Base):
    """稳定逻辑资料及乐观并发计数，当前指针受资料归属约束。"""

    __tablename__ = "managed_knowledge_documents"
    __table_args__ = (
        CheckConstraint("document_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'", name="ck_mkd_id"),
        CheckConstraint("row_version >= 0", name="ck_mkd_row_version"),
        CheckConstraint("length(btrim(created_by)) > 0", name="ck_mkd_actor"),
        ForeignKeyConstraint(
            ["document_id", "current_version_id"],
            ["managed_knowledge_versions.document_id", "managed_knowledge_versions.version_id"],
            name="fk_mkd_current_version",
            use_alter=True,
        ),
    )

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    library_id: Mapped[str] = mapped_column(
        ForeignKey("managed_knowledge_libraries.library_id", name="fk_mkd_library"),
        server_default="DEFAULT",
    )
    current_version_id: Mapped[str | None] = mapped_column(String(128))
    row_version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManagedKnowledgeVersion(Base):
    """规范版本、当前修订及封存索引关系，发布行为仍由后续事务负责。"""

    __tablename__ = "managed_knowledge_versions"
    __table_args__ = (
        CheckConstraint("version_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'", name="ck_mkv_id"),
        CheckConstraint(
            "publication_state IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'DISABLED', 'HISTORICAL')",
            name="ck_mkv_publication_state",
        ),
        CheckConstraint(
            "(publication_state = 'DRAFT' AND published_revision_no IS NULL "
            "AND published_generation_id IS NULL AND published_at IS NULL) OR "
            "(publication_state IN ('PUBLISHED', 'SUPERSEDED', 'DISABLED', 'HISTORICAL') "
            "AND published_revision_no IS NOT NULL AND published_revision_no = current_revision_no "
            "AND published_generation_id IS NOT NULL AND "
            "((publication_state = 'HISTORICAL' AND source_kind = 'CATALOG_IMPORT' "
            "AND source_lifecycle = 'HISTORICAL' AND published_at IS NULL) OR "
            "(publication_state <> 'HISTORICAL' AND published_at IS NOT NULL "
            "AND published_at >= created_at)))",
            name="ck_mkv_publication_fields",
        ),
        CheckConstraint("current_revision_no > 0", name="ck_mkv_revision_positive"),
        CheckConstraint("specification_version ~ '^[0-9]+([.][0-9]+)*$'", name="ck_mkv_spec"),
        CheckConstraint(
            "citation_document_id ~ '^[A-Z0-9]+(-[A-Z0-9]+)*$'",
            name="ck_mkv_citation_id",
        ),
        CheckConstraint("length(btrim(created_by)) > 0", name="ck_mkv_actor"),
        CheckConstraint(
            "(source_kind = 'UPLOAD' AND citation_document_id = version_id "
            "AND source_document_id IS NULL AND source_catalog_hash IS NULL "
            "AND source_lifecycle IS NULL AND source_replaced_by IS NULL) OR "
            "(source_kind = 'CATALOG_IMPORT' AND source_document_id IS NOT NULL "
            "AND citation_document_id = source_document_id AND source_catalog_hash IS NOT NULL "
            "AND source_catalog_hash ~ '^[0-9a-f]{64}$' AND source_lifecycle IS NOT NULL AND "
            "((source_lifecycle = 'ACTIVE' AND source_replaced_by IS NULL) OR "
            "(source_lifecycle = 'HISTORICAL' AND source_replaced_by IS NOT NULL "
            "AND source_replaced_by <> source_document_id)))",
            name="ck_mkv_provenance",
        ),
        UniqueConstraint("document_id", "specification_version", name="uq_mkv_document_spec"),
        UniqueConstraint("document_id", "version_id", name="uq_mkv_document_version"),
        UniqueConstraint("version_id", "specification_version", name="uq_mkv_version_spec"),
        UniqueConstraint("citation_document_id", name="uq_mkv_citation"),
        ForeignKeyConstraint(
            ["version_id", "current_revision_no"],
            ["managed_knowledge_revisions.version_id", "managed_knowledge_revisions.revision_no"],
            name="fk_mkv_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["version_id", "published_revision_no", "published_generation_id"],
            [
                "managed_knowledge_index_generations.version_id",
                "managed_knowledge_index_generations.revision_no",
                "managed_knowledge_index_generations.generation_id",
            ],
            name="fk_mkv_published_generation",
            use_alter=True,
        ),
        Index(
            "uq_mkv_one_published",
            "document_id",
            unique=True,
            postgresql_where=text("publication_state = 'PUBLISHED'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("managed_knowledge_documents.document_id", name="fk_mkv_document")
    )
    specification_version: Mapped[str] = mapped_column(String(64))
    citation_document_id: Mapped[str] = mapped_column(String(128))
    current_revision_no: Mapped[int] = mapped_column(Integer, server_default="1")
    publication_state: Mapped[str] = mapped_column(String(16), server_default="DRAFT")
    published_revision_no: Mapped[int | None] = mapped_column(Integer)
    published_generation_id: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_kind: Mapped[str] = mapped_column(String(32))
    source_document_id: Mapped[str | None] = mapped_column(String(128))
    source_catalog_hash: Mapped[str | None] = mapped_column(String(64))
    source_lifecycle: Mapped[str | None] = mapped_column(String(16))
    source_replaced_by: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManagedKnowledgeRevision(Base):
    """修订原件、业务元数据和可空解析结果，不映射旧表关系。"""

    __tablename__ = "managed_knowledge_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "specification_version"],
            [
                "managed_knowledge_versions.version_id",
                "managed_knowledge_versions.specification_version",
            ],
            name="fk_mkr_version_spec",
        ),
        UniqueConstraint("original_key", name="uq_mkr_original_key"),
        CheckConstraint("revision_no > 0", name="ck_mkr_revision_positive"),
        CheckConstraint("byte_size > 0 AND byte_size <= 10485760", name="ck_mkr_byte_size"),
        CheckConstraint("file_format IN ('MD', 'TXT')", name="ck_mkr_file_format"),
        CheckConstraint(
            "original_key = 'versions/' || version_id || '/revisions/' || revision_no::text "
            "|| '/original.' || CASE WHEN file_format = 'MD' THEN 'md' ELSE 'txt' END",
            name="ck_mkr_original_key",
        ),
        CheckConstraint("raw_hash ~ '^[0-9a-f]{64}$'", name="ck_mkr_raw_hash"),
        CheckConstraint("metadata_hash ~ '^[0-9a-f]{64}$'", name="ck_mkr_metadata_hash"),
        CheckConstraint(
            "(body IS NULL AND normalized_hash IS NULL) OR "
            "(body IS NOT NULL AND length(btrim(body)) > 0 AND normalized_hash IS NOT NULL "
            "AND normalized_hash ~ '^[0-9a-f]{64}$')",
            name="ck_mkr_parse_pair",
        ),
        CheckConstraint(
            "expiry_date IS NULL OR expiry_date >= effective_date",
            name="ck_mkr_dates",
        ),
        CheckConstraint(
            "document_type IN ('DOM_PRODUCT_SPEC', 'QUALITY_SPEC', 'COORDINATE_SYSTEM_SPEC', "
            "'REVIEW_OPERATION_SPEC', 'DELIVERY_SPEC')",
            name="ck_mkr_type",
        ),
        CheckConstraint("permission_scope = 'INTERNAL_REVIEWER'", name="ck_mkr_scope"),
        CheckConstraint("is_demo AND maintainer = '演示维护用户'", name="ck_mkr_demo"),
        CheckConstraint(
            "length(btrim(title)) > 0 AND length(btrim(original_filename)) > 0 "
            "AND length(btrim(change_summary)) > 0 AND length(btrim(created_by)) > 0",
            name="ck_mkr_required_text",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    specification_version: Mapped[str] = mapped_column(String(64))
    original_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(256))
    file_format: Mapped[str] = mapped_column(String(8))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    raw_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str | None] = mapped_column(Text)
    normalized_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    document_type: Mapped[str] = mapped_column(String(32))
    satellite_type: Mapped[str | None] = mapped_column(String(128))
    product_type: Mapped[str | None] = mapped_column(String(128))
    processing_level: Mapped[str | None] = mapped_column(String(128))
    effective_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    permission_scope: Mapped[str] = mapped_column(String(32))
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="true")
    maintainer: Mapped[str] = mapped_column(String(128), server_default="演示维护用户")
    change_summary: Mapped[str] = mapped_column(String(2000))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
