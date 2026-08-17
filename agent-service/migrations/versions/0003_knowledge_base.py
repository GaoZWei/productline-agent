"""创建知识文档、分块、pgvector和全文检索字段。

Revision ID: 0003_knowledge_base
Revises: 0002_session_context
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0003_knowledge_base"
down_revision: str | None = "0002_session_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建Agent自有知识元数据，不导入或解析规范正文。"""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "lifecycle",
            sa.Enum(
                "ACTIVE",
                "HISTORICAL",
                name="ck_knowledge_documents_lifecycle",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("replaced_by", sa.String(length=128), nullable=True),
        sa.Column(
            "document_type",
            sa.Enum(
                "DOM_PRODUCT_SPEC",
                "QUALITY_SPEC",
                "COORDINATE_SYSTEM_SPEC",
                "REVIEW_OPERATION_SPEC",
                "DELIVERY_SPEC",
                name="ck_knowledge_documents_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("satellite_type", sa.String(length=128), nullable=True),
        sa.Column("product_type", sa.String(length=128), nullable=True),
        sa.Column("processing_level", sa.String(length=128), nullable=True),
        sa.Column("specification_version", sa.String(length=64), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "permission_scope",
            sa.Enum(
                "INTERNAL_REVIEWER",
                name="ck_knowledge_documents_permission",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(document_id) > 0",
            name="ck_knowledge_documents_id_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(title) > 0",
            name="ck_knowledge_documents_title_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(file_path) > 0",
            name="ck_knowledge_documents_path_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_knowledge_documents_hash_length",
        ),
        sa.CheckConstraint(
            "expiry_date IS NULL OR expiry_date >= effective_date",
            name="ck_knowledge_documents_date_order",
        ),
        sa.CheckConstraint(
            "(lifecycle = 'ACTIVE' AND expiry_date IS NULL AND replaced_by IS NULL) "
            "OR (lifecycle = 'HISTORICAL' AND expiry_date IS NOT NULL "
            "AND replaced_by IS NOT NULL)",
            name="ck_knowledge_documents_lifecycle_fields",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by"],
            ["knowledge_documents.document_id"],
        ),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint("content_hash", name="uq_knowledge_documents_content_hash"),
        sa.UniqueConstraint("file_path", name="uq_knowledge_documents_file_path"),
    )
    op.create_index(
        "ix_knowledge_documents_filter",
        "knowledge_documents",
        [
            "lifecycle",
            "document_type",
            "product_type",
            "satellite_type",
            "processing_level",
        ],
        unique=False,
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(chunk_id) > 0",
            name="ck_knowledge_chunks_id_not_blank",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_knowledge_chunks_index_nonnegative",
        ),
        sa.CheckConstraint(
            "char_length(content) > 0",
            name="ck_knowledge_chunks_content_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_knowledge_chunks_hash_length",
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name="ck_knowledge_chunks_token_count_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.document_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_index",
        ),
    )


def downgrade() -> None:
    """移除知识表，但保留可能被同库其他能力复用的vector扩展。"""

    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_filter", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")

