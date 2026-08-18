"""固定Embedding维度并记录文档当前索引版本。

Revision ID: 0004_embedding_index
Revises: 0003_knowledge_base
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "0004_embedding_index"
down_revision: str | None = "0003_knowledge_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """将未定维向量收紧为1536维并增加当前索引身份。"""

    op.add_column(
        "knowledge_documents",
        sa.Column("embedding_provider", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("index_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_knowledge_documents_embedding_index_fields",
        "knowledge_documents",
        "(index_version IS NULL AND embedding_provider IS NULL "
        "AND embedding_model IS NULL AND embedding_dimension IS NULL "
        "AND indexed_at IS NULL) OR "
        "(index_version IS NOT NULL AND embedding_provider IS NOT NULL "
        "AND embedding_model IS NOT NULL AND embedding_dimension = 1536 "
        "AND indexed_at IS NOT NULL)",
    )
    op.alter_column(
        "knowledge_chunks",
        "embedding",
        existing_type=VECTOR(),
        type_=VECTOR(1536),
        existing_nullable=True,
        postgresql_using="embedding::vector(1536)",
    )


def downgrade() -> None:
    """恢复未定维向量并移除当前索引身份字段。"""

    op.alter_column(
        "knowledge_chunks",
        "embedding",
        existing_type=VECTOR(1536),
        type_=VECTOR(),
        existing_nullable=True,
        postgresql_using="embedding::vector",
    )
    op.drop_constraint(
        "ck_knowledge_documents_embedding_index_fields",
        "knowledge_documents",
        type_="check",
    )
    op.drop_column("knowledge_documents", "indexed_at")
    op.drop_column("knowledge_documents", "index_version")
    op.drop_column("knowledge_documents", "embedding_dimension")
    op.drop_column("knowledge_documents", "embedding_model")
    op.drop_column("knowledge_documents", "embedding_provider")
