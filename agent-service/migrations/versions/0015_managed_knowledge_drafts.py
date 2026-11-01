"""建立与旧知识索引隔离的草稿管理底座。

Revision ID: 0015_managed_knowledge_drafts
Revises: 0014_review_source_run
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_managed_knowledge_drafts"
down_revision: str | None = "0014_review_source_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅创建四张空管理表和LEGACY单例，不导入资料或切换问答源。"""

    # 固化本版PostgreSQL DDL，后续ORM变化不能改写既有迁移。
    op.execute(
        """
        CREATE TABLE managed_knowledge_libraries (
        	library_id VARCHAR(128) NOT NULL,
        	source_mode VARCHAR(16) DEFAULT 'LEGACY' NOT NULL,
        	release_revision BIGINT DEFAULT '0' NOT NULL,
        	source_catalog_hash VARCHAR(64),
        	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        	activated_at TIMESTAMP WITH TIME ZONE,
        	PRIMARY KEY (library_id),
        	CONSTRAINT ck_mkl_singleton CHECK (library_id = 'DEFAULT'),
        	CONSTRAINT ck_mkl_source_mode CHECK (source_mode = 'LEGACY'),
        	CONSTRAINT ck_mkl_release_revision CHECK (release_revision >= 0),
        	CONSTRAINT ck_mkl_catalog_hash CHECK (source_catalog_hash IS NULL OR source_catalog_hash ~ '^[0-9a-f]{64}$'),
        	CONSTRAINT ck_mkl_not_activated CHECK (activated_at IS NULL)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE managed_knowledge_documents (
        	document_id VARCHAR(128) NOT NULL,
        	library_id VARCHAR(128) DEFAULT 'DEFAULT' NOT NULL,
        	current_version_id VARCHAR(128),
        	row_version BIGINT DEFAULT '0' NOT NULL,
        	created_by VARCHAR(128) NOT NULL,
        	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        	PRIMARY KEY (document_id),
        	CONSTRAINT ck_mkd_id CHECK (document_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'),
        	CONSTRAINT ck_mkd_row_version CHECK (row_version >= 0),
        	CONSTRAINT ck_mkd_actor CHECK (length(btrim(created_by)) > 0),
        	CONSTRAINT fk_mkd_library FOREIGN KEY(library_id) REFERENCES managed_knowledge_libraries (library_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE managed_knowledge_versions (
        	version_id VARCHAR(128) NOT NULL,
        	document_id VARCHAR(128) NOT NULL,
        	specification_version VARCHAR(64) NOT NULL,
        	citation_document_id VARCHAR(128) NOT NULL,
        	current_revision_no INTEGER DEFAULT '1' NOT NULL,
        	publication_state VARCHAR(16) DEFAULT 'DRAFT' NOT NULL,
        	source_kind VARCHAR(32) NOT NULL,
        	source_document_id VARCHAR(128),
        	source_catalog_hash VARCHAR(64),
        	source_lifecycle VARCHAR(16),
        	source_replaced_by VARCHAR(128),
        	created_by VARCHAR(128) NOT NULL,
        	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        	PRIMARY KEY (version_id),
        	CONSTRAINT ck_mkv_id CHECK (version_id ~ '^[A-Z][A-Z0-9]*-[0-9A-F]{32}$'),
        	CONSTRAINT ck_mkv_draft_only CHECK (publication_state = 'DRAFT'),
        	CONSTRAINT ck_mkv_revision_positive CHECK (current_revision_no > 0),
        	CONSTRAINT ck_mkv_spec CHECK (specification_version ~ '^[0-9]+([.][0-9]+)*$'),
        	CONSTRAINT ck_mkv_citation_id CHECK (citation_document_id ~ '^[A-Z0-9]+(-[A-Z0-9]+)*$'),
        	CONSTRAINT ck_mkv_actor CHECK (length(btrim(created_by)) > 0),
        	CONSTRAINT ck_mkv_provenance CHECK ((source_kind = 'UPLOAD' AND citation_document_id = version_id AND source_document_id IS NULL AND source_catalog_hash IS NULL AND source_lifecycle IS NULL AND source_replaced_by IS NULL) OR (source_kind = 'CATALOG_IMPORT' AND source_document_id IS NOT NULL AND citation_document_id = source_document_id AND source_catalog_hash IS NOT NULL AND source_catalog_hash ~ '^[0-9a-f]{64}$' AND source_lifecycle IS NOT NULL AND ((source_lifecycle = 'ACTIVE' AND source_replaced_by IS NULL) OR (source_lifecycle = 'HISTORICAL' AND source_replaced_by IS NOT NULL AND source_replaced_by <> source_document_id)))),
        	CONSTRAINT uq_mkv_document_spec UNIQUE (document_id, specification_version),
        	CONSTRAINT uq_mkv_document_version UNIQUE (document_id, version_id),
        	CONSTRAINT uq_mkv_version_spec UNIQUE (version_id, specification_version),
        	CONSTRAINT uq_mkv_citation UNIQUE (citation_document_id),
        	CONSTRAINT fk_mkv_document FOREIGN KEY(document_id) REFERENCES managed_knowledge_documents (document_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE managed_knowledge_revisions (
        	version_id VARCHAR(128) NOT NULL,
        	revision_no INTEGER NOT NULL,
        	specification_version VARCHAR(64) NOT NULL,
        	original_key VARCHAR(512) NOT NULL,
        	original_filename VARCHAR(256) NOT NULL,
        	file_format VARCHAR(8) NOT NULL,
        	byte_size BIGINT NOT NULL,
        	raw_hash VARCHAR(64) NOT NULL,
        	body TEXT,
        	normalized_hash VARCHAR(64),
        	metadata_hash VARCHAR(64) NOT NULL,
        	title VARCHAR(256) NOT NULL,
        	document_type VARCHAR(32) NOT NULL,
        	satellite_type VARCHAR(128),
        	product_type VARCHAR(128),
        	processing_level VARCHAR(128),
        	effective_date DATE NOT NULL,
        	expiry_date DATE,
        	permission_scope VARCHAR(32) NOT NULL,
        	is_demo BOOLEAN DEFAULT 'true' NOT NULL,
        	maintainer VARCHAR(128) DEFAULT '演示维护用户' NOT NULL,
        	change_summary VARCHAR(2000) NOT NULL,
        	created_by VARCHAR(128) NOT NULL,
        	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        	PRIMARY KEY (version_id, revision_no),
        	CONSTRAINT fk_mkr_version_spec FOREIGN KEY(version_id, specification_version) REFERENCES managed_knowledge_versions (version_id, specification_version),
        	CONSTRAINT uq_mkr_original_key UNIQUE (original_key),
        	CONSTRAINT ck_mkr_revision_positive CHECK (revision_no > 0),
        	CONSTRAINT ck_mkr_byte_size CHECK (byte_size > 0 AND byte_size <= 10485760),
        	CONSTRAINT ck_mkr_file_format CHECK (file_format IN ('MD', 'TXT')),
        	CONSTRAINT ck_mkr_original_key CHECK (original_key = 'versions/' || version_id || '/revisions/' || revision_no::text || '/original.' || CASE WHEN file_format = 'MD' THEN 'md' ELSE 'txt' END),
        	CONSTRAINT ck_mkr_raw_hash CHECK (raw_hash ~ '^[0-9a-f]{64}$'),
        	CONSTRAINT ck_mkr_metadata_hash CHECK (metadata_hash ~ '^[0-9a-f]{64}$'),
        	CONSTRAINT ck_mkr_parse_pair CHECK ((body IS NULL AND normalized_hash IS NULL) OR (body IS NOT NULL AND length(btrim(body)) > 0 AND normalized_hash IS NOT NULL AND normalized_hash ~ '^[0-9a-f]{64}$')),
        	CONSTRAINT ck_mkr_dates CHECK (expiry_date IS NULL OR expiry_date >= effective_date),
        	CONSTRAINT ck_mkr_type CHECK (document_type IN ('DOM_PRODUCT_SPEC', 'QUALITY_SPEC', 'COORDINATE_SYSTEM_SPEC', 'REVIEW_OPERATION_SPEC', 'DELIVERY_SPEC')),
        	CONSTRAINT ck_mkr_scope CHECK (permission_scope = 'INTERNAL_REVIEWER'),
        	CONSTRAINT ck_mkr_demo CHECK (is_demo AND maintainer = '演示维护用户'),
        	CONSTRAINT ck_mkr_required_text CHECK (length(btrim(title)) > 0 AND length(btrim(original_filename)) > 0 AND length(btrim(change_summary)) > 0 AND length(btrim(created_by)) > 0)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE managed_knowledge_documents ADD CONSTRAINT fk_mkd_current_version FOREIGN KEY(document_id, current_version_id) REFERENCES managed_knowledge_versions (document_id, version_id)
        """
    )
    op.execute(
        """
        ALTER TABLE managed_knowledge_versions ADD CONSTRAINT fk_mkv_current_revision FOREIGN KEY(version_id, current_revision_no) REFERENCES managed_knowledge_revisions (version_id, revision_no) DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute("INSERT INTO managed_knowledge_libraries (library_id) VALUES ('DEFAULT')")


def downgrade() -> None:
    """只撤销本版四表，先移除循环外键，不触及旧索引或业务数据。"""

    op.drop_constraint("fk_mkd_current_version", "managed_knowledge_documents", type_="foreignkey")
    op.drop_constraint("fk_mkv_current_revision", "managed_knowledge_versions", type_="foreignkey")
    op.drop_table("managed_knowledge_revisions")
    op.drop_table("managed_knowledge_versions")
    op.drop_table("managed_knowledge_documents")
    op.drop_table("managed_knowledge_libraries")
