"""增加中文关键词检索文档和GIN全文索引。

Revision ID: 0005_keyword_search
Revises: 0004_embedding_index
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_keyword_search"
down_revision: str | None = "0004_embedding_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """回填原文和双字检索词元，并让tsvector使用可检索文本。"""

    op.add_column(
        "knowledge_chunks",
        sa.Column("search_document", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE knowledge_chunks AS chunk
        SET search_document = concat_ws(
            E'\n',
            chunk.section_path::text,
            chunk.content,
            (
                SELECT string_agg(
                    substr(source.text_value, character_position, 2),
                    ' '
                    ORDER BY character_position
                )
                FROM (
                    SELECT chunk.section_path::text || ' ' || chunk.content AS text_value
                ) AS source
                CROSS JOIN LATERAL generate_series(
                    1,
                    greatest(char_length(source.text_value) - 1, 0)
                ) AS character_position
            )
        )
        """
    )
    op.alter_column(
        "knowledge_chunks",
        "search_document",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("knowledge_chunks", "search_vector")
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', search_document)", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_search_vector",
        "knowledge_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """恢复直接基于正文的无索引tsvector。"""

    op.drop_index(
        "ix_knowledge_chunks_search_vector",
        table_name="knowledge_chunks",
        postgresql_using="gin",
    )
    op.drop_column("knowledge_chunks", "search_vector")
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=False,
        ),
    )
    op.drop_column("knowledge_chunks", "search_document")
