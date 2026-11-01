"""补齐管理操作、任务、候选索引及版本封存关系。

Revision ID: 0016_managed_knowledge_state
Revises: 0015_managed_knowledge_drafts
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_managed_knowledge_state"
down_revision: str | None = "0015_managed_knowledge_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅扩充管理模型，不导入资料、激活检索源或启动任务。"""

    op.add_column("managed_knowledge_versions", sa.Column("published_revision_no", sa.Integer()))
    op.add_column("managed_knowledge_versions", sa.Column("published_generation_id", sa.String(128)))
    op.add_column("managed_knowledge_versions", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_mkv_draft_only", "managed_knowledge_versions", type_="check")
    # 固化本版DDL，不导入随应用演进的ORM或枚举。
    op.execute(
        """
        CREATE TABLE managed_knowledge_index_generations (
            generation_id VARCHAR(128) NOT NULL,
            version_id VARCHAR(128) NOT NULL,
            revision_no INTEGER NOT NULL,
            embedding_provider VARCHAR(64) NOT NULL,
            embedding_model VARCHAR(128) NOT NULL,
            embedding_dimension INTEGER NOT NULL,
            index_version VARCHAR(128) NOT NULL,
            chunking_version VARCHAR(128) NOT NULL,
            input_hash VARCHAR(64) NOT NULL,
            build_method VARCHAR(32) NOT NULL,
            state VARCHAR(16) DEFAULT 'BUILDING' NOT NULL,
            chunk_count BIGINT DEFAULT '0' NOT NULL,
            error_code VARCHAR(64),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            finished_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (generation_id),
            CONSTRAINT ck_mkg_id CHECK (generation_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'),
            CONSTRAINT fk_mkg_revision FOREIGN KEY(version_id, revision_no) REFERENCES managed_knowledge_revisions (version_id, revision_no),
            CONSTRAINT uq_mkg_revision_id UNIQUE (version_id, revision_no, generation_id),
            CONSTRAINT ck_mkg_dimension CHECK (embedding_dimension = 1536),
            CONSTRAINT ck_mkg_input_hash CHECK (input_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_mkg_chunk_count CHECK (chunk_count >= 0),
            CONSTRAINT ck_mkg_method CHECK (build_method IN ('GENERATED', 'COPIED_LEGACY')),
            CONSTRAINT ck_mkg_identity CHECK (length(btrim(embedding_provider)) > 0 AND length(btrim(embedding_model)) > 0 AND length(btrim(index_version)) > 0 AND length(btrim(chunking_version)) > 0),
            CONSTRAINT ck_mkg_error CHECK (error_code IS NULL OR error_code IN ('PARSE_FAILED', 'STORAGE_ERROR', 'INDEX_BUILD_FAILED', 'INDEX_VALIDATION_FAILED', 'TOOL_TIMEOUT', 'UPSTREAM_UNAVAILABLE', 'PERMISSION_DENIED', 'MODEL_OUTPUT_VALIDATION_ERROR', 'PROCESSING_INTERRUPTED', 'STALE_INPUT')),
            CONSTRAINT ck_mkg_state_fields CHECK ((state = 'BUILDING' AND finished_at IS NULL AND error_code IS NULL) OR (state = 'READY' AND finished_at IS NOT NULL AND error_code IS NULL AND chunk_count > 0) OR (state = 'FAILED' AND finished_at IS NOT NULL AND error_code IS NOT NULL)),
            CONSTRAINT ck_mkg_times CHECK (finished_at IS NULL OR finished_at >= created_at)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE managed_knowledge_operations (
            operation_id VARCHAR(128) NOT NULL,
            actor_id VARCHAR(128) NOT NULL,
            action VARCHAR(16) NOT NULL,
            version_id VARCHAR(128) NOT NULL,
            revision_no INTEGER NOT NULL,
            target_type VARCHAR(16) DEFAULT 'VERSION' NOT NULL,
            target_id VARCHAR(128) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            input_hash VARCHAR(64) NOT NULL,
            confirmation_snapshot JSONB NOT NULL,
            state VARCHAR(16) DEFAULT 'CONFIRMED' NOT NULL,
            result_id VARCHAR(128),
            error_code VARCHAR(64),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            finished_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (operation_id),
            CONSTRAINT ck_mko_id CHECK (operation_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'),
            CONSTRAINT fk_mko_revision FOREIGN KEY(version_id, revision_no) REFERENCES managed_knowledge_revisions (version_id, revision_no),
            CONSTRAINT uq_mko_idempotency UNIQUE (actor_id, action, idempotency_key),
            CONSTRAINT uq_mko_target UNIQUE (version_id, revision_no, operation_id, action),
            CONSTRAINT ck_mko_action CHECK (action IN ('UPLOAD', 'PUBLISH', 'DISABLE', 'RETRY_INDEX')),
            CONSTRAINT ck_mko_target CHECK (target_type = 'VERSION' AND target_id = version_id),
            CONSTRAINT ck_mko_actor CHECK (length(btrim(actor_id)) > 0),
            CONSTRAINT ck_mko_key CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
            CONSTRAINT ck_mko_input_hash CHECK (input_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_mko_snapshot CHECK (COALESCE((jsonb_typeof(confirmation_snapshot) = 'object' AND confirmation_snapshot ->> 'actor_id' = actor_id AND confirmation_snapshot ->> 'action' = action AND confirmation_snapshot ->> 'version_id' = version_id AND confirmation_snapshot ->> 'revision_no' = revision_no::text AND confirmation_snapshot ->> 'library_id' = 'DEFAULT' AND confirmation_snapshot ->> 'raw_hash' ~ '^[0-9a-f]{64}$' AND confirmation_snapshot ->> 'metadata_hash' ~ '^[0-9a-f]{64}$' AND confirmation_snapshot ->> 'expected_row_version' ~ '^[0-9]+$' AND confirmation_snapshot ?& ARRAY['actor_id', 'action', 'library_id', 'document_id', 'version_id', 'revision_no', 'raw_hash', 'metadata_hash', 'expected_row_version'] AND confirmation_snapshot - ARRAY['actor_id', 'action', 'library_id', 'document_id', 'version_id', 'revision_no', 'raw_hash', 'normalized_hash', 'metadata_hash', 'expected_row_version', 'previous_version_id', 'task_id', 'generation_id'] = '{}'::jsonb), false)),
            CONSTRAINT ck_mko_error CHECK (error_code IS NULL OR error_code IN ('PARSE_FAILED', 'STORAGE_ERROR', 'INDEX_BUILD_FAILED', 'INDEX_VALIDATION_FAILED', 'TOOL_TIMEOUT', 'UPSTREAM_UNAVAILABLE', 'PERMISSION_DENIED', 'MODEL_OUTPUT_VALIDATION_ERROR', 'PROCESSING_INTERRUPTED', 'STALE_INPUT')),
            CONSTRAINT ck_mko_state_fields CHECK ((state IN ('CONFIRMED', 'EXECUTING') AND finished_at IS NULL AND error_code IS NULL AND result_id IS NULL) OR (state = 'SUCCEEDED' AND finished_at IS NOT NULL AND error_code IS NULL AND result_id IS NOT NULL) OR (state IN ('FAILED', 'STALE') AND finished_at IS NOT NULL AND error_code IS NOT NULL AND result_id IS NULL)),
            CONSTRAINT ck_mko_times CHECK (finished_at IS NULL OR finished_at >= created_at)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE managed_knowledge_tasks (
            task_id VARCHAR(128) NOT NULL,
            operation_id VARCHAR(128) NOT NULL,
            operation_action VARCHAR(16) NOT NULL,
            version_id VARCHAR(128) NOT NULL,
            revision_no INTEGER NOT NULL,
            task_type VARCHAR(8) NOT NULL,
            generation_id VARCHAR(128),
            state VARCHAR(16) DEFAULT 'QUEUED' NOT NULL,
            owner_id VARCHAR(128) NOT NULL,
            attempt_no BIGINT DEFAULT '1' NOT NULL,
            retry_of_task_id VARCHAR(128),
            trace_id VARCHAR(128) NOT NULL,
            error_code VARCHAR(64),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            started_at TIMESTAMP WITH TIME ZONE,
            finished_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (task_id),
            CONSTRAINT ck_mkt_id CHECK (task_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'),
            CONSTRAINT fk_mkt_operation FOREIGN KEY(version_id, revision_no, operation_id, operation_action) REFERENCES managed_knowledge_operations (version_id, revision_no, operation_id, action),
            CONSTRAINT fk_mkt_generation FOREIGN KEY(version_id, revision_no, generation_id) REFERENCES managed_knowledge_index_generations (version_id, revision_no, generation_id),
            CONSTRAINT fk_mkt_retry FOREIGN KEY(version_id, revision_no, task_type, retry_of_task_id) REFERENCES managed_knowledge_tasks (version_id, revision_no, task_type, task_id),
            CONSTRAINT uq_mkt_retry_target UNIQUE (version_id, revision_no, task_type, task_id),
            CONSTRAINT uq_mkt_operation_type UNIQUE (operation_id, task_type),
            CONSTRAINT uq_mkt_generation UNIQUE (generation_id),
            CONSTRAINT ck_mkt_type_fields CHECK ((task_type = 'PARSE' AND generation_id IS NULL AND operation_action = 'UPLOAD') OR (task_type = 'INDEX' AND generation_id IS NOT NULL AND operation_action IN ('PUBLISH', 'RETRY_INDEX'))),
            CONSTRAINT ck_mkt_attempt CHECK ((retry_of_task_id IS NULL AND attempt_no = 1 AND operation_action <> 'RETRY_INDEX') OR (retry_of_task_id IS NOT NULL AND retry_of_task_id <> task_id AND attempt_no > 1 AND task_type = 'INDEX' AND operation_action = 'RETRY_INDEX')),
            CONSTRAINT ck_mkt_owner CHECK (length(btrim(owner_id)) > 0),
            CONSTRAINT ck_mkt_trace CHECK (trace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
            CONSTRAINT ck_mkt_error CHECK (error_code IS NULL OR error_code IN ('PARSE_FAILED', 'STORAGE_ERROR', 'INDEX_BUILD_FAILED', 'INDEX_VALIDATION_FAILED', 'TOOL_TIMEOUT', 'UPSTREAM_UNAVAILABLE', 'PERMISSION_DENIED', 'MODEL_OUTPUT_VALIDATION_ERROR', 'PROCESSING_INTERRUPTED', 'STALE_INPUT')),
            CONSTRAINT ck_mkt_state_fields CHECK ((state = 'QUEUED' AND started_at IS NULL AND finished_at IS NULL AND error_code IS NULL) OR (state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND error_code IS NULL) OR (state = 'SUCCEEDED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND error_code IS NULL) OR (state IN ('FAILED', 'INTERRUPTED', 'STALE') AND finished_at IS NOT NULL AND error_code IS NOT NULL)),
            CONSTRAINT ck_mkt_times CHECK ((started_at IS NULL OR started_at >= created_at) AND (finished_at IS NULL OR finished_at >= COALESCE(started_at, created_at)))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE managed_knowledge_chunks (
            generation_id VARCHAR(128) NOT NULL,
            chunk_id VARCHAR(128) NOT NULL,
            chunk_index BIGINT NOT NULL,
            section_path JSONB NOT NULL,
            content TEXT NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            token_count BIGINT NOT NULL,
            search_document TEXT NOT NULL,
            embedding VECTOR(1536) NOT NULL,
            search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', search_document)) STORED NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (generation_id, chunk_id),
            CONSTRAINT uq_mkc_generation_index UNIQUE (generation_id, chunk_index),
            CONSTRAINT ck_mkc_counts CHECK (chunk_index >= 0 AND token_count > 0),
            CONSTRAINT ck_mkc_id CHECK (chunk_id ~ '^[A-Za-z0-9._:-]+$'),
            CONSTRAINT ck_mkc_content CHECK (length(btrim(content)) > 0),
            CONSTRAINT ck_mkc_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_mkc_search CHECK (length(btrim(search_document)) > 0),
            CONSTRAINT ck_mkc_section CHECK (CASE WHEN jsonb_typeof(section_path) = 'array' THEN jsonb_array_length(section_path) BETWEEN 1 AND 16 ELSE false END),
            CONSTRAINT fk_mkc_generation FOREIGN KEY(generation_id) REFERENCES managed_knowledge_index_generations (generation_id)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_mkt_active ON managed_knowledge_tasks (version_id, revision_no, task_type) WHERE state IN ('QUEUED', 'RUNNING')
        """
    )
    op.execute(
        """
        CREATE INDEX ix_mkc_embedding_cosine ON managed_knowledge_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_mkc_search_vector ON managed_knowledge_chunks USING gin (search_vector)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_mkv_one_published ON managed_knowledge_versions (document_id) WHERE publication_state = 'PUBLISHED'
        """
    )
    op.execute(
        """
        ALTER TABLE managed_knowledge_versions ADD CONSTRAINT ck_mkv_publication_state CHECK (publication_state IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'DISABLED', 'HISTORICAL'))
        """
    )
    op.execute(
        """
        ALTER TABLE managed_knowledge_versions ADD CONSTRAINT fk_mkv_published_generation FOREIGN KEY(version_id, published_revision_no, published_generation_id) REFERENCES managed_knowledge_index_generations (version_id, revision_no, generation_id)
        """
    )
    op.execute(
        """
        ALTER TABLE managed_knowledge_versions ADD CONSTRAINT ck_mkv_publication_fields CHECK ((publication_state = 'DRAFT' AND published_revision_no IS NULL AND published_generation_id IS NULL AND published_at IS NULL) OR (publication_state IN ('PUBLISHED', 'SUPERSEDED', 'DISABLED', 'HISTORICAL') AND published_revision_no IS NOT NULL AND published_revision_no = current_revision_no AND published_generation_id IS NOT NULL AND ((publication_state = 'HISTORICAL' AND source_kind = 'CATALOG_IMPORT' AND source_lifecycle = 'HISTORICAL' AND published_at IS NULL) OR (publication_state <> 'HISTORICAL' AND published_at IS NOT NULL AND published_at >= created_at))))
        """
    )


def downgrade() -> None:
    """只撤销本版对象，有封存版本时拒绝降级以保留历史证据。"""

    # 先验证旧版可承载现有状态，失败时整笔DDL事务回滚，不能静默改写发布历史。
    op.create_check_constraint(
        "ck_mkv_draft_only", "managed_knowledge_versions", "publication_state = 'DRAFT'"
    )
    op.drop_constraint("fk_mkv_published_generation", "managed_knowledge_versions", type_="foreignkey")
    op.drop_index("uq_mkv_one_published", table_name="managed_knowledge_versions")
    op.drop_constraint("ck_mkv_publication_fields", "managed_knowledge_versions", type_="check")
    op.drop_constraint("ck_mkv_publication_state", "managed_knowledge_versions", type_="check")
    op.drop_column("managed_knowledge_versions", "published_at")
    op.drop_column("managed_knowledge_versions", "published_generation_id")
    op.drop_column("managed_knowledge_versions", "published_revision_no")
    op.drop_table("managed_knowledge_tasks")
    op.drop_table("managed_knowledge_chunks")
    op.drop_table("managed_knowledge_operations")
    op.drop_table("managed_knowledge_index_generations")
