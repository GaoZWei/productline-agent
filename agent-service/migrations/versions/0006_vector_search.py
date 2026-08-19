"""增加余弦距离HNSW向量索引。

Revision ID: 0006_vector_search
Revises: 0005_keyword_search
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_vector_search"
down_revision: str | None = "0005_keyword_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为1536维Embedding建立余弦距离HNSW索引。"""

    op.create_index(
        "ix_knowledge_chunks_embedding_cosine",
        "knowledge_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """移除余弦距离HNSW索引。"""

    op.drop_index(
        "ix_knowledge_chunks_embedding_cosine",
        table_name="knowledge_chunks",
        postgresql_using="hnsw",
    )
