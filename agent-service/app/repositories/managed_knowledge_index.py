"""只读捕获授权范围内的发布声明及全部索引，重校验在连接释放后执行。"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import or_, select, text

from app.database import Database
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
from app.schemas.managed_knowledge import (
    ManagedKnowledgeRevisionSnapshot,
    ManagedKnowledgeVersionState,
)
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeGenerationRecord,
)


@dataclass(frozen=True, slots=True)
class PublishedIndexClaim:
    """当前指针或PUBLISHED状态的声明，包含错误指针以防静默漏掉坏资料。"""

    document_id: str
    current_version_id: str | None
    version: Mapping[str, object]
    revision: Mapping[str, object] | None
    metadata_hash: str | None
    generation: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class ManagedPublishedIndexSnapshot:
    """同一SQL快照的不可变原始值，不携带活会话或延迟加载ORM对象。"""

    configured_source_mode: str
    release_revision: int
    claims: tuple[PublishedIndexClaim, ...]
    chunks: tuple[Mapping[str, object], ...]


class ManagedKnowledgeIndexRepository:
    """既不按固定catalog数判断，也不先用READY内连接把坏发布从统计中排除。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def read_published_snapshot(self, scope: str) -> ManagedPublishedIndexSnapshot:
        """发布声明、指针、计数及完整分块同一只读快照，不加载历史/草稿候选批次。"""

        async with self.database.session() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            library = await session.get(Library, "DEFAULT")
            if library is None:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            rows = (
                await session.execute(
                    select(Document, Version, Revision, Generation)
                    .join(Version, Version.document_id == Document.document_id)
                    .outerjoin(
                        Revision,
                        (Revision.version_id == Version.version_id)
                        & (Revision.revision_no == Version.current_revision_no),
                    )
                    .outerjoin(
                        Generation,
                        (Generation.generation_id == Version.published_generation_id)
                        & (Generation.version_id == Version.version_id)
                        & (Generation.revision_no == Version.published_revision_no),
                    )
                    .where(
                        Document.library_id == "DEFAULT",
                        or_(
                            Version.publication_state == "PUBLISHED",
                            Version.version_id == Document.current_version_id,
                        ),
                        or_(Revision.permission_scope == scope, Revision.version_id.is_(None)),
                    )
                    .order_by(Document.document_id, Version.version_id)
                )
            ).all()
            claims: list[PublishedIndexClaim] = []
            generation_ids: set[str] = set()
            for document, version, revision, generation in rows:
                if revision is None:
                    # 无修订即无法裁决范围，不能把未知范围资料漏算后声称READY。
                    raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
                if generation is not None:
                    generation_ids.add(generation.generation_id)
                claims.append(
                    PublishedIndexClaim(
                        document.document_id,
                        document.current_version_id,
                        MappingProxyType(
                            {
                                name: getattr(version, name)
                                for name in ManagedKnowledgeVersionState.model_fields
                            }
                        ),
                        MappingProxyType(
                            {
                                name: getattr(revision, name)
                                for name in ManagedKnowledgeRevisionSnapshot.model_fields
                            }
                        ),
                        revision.metadata_hash,
                        None
                        if generation is None
                        else MappingProxyType(
                            {
                                name: getattr(generation, name)
                                for name in ManagedKnowledgeGenerationRecord.model_fields
                            }
                        ),
                    )
                )
            chunks: list[Mapping[str, object]] = []
            if generation_ids:
                for chunk in await session.scalars(
                    select(Chunk)
                    .where(Chunk.generation_id.in_(generation_ids))
                    .order_by(Chunk.generation_id, Chunk.chunk_index)
                ):
                    chunks.append(
                        MappingProxyType(
                            {
                                **{
                                    name: getattr(chunk, name)
                                    for name in ManagedKnowledgeChunkRecord.model_fields
                                },
                                "section_path": tuple(chunk.section_path),
                                "embedding": tuple(float(value) for value in chunk.embedding),
                            }
                        )
                    )
            return ManagedPublishedIndexSnapshot(
                library.source_mode, library.release_revision, tuple(claims), tuple(chunks)
            )
