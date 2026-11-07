"""管理检索命中与全量就绪共享封存证据校验，不访问SQL、原件或模型。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.knowledge.managed_parsing import ParsedKnowledgeRevision, parse_managed_revision
from app.knowledge.publication import publication_generation_hash
from app.knowledge.search import build_search_document
from app.schemas.managed_knowledge import (
    ManagedKnowledgeRevisionSnapshot,
    ManagedKnowledgeVersionState,
)
from app.schemas.managed_knowledge_index import ManagedKnowledgeIndexIdentity
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeConfirmation,
    ManagedKnowledgeGenerationRecord,
)


@dataclass(frozen=True, slots=True)
class PreparedManagedIndex:
    """已检查的封存身份，未知分块规则只能报告不匹配，不能据此READY。"""

    version: ManagedKnowledgeVersionState
    revision: ManagedKnowledgeRevisionSnapshot
    generation: ManagedKnowledgeGenerationRecord
    index: ManagedKnowledgeIndexIdentity
    parsed: ParsedKnowledgeRevision | None


def prepare_managed_index(
    version_values: Mapping[str, object],
    revision_values: Mapping[str, object],
    generation_values: Mapping[str, object],
    metadata_hash: str,
) -> PreparedManagedIndex:
    """校验关系、正文和批次输入哈希，使用已存完整索引身份核对来源而非当前配置。"""

    version = ManagedKnowledgeVersionState.model_validate(dict(version_values))
    revision = ManagedKnowledgeRevisionSnapshot.model_validate(dict(revision_values))
    generation = ManagedKnowledgeGenerationRecord.model_validate(dict(generation_values))
    if (
        version.publication_state != "PUBLISHED"
        or version.published_revision_no != revision.revision_no
        or revision.version_id != version.version_id
        or generation.version_id != version.version_id
        or generation.revision_no != revision.revision_no
        or generation.generation_id != version.published_generation_id
        or revision.specification_version != version.specification_version
        or version.source_lifecycle == "HISTORICAL"
        or generation.state != "READY"
        or revision.body is None
        or revision.metadata_digest() != metadata_hash
    ):
        raise ValueError("published evidence relationships or sealed body mismatch")
    index = ManagedKnowledgeIndexIdentity(
        provider=generation.embedding_provider,
        model=generation.embedding_model,
        dimension=generation.embedding_dimension,
        index_version=generation.index_version,
        chunking_version=generation.chunking_version,
    )
    confirmation = ManagedKnowledgeConfirmation(
        actor_id=version.created_by,
        action="PUBLISH",
        document_id=version.document_id,
        version_id=version.version_id,
        revision_no=revision.revision_no,
        raw_hash=revision.raw_hash,
        normalized_hash=revision.normalized_hash,
        metadata_hash=metadata_hash,
        expected_row_version=0,
    )
    if generation.input_hash != publication_generation_hash(
        confirmation, version.citation_document_id, index
    ):
        raise ValueError("sealed generation identity mismatch")
    parsed = None
    if index.chunking_version == "heading-v1":
        parsed = parse_managed_revision(
            revision.body.encode(),
            citation_document_id=version.citation_document_id,
            title=revision.title,
            file_format=revision.file_format,
        )
        if generation.chunk_count != len(parsed.chunks):
            raise ValueError("generation count does not match sealed body")
    return PreparedManagedIndex(version, revision, generation, index, parsed)


def validate_managed_chunk(
    values: Mapping[str, object], prepared: PreparedManagedIndex
) -> ManagedKnowledgeChunkRecord:
    """检查返回块的正文、向量和章节定位，未知分块规则也不得放过坏正文或零向量。"""

    record = ManagedKnowledgeChunkRecord.model_validate(dict(values))
    if record.generation_id != prepared.generation.generation_id:
        raise ValueError("chunk belongs to another generation")
    if record.search_document != build_search_document(
        content=record.content, section_path=record.section_path
    ):
        raise ValueError("search document mismatch")
    if prepared.parsed is not None:
        expected = next(
            (item for item in prepared.parsed.chunks if item.chunk_id == record.chunk_id), None
        )
        if expected is None or (
            record.chunk_index,
            record.section_path,
            record.content,
            record.content_hash,
            record.token_count,
        ) != (
            expected.chunk_index,
            expected.section_path,
            expected.content,
            expected.content_hash,
            expected.token_count,
        ):
            raise ValueError("chunk does not match sealed body")
    return record


def validate_managed_index_chunks(
    values: Sequence[Mapping[str, object]], prepared: PreparedManagedIndex
) -> None:
    """比对完整集合，防止缺块、重复或额外块被一次TopK没有命中而遗漏。"""

    if len(values) != prepared.generation.chunk_count:
        raise ValueError("stored chunks do not cover declared generation")
    records = tuple(validate_managed_chunk(value, prepared) for value in values)
    if len({item.chunk_id for item in records}) != len(records) or {
        item.chunk_index for item in records
    } != set(range(len(records))):
        raise ValueError("chunk identities or sequence are incomplete")
