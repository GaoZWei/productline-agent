"""管理操作、任务及候选索引模型，所有外部调用和执行流程留在应用层。"""

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 只存受控错误码，不能把供应商原始异常、凭据或正文写入任务记录。
_ERROR_CODES = (
    "'PARSE_FAILED', 'STORAGE_ERROR', 'INDEX_BUILD_FAILED', 'INDEX_VALIDATION_FAILED', "
    "'TOOL_TIMEOUT', 'UPSTREAM_UNAVAILABLE', 'PERMISSION_DENIED', "
    "'MODEL_OUTPUT_VALIDATION_ERROR', 'PROCESSING_INTERRUPTED', 'STALE_INPUT'"
)


class ManagedKnowledgeIndexGeneration(Base):
    """一次修订的一次构建，READY只表示候选完成，不授予发布资格。"""

    __tablename__ = "managed_knowledge_index_generations"
    __table_args__ = (
        CheckConstraint("generation_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'", name="ck_mkg_id"),
        ForeignKeyConstraint(
            ["version_id", "revision_no"],
            ["managed_knowledge_revisions.version_id", "managed_knowledge_revisions.revision_no"],
            name="fk_mkg_revision",
        ),
        UniqueConstraint("version_id", "revision_no", "generation_id", name="uq_mkg_revision_id"),
        CheckConstraint("embedding_dimension = 1536", name="ck_mkg_dimension"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_mkg_input_hash"),
        CheckConstraint("chunk_count >= 0", name="ck_mkg_chunk_count"),
        CheckConstraint("build_method IN ('GENERATED', 'COPIED_LEGACY')", name="ck_mkg_method"),
        CheckConstraint(
            "length(btrim(embedding_provider)) > 0 AND length(btrim(embedding_model)) > 0 "
            "AND length(btrim(index_version)) > 0 AND length(btrim(chunking_version)) > 0",
            name="ck_mkg_identity",
        ),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_ERROR_CODES})", name="ck_mkg_error"
        ),
        CheckConstraint(
            "(state = 'BUILDING' AND finished_at IS NULL AND error_code IS NULL) OR "
            "(state = 'READY' AND finished_at IS NOT NULL AND error_code IS NULL "
            "AND chunk_count > 0) OR "
            "(state = 'FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name="ck_mkg_state_fields",
        ),
        CheckConstraint("finished_at IS NULL OR finished_at >= created_at", name="ck_mkg_times"),
    )

    generation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(128))
    revision_no: Mapped[int] = mapped_column(Integer)
    embedding_provider: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(128))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    index_version: Mapped[str] = mapped_column(String(128))
    chunking_version: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    build_method: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), server_default="BUILDING")
    chunk_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManagedKnowledgeOperation(Base):
    """人工意图和幂等身份，确认快照不保存令牌、长正文或任意附加参数。"""

    __tablename__ = "managed_knowledge_operations"
    __table_args__ = (
        CheckConstraint("operation_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'", name="ck_mko_id"),
        ForeignKeyConstraint(
            ["version_id", "revision_no"],
            ["managed_knowledge_revisions.version_id", "managed_knowledge_revisions.revision_no"],
            name="fk_mko_revision",
        ),
        UniqueConstraint("actor_id", "action", "idempotency_key", name="uq_mko_idempotency"),
        UniqueConstraint(
            "version_id", "revision_no", "operation_id", "action", name="uq_mko_target"
        ),
        CheckConstraint(
            "action IN ('UPLOAD', 'PUBLISH', 'DISABLE', 'RETRY_INDEX')", name="ck_mko_action"
        ),
        CheckConstraint("target_type = 'VERSION' AND target_id = version_id", name="ck_mko_target"),
        CheckConstraint("length(btrim(actor_id)) > 0", name="ck_mko_actor"),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'", name="ck_mko_key"
        ),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_mko_input_hash"),
        CheckConstraint(
            "COALESCE((jsonb_typeof(confirmation_snapshot) = 'object' "
            "AND confirmation_snapshot ->> 'actor_id' = actor_id "
            "AND confirmation_snapshot ->> 'action' = action "
            "AND confirmation_snapshot ->> 'version_id' = version_id "
            "AND confirmation_snapshot ->> 'revision_no' = revision_no::text "
            "AND confirmation_snapshot ->> 'library_id' = 'DEFAULT' "
            "AND confirmation_snapshot ->> 'raw_hash' ~ '^[0-9a-f]{64}$' "
            "AND confirmation_snapshot ->> 'metadata_hash' ~ '^[0-9a-f]{64}$' "
            "AND confirmation_snapshot ->> 'expected_row_version' ~ '^[0-9]+$' "
            "AND confirmation_snapshot ?& ARRAY['actor_id', 'action', 'library_id', 'document_id', "
            "'version_id', 'revision_no', 'raw_hash', 'metadata_hash', 'expected_row_version'] "
            "AND confirmation_snapshot - ARRAY['actor_id', 'action', 'library_id', 'document_id', "
            "'version_id', 'revision_no', 'raw_hash', 'normalized_hash', 'metadata_hash', "
            "'expected_row_version', 'previous_version_id', 'task_id', 'generation_id'] "
            "= '{}'::jsonb), false)",
            name="ck_mko_snapshot",
        ),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_ERROR_CODES})", name="ck_mko_error"
        ),
        CheckConstraint(
            "(state IN ('CONFIRMED', 'EXECUTING') AND finished_at IS NULL "
            "AND error_code IS NULL AND result_id IS NULL) OR "
            "(state = 'SUCCEEDED' AND finished_at IS NOT NULL AND error_code IS NULL "
            "AND result_id IS NOT NULL) OR "
            "(state IN ('FAILED', 'STALE') AND finished_at IS NOT NULL "
            "AND error_code IS NOT NULL AND result_id IS NULL)",
            name="ck_mko_state_fields",
        ),
        CheckConstraint("finished_at IS NULL OR finished_at >= created_at", name="ck_mko_times"),
    )

    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(16))
    version_id: Mapped[str] = mapped_column(String(128))
    revision_no: Mapped[int] = mapped_column(Integer)
    target_type: Mapped[str] = mapped_column(String(16), server_default="VERSION")
    target_id: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    confirmation_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16), server_default="CONFIRMED")
    result_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManagedKnowledgeTask(Base):
    """任务输入绑定操作和修订，排他索引限制同修订同类任务并行执行。"""

    __tablename__ = "managed_knowledge_tasks"
    __table_args__ = (
        CheckConstraint("task_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'", name="ck_mkt_id"),
        ForeignKeyConstraint(
            ["version_id", "revision_no", "operation_id", "operation_action"],
            [
                "managed_knowledge_operations.version_id",
                "managed_knowledge_operations.revision_no",
                "managed_knowledge_operations.operation_id",
                "managed_knowledge_operations.action",
            ],
            name="fk_mkt_operation",
        ),
        ForeignKeyConstraint(
            ["version_id", "revision_no", "generation_id"],
            [
                "managed_knowledge_index_generations.version_id",
                "managed_knowledge_index_generations.revision_no",
                "managed_knowledge_index_generations.generation_id",
            ],
            name="fk_mkt_generation",
        ),
        ForeignKeyConstraint(
            ["version_id", "revision_no", "task_type", "retry_of_task_id"],
            [
                "managed_knowledge_tasks.version_id",
                "managed_knowledge_tasks.revision_no",
                "managed_knowledge_tasks.task_type",
                "managed_knowledge_tasks.task_id",
            ],
            name="fk_mkt_retry",
        ),
        UniqueConstraint(
            "version_id", "revision_no", "task_type", "task_id", name="uq_mkt_retry_target"
        ),
        UniqueConstraint("operation_id", "task_type", name="uq_mkt_operation_type"),
        UniqueConstraint("generation_id", name="uq_mkt_generation"),
        CheckConstraint(
            "(task_type = 'PARSE' AND generation_id IS NULL AND operation_action = 'UPLOAD') OR "
            "(task_type = 'INDEX' AND generation_id IS NOT NULL "
            "AND operation_action IN ('PUBLISH', 'RETRY_INDEX'))",
            name="ck_mkt_type_fields",
        ),
        CheckConstraint(
            "(retry_of_task_id IS NULL AND attempt_no = 1 "
            "AND operation_action <> 'RETRY_INDEX') OR "
            "(retry_of_task_id IS NOT NULL AND retry_of_task_id <> task_id "
            "AND attempt_no > 1 AND task_type = 'INDEX' AND operation_action = 'RETRY_INDEX')",
            name="ck_mkt_attempt",
        ),
        CheckConstraint("length(btrim(owner_id)) > 0", name="ck_mkt_owner"),
        CheckConstraint("trace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'", name="ck_mkt_trace"),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_ERROR_CODES})", name="ck_mkt_error"
        ),
        CheckConstraint(
            "(state = 'QUEUED' AND started_at IS NULL AND finished_at IS NULL "
            "AND error_code IS NULL) OR "
            "(state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL "
            "AND error_code IS NULL) OR "
            "(state = 'SUCCEEDED' AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND error_code IS NULL) OR (state IN ('FAILED', 'INTERRUPTED', 'STALE') "
            "AND finished_at IS NOT NULL AND error_code IS NOT NULL)",
            name="ck_mkt_state_fields",
        ),
        CheckConstraint(
            "(started_at IS NULL OR started_at >= created_at) "
            "AND (finished_at IS NULL OR finished_at >= COALESCE(started_at, created_at))",
            name="ck_mkt_times",
        ),
        Index(
            "uq_mkt_active",
            "version_id",
            "revision_no",
            "task_type",
            unique=True,
            postgresql_where=text("state IN ('QUEUED', 'RUNNING')"),
        ),
    )

    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128))
    operation_action: Mapped[str] = mapped_column(String(16))
    version_id: Mapped[str] = mapped_column(String(128))
    revision_no: Mapped[int] = mapped_column(Integer)
    task_type: Mapped[str] = mapped_column(String(8))
    generation_id: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(16), server_default="QUEUED")
    owner_id: Mapped[str] = mapped_column(String(128))
    attempt_no: Mapped[int] = mapped_column(BigInteger, server_default="1")
    retry_of_task_id: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManagedKnowledgeChunk(Base):
    """按批次保留原文与向量，候选和历史批次不自动进入默认检索。"""

    __tablename__ = "managed_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("generation_id", "chunk_index", name="uq_mkc_generation_index"),
        CheckConstraint("chunk_index >= 0 AND token_count > 0", name="ck_mkc_counts"),
        CheckConstraint("chunk_id ~ '^[A-Za-z0-9._:-]+$'", name="ck_mkc_id"),
        CheckConstraint("length(btrim(content)) > 0", name="ck_mkc_content"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_mkc_hash"),
        CheckConstraint("length(btrim(search_document)) > 0", name="ck_mkc_search"),
        CheckConstraint(
            "CASE WHEN jsonb_typeof(section_path) = 'array' "
            "THEN jsonb_array_length(section_path) BETWEEN 1 AND 16 ELSE false END",
            name="ck_mkc_section",
        ),
        Index("ix_mkc_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_mkc_embedding_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    generation_id: Mapped[str] = mapped_column(
        ForeignKey("managed_knowledge_index_generations.generation_id", name="fk_mkc_generation"),
        primary_key=True,
    )
    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    chunk_index: Mapped[int] = mapped_column(BigInteger)
    section_path: Mapped[list[str]] = mapped_column(JSONB)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(BigInteger)
    search_document: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(1536))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', search_document)", persisted=True),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
