"""候选索引的正文分块、向量绑定与完整性校验，不访问数据库或外部模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.knowledge.embeddings import EmbeddingGeneration, EmbeddingIndexDescriptor
from app.knowledge.managed_parsing import ParsedKnowledgeRevision, parse_managed_revision
from app.knowledge.search import build_search_document
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge_processing import ManagedKnowledgeChunkRecord

if TYPE_CHECKING:
    from app.repositories.managed_knowledge import PublicationRead


class IndexEvidenceInput(Protocol):
    """构建与最终发布共用同一原文校验，不依赖任务是否仍处于执行中。"""

    @property
    def generation_id(self) -> str: ...

    @property
    def record(self) -> PublicationRead: ...

    @property
    def index(self) -> KnowledgePublicationIndexIdentity: ...


def parse_index_input(claim: IndexEvidenceInput) -> ParsedKnowledgeRevision:
    """只使用已领取修订的规范化正文，不读原件或仓库固定语料。"""

    snapshot = claim.record.revision.snapshot
    if snapshot.body is None:
        raise ValueError("index input requires parsed body")
    parsed = parse_managed_revision(
        snapshot.body.encode(),
        citation_document_id=claim.record.revision.citation_document_id,
        title=snapshot.title,
        file_format=snapshot.file_format,
    )
    if parsed.normalized_hash != snapshot.normalized_hash:
        raise ValueError("index input hash changed during chunking")
    return parsed


def index_chunk_records(
    claim: IndexEvidenceInput, parsed: ParsedKnowledgeRevision, generated: EmbeddingGeneration
) -> tuple[ManagedKnowledgeChunkRecord, ...]:
    """按明确Chunk身份绑定向量，拒绝缺失、重复、外来身份及错误模型空间。"""

    index = claim.index
    if generated.descriptor != EmbeddingIndexDescriptor(
        provider=index.provider,
        model=index.model,
        dimension=index.dimension,
        index_version=index.index_version,
    ):
        raise ValueError("embedding index identity does not match reservation")
    if generated.generated_at.tzinfo is None or generated.generated_at.utcoffset() is None:
        raise ValueError("embedding result requires an aware generation time")
    vectors = {item.chunk_id: item.vector for item in generated.embeddings}
    if len(vectors) != len(generated.embeddings) or set(vectors) != {
        chunk.chunk_id for chunk in parsed.chunks
    }:
        raise ValueError("embedding chunk identities do not match inputs")
    return tuple(
        ManagedKnowledgeChunkRecord(
            generation_id=claim.generation_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            section_path=chunk.section_path,
            content=chunk.content,
            content_hash=chunk.content_hash,
            token_count=chunk.token_count,
            search_document=build_search_document(
                content=chunk.content, section_path=chunk.section_path
            ),
            embedding=vectors[chunk.chunk_id],
        )
        for chunk in parsed.chunks
    )


def validate_index_records(
    claim: IndexEvidenceInput, records: tuple[ManagedKnowledgeChunkRecord, ...]
) -> None:
    """保存前在事务外重新校验完整清单，不能以任意有效分块替代原修订证据。"""

    expected = parse_index_input(claim).chunks
    if not records or len(records) != len(expected):
        raise ValueError("index records must cover all chunks")
    for source, record in zip(expected, records, strict=True):
        checked = ManagedKnowledgeChunkRecord.model_validate(record.model_dump())
        if (
            checked.generation_id != claim.generation_id
            or checked.chunk_id != source.chunk_id
            or checked.chunk_index != source.chunk_index
            or checked.section_path != source.section_path
            or checked.content != source.content
            or checked.content_hash != source.content_hash
            or checked.token_count != source.token_count
            or checked.search_document
            != build_search_document(content=source.content, section_path=source.section_path)
        ):
            raise ValueError("index records do not match immutable revision")
