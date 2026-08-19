"""M4.5/M4.6中文关键词预处理和Query Embedding测试。"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import AnyHttpUrl, SecretStr

from app.knowledge import (
    EMBEDDING_DIMENSION,
    EmbeddingBatchGenerator,
    EmbeddingConfig,
    EmbeddingIndexDescriptor,
    KeywordQueryError,
    build_search_document,
    preprocess_keyword_query,
)


def _config() -> EmbeddingConfig:
    return EmbeddingConfig(
        provider="openai_compatible",
        model="text-embedding-3-small",
        base_url=AnyHttpUrl("https://embedding.example/v1"),
        api_key=SecretStr("embedding-secret"),
        dimension=EMBEDDING_DIMENSION,
        batch_size=2,
        max_retries=0,
        initial_backoff_seconds=0.01,
        max_backoff_seconds=0.1,
        timeout_seconds=2.0,
        index_version="demo-embedding-v1",
    )


class QueryProvider:
    """记录Query Embedding输入的固定Provider。"""

    def __init__(self, config: EmbeddingConfig) -> None:
        self.descriptor = EmbeddingIndexDescriptor.from_config(config)
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(tuple(texts))
        return ((1.0, *([0.0] * (EMBEDDING_DIMENSION - 1))),)


@pytest.mark.unit
def test_keyword_query_generates_chinese_bigrams_and_safe_latin_terms() -> None:
    query = preprocess_keyword_query("  坐标系问题 + GF-2 / DOM  ")

    assert query.terms == ("坐标", "标系", "系问", "问题", "gf-2", "dom")
    assert query.search_text == "坐标 标系 系问 问题 gf-2 dom"


@pytest.mark.unit
def test_search_document_contains_section_content_and_chinese_bigrams() -> None:
    search_document = build_search_document(
        content="坐标系问题处理完成后重新提交复核。",
        section_path=("质量规范", "坐标系统一"),
    )

    assert "质量规范 坐标系统一" in search_document
    assert "坐标系问题处理完成后重新提交复核。" in search_document
    assert all(term in search_document.split() for term in ("坐标", "标系", "系问", "问题"))
    assert "质量 量规 规范" in search_document


@pytest.mark.unit
@pytest.mark.parametrize("query", ["", "   ", "坐", "!!!", "x" * 257])
def test_keyword_query_rejects_empty_ambiguous_or_oversized_input(query: str) -> None:
    with pytest.raises(KeywordQueryError):
        preprocess_keyword_query(query)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_embedding_uses_same_provider_descriptor_and_validates_vector() -> None:
    config = _config()
    provider = QueryProvider(config)
    generator = EmbeddingBatchGenerator(config, provider)

    query_embedding = await generator.generate_query("  坐标系问题  ")

    assert provider.calls == [("坐标系问题",)]
    assert query_embedding.descriptor == provider.descriptor
    assert len(query_embedding.vector) == EMBEDDING_DIMENSION
    assert query_embedding.vector[0] == 1.0
