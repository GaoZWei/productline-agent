"""仅检索管理库当前发布指针，双路共享只读快照，不触碰旧知识表。"""

import math
import struct
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import Float, Select, desc, func, literal_column, or_, select, text
from sqlalchemy.sql.elements import ColumnElement

from app.database import Database
from app.knowledge.embeddings import EmbeddingIndexDescriptor, QueryEmbedding
from app.knowledge.managed_parsing import ParsedKnowledgeRevision, parse_managed_revision
from app.knowledge.publication import publication_generation_hash
from app.knowledge.search import (
    KeywordSearchHit,
    VectorSearchHit,
    build_search_document,
    preprocess_keyword_query,
)
from app.models.managed_knowledge import (
    ManagedKnowledgeDocument as Document,
)
from app.models.managed_knowledge import (
    ManagedKnowledgeLibrary as Library,
)
from app.models.managed_knowledge import (
    ManagedKnowledgeRevision as Revision,
)
from app.models.managed_knowledge import (
    ManagedKnowledgeVersion as Version,
)
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeChunk as Chunk,
)
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeIndexGeneration as Generation,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge import (
    ManagedKnowledgeRevisionSnapshot,
    ManagedKnowledgeVersionState,
)
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeConfirmation,
    ManagedKnowledgeGenerationRecord,
)
from app.schemas.managed_knowledge_search import (
    ManagedKnowledgeEvidence,
    ManagedKnowledgeReadContext,
    ManagedKnowledgeSearchFilter,
    ManagedKnowledgeSearchOptions,
)


@dataclass(frozen=True, slots=True)
class ManagedKnowledgeSearchSnapshot:
    """两个通道的不可变结果，引用定位与库计数来自同一SQL快照。"""

    context: ManagedKnowledgeReadContext
    keyword_hits: tuple[KeywordSearchHit, ...]
    vector_hits: tuple[VectorSearchHit, ...]
    evidence: tuple[ManagedKnowledgeEvidence, ...]


class _HitPayload(TypedDict):
    """两路复用明确字段，管理UUID不能误填为原规范引用ID。"""

    chunk_id: str
    document_id: str
    document_name: str
    document_version: str
    chunk_index: int
    section_path: tuple[str, ...]
    content: str
    content_hash: str


def validate_managed_query(
    query_embedding: QueryEmbedding, index: KnowledgePublicationIndexIdentity
) -> None:
    """生成器输出须匹配配置空间，拒绝非float32有限非零向量，且不借用SQL连接。"""

    if query_embedding.descriptor != EmbeddingIndexDescriptor(
        provider=index.provider,
        model=index.model,
        dimension=index.dimension,
        index_version=index.index_version,
    ):
        raise KnowledgeManagementError("MANAGED_QUERY_INDEX_MISMATCH")
    if (
        len(query_embedding.vector) != 1536
        or not any(query_embedding.vector)
        or any(
            not math.isfinite(value) or abs(value) > 3.4028234663852886e38
            for value in query_embedding.vector
        )
    ):
        raise KnowledgeManagementError("INVALID_QUERY_EMBEDDING")
    if not any(struct.unpack("f", struct.pack("f", value))[0] for value in query_embedding.vector):
        raise KnowledgeManagementError("INVALID_QUERY_EMBEDDING")


class ManagedKnowledgeSearchRepository:
    """先过滤发布/范围/索引身份，再分别排序TopK，不合并或回退旧库。"""

    def __init__(
        self, database: Database, *, index_identity: KnowledgePublicationIndexIdentity
    ) -> None:
        self.database = database
        self.index = index_identity

    def _base(
        self, filters: ManagedKnowledgeSearchFilter
    ) -> Select[tuple[Chunk, Version, Revision, Generation]]:
        """组合外键归属及当前指针一起参与查询，不能只凭READY标签取块。"""

        clauses: list[ColumnElement[bool]] = [
            Document.library_id == "DEFAULT",
            Version.publication_state == "PUBLISHED",
            Version.current_revision_no == Version.published_revision_no,
            or_(Version.source_kind == "UPLOAD", Version.source_lifecycle == "ACTIVE"),
            Revision.body.is_not(None),
            Revision.normalized_hash.is_not(None),
            Revision.permission_scope == filters.permission_scope,
            Revision.effective_date <= filters.effective_at,
            or_(Revision.expiry_date.is_(None), Revision.expiry_date >= filters.effective_at),
            Generation.state == "READY",
            Generation.chunk_count > 0,
            Generation.embedding_provider == self.index.provider,
            Generation.embedding_model == self.index.model,
            Generation.embedding_dimension == self.index.dimension,
            Generation.index_version == self.index.index_version,
            Generation.chunking_version == self.index.chunking_version,
        ]
        for column, value in (
            (Revision.product_type, filters.product_type),
            (Revision.satellite_type, filters.satellite_type),
            (Revision.processing_level, filters.processing_level),
            (Revision.document_type, filters.document_type),
            (Version.specification_version, filters.specification_version),
        ):
            if value is not None:
                clauses.append(column == value)
        return (
            select(Chunk, Version, Revision, Generation)
            .select_from(Document)
            .join(
                Version,
                (Document.current_version_id == Version.version_id)
                & (Version.document_id == Document.document_id),
            )
            .join(
                Revision,
                (Revision.version_id == Version.version_id)
                & (Revision.revision_no == Version.published_revision_no),
            )
            .join(
                Generation,
                (Generation.generation_id == Version.published_generation_id)
                & (Generation.version_id == Version.version_id)
                & (Generation.revision_no == Revision.revision_no),
            )
            .join(Chunk, Chunk.generation_id == Generation.generation_id)
            .where(*clauses)
        )

    def keyword_statement(
        self,
        query: str,
        filters: ManagedKnowledgeSearchFilter,
        options: ManagedKnowledgeSearchOptions,
    ) -> Select[tuple[Chunk, Version, Revision, Generation, float]]:
        """使用既有中文双字规则和AND词元语义，不把输入拼成SQL或改变召回策略。"""

        ts_query = func.plainto_tsquery(
            literal_column("'simple'::regconfig"), preprocess_keyword_query(query).search_text
        )
        score = func.ts_rank_cd(Chunk.search_vector, ts_query, 32).label("keyword_score")
        return (
            self._base(filters)
            .add_columns(score)
            .where(Chunk.search_vector.op("@@")(ts_query))
            .order_by(desc(score), Chunk.chunk_id)
            .limit(options.channel_top_k)
        )

    def vector_statement(
        self,
        query_embedding: QueryEmbedding,
        filters: ManagedKnowledgeSearchFilter,
        options: ManagedKnowledgeSearchOptions,
    ) -> Select[tuple[Chunk, Version, Revision, Generation, float]]:
        """相同完整索引身份内余弦检索，与关键词共享全部发布和元数据门禁。"""

        distance = Chunk.embedding.op("<=>", return_type=Float)(list(query_embedding.vector))
        return (
            self._base(filters)
            .add_columns((1.0 - distance).label("vector_score"))
            .where(distance <= 1.0 - options.min_vector_similarity)
            .order_by(distance, Chunk.chunk_id)
            .limit(options.channel_top_k)
        )

    async def search(
        self,
        query: str,
        query_embedding: QueryEmbedding,
        *,
        filters: ManagedKnowledgeSearchFilter,
        options: ManagedKnowledgeSearchOptions,
    ) -> ManagedKnowledgeSearchSnapshot:
        """向量已生成后才开启事务，完整读出两路候选及引用后立即释放连接。"""

        validate_managed_query(query_embedding, self.index)
        keyword = self.keyword_statement(query, filters, options)
        vector = self.vector_statement(query_embedding, filters, options)
        async with self.database.session() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            library = await session.get(Library, "DEFAULT")
            if library is None:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            try:
                context = ManagedKnowledgeReadContext.model_validate(
                    {
                        "configured_source_mode": library.source_mode,
                        "release_revision": library.release_revision,
                        "index": self.index,
                    }
                )
                keyword_rows = (await session.execute(keyword)).all()
                vector_rows = (await session.execute(vector)).all()
                cache: dict[tuple[str, int, str], ParsedKnowledgeRevision] = {}
                evidence: dict[str, ManagedKnowledgeEvidence] = {}
                keywords: list[KeywordSearchHit] = []
                vectors: list[VectorSearchHit] = []
                for rows, keyword_channel in ((keyword_rows, True), (vector_rows, False)):
                    for chunk, version, revision, generation, score in rows:
                        binding = self._validate_candidate(
                            chunk, version, revision, generation, cache
                        )
                        previous = evidence.setdefault(chunk.chunk_id, binding)
                        if previous != binding or not math.isfinite(float(score)):
                            raise ValueError("inconsistent candidate identity or score")
                        payload = _HitPayload(
                            chunk_id=chunk.chunk_id,
                            document_id=version.citation_document_id,
                            document_name=revision.title,
                            document_version=version.specification_version,
                            chunk_index=chunk.chunk_index,
                            section_path=tuple(chunk.section_path),
                            content=chunk.content,
                            content_hash=chunk.content_hash,
                        )
                        if keyword_channel:
                            keywords.append(KeywordSearchHit(**payload, keyword_score=float(score)))
                        else:
                            vectors.append(VectorSearchHit(**payload, vector_score=float(score)))
            except ValueError:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
            return ManagedKnowledgeSearchSnapshot(
                context, tuple(keywords), tuple(vectors), tuple(evidence.values())
            )

    def _validate_candidate(
        self,
        chunk: Chunk,
        version: Version,
        revision: Revision,
        generation: Generation,
        cache: dict[tuple[str, int, str], ParsedKnowledgeRevision],
    ) -> ManagedKnowledgeEvidence:
        """校验命中原文、封存元数据和稳定章节定位，不以相同块数代替证据完整性。"""

        key = (version.version_id, revision.revision_no, generation.generation_id)
        if key not in cache:
            ManagedKnowledgeVersionState.model_validate(
                {name: getattr(version, name) for name in ManagedKnowledgeVersionState.model_fields}
            )
            snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
                {
                    name: getattr(revision, name)
                    for name in ManagedKnowledgeRevisionSnapshot.model_fields
                }
            )
            if snapshot.metadata_digest() != revision.metadata_hash or snapshot.body is None:
                raise ValueError("sealed metadata or body mismatch")
            ManagedKnowledgeGenerationRecord.model_validate(
                {
                    name: getattr(generation, name)
                    for name in ManagedKnowledgeGenerationRecord.model_fields
                }
            )
            confirmation = ManagedKnowledgeConfirmation(
                actor_id=version.created_by,
                action="PUBLISH",
                document_id=version.document_id,
                version_id=version.version_id,
                revision_no=revision.revision_no,
                raw_hash=snapshot.raw_hash,
                normalized_hash=snapshot.normalized_hash,
                metadata_hash=revision.metadata_hash,
                expected_row_version=0,
            )
            if generation.input_hash != publication_generation_hash(
                confirmation, version.citation_document_id, self.index
            ):
                raise ValueError("sealed generation identity mismatch")
            parsed = parse_managed_revision(
                snapshot.body.encode(),
                citation_document_id=version.citation_document_id,
                title=snapshot.title,
                file_format=snapshot.file_format,
            )
            if generation.chunk_count != len(parsed.chunks):
                raise ValueError("generation count does not match parsed body")
            cache[key] = parsed
        record = ManagedKnowledgeChunkRecord.model_validate(
            {
                **{name: getattr(chunk, name) for name in ManagedKnowledgeChunkRecord.model_fields},
                "embedding": tuple(float(value) for value in chunk.embedding),
                "section_path": tuple(chunk.section_path),
            }
        )
        expected = next(
            (item for item in cache[key].chunks if item.chunk_id == record.chunk_id), None
        )
        if expected is None or (
            record.chunk_index,
            record.section_path,
            record.content,
            record.content_hash,
            record.token_count,
            record.search_document,
        ) != (
            expected.chunk_index,
            expected.section_path,
            expected.content,
            expected.content_hash,
            expected.token_count,
            build_search_document(content=expected.content, section_path=expected.section_path),
        ):
            raise ValueError("chunk does not match sealed body")
        return ManagedKnowledgeEvidence(
            citation_document_id=version.citation_document_id,
            chunk_id=chunk.chunk_id,
            document_id=version.document_id,
            version_id=version.version_id,
            revision_no=revision.revision_no,
            generation_id=generation.generation_id,
        )
