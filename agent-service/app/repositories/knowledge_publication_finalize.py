"""已确认操作的发布准备与原子切换，不调用外部服务或改变知识读源。"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.publication import publication_confirmation, publication_generation_hash
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeLibrary as Library
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.managed_knowledge import ManagedKnowledgeRepository, PublicationRead
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationReceipt,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeConfirmation,
    ManagedKnowledgeGenerationRecord,
)


@dataclass(frozen=True, slots=True)
class PublicationFinalizeRead:
    """事务外完整校验所需的只读快照，不含调用者凭据。"""

    operation_id: str
    confirmation: ManagedKnowledgeConfirmation
    record: PublicationRead
    index: KnowledgePublicationIndexIdentity
    generation_id: str
    generation: ManagedKnowledgeGenerationRecord
    chunks: tuple[ManagedKnowledgeChunkRecord, ...]


def finalization_hash(prepared: PublicationFinalizeRead) -> str:
    """绑定完整已存向量和证据清单，最终事务不复用校验前的旧分块。"""

    payload = {
        "confirmation": prepared.confirmation.model_dump(mode="json"),
        "generation": prepared.generation.model_dump(mode="json"),
        "chunks": [chunk.model_dump(mode="json") for chunk in prepared.chunks],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class KnowledgePublicationFinalizeRepository(ManagedKnowledgeRepository):
    """按库→资料→任务→操作→批次加锁，再验证和切换同一逻辑资料的版本。"""

    async def _operation(
        self, session: AsyncSession, operation_id: str, actor: str, scope: str, *, lock: bool
    ) -> tuple[Operation, Library, Document, Task | None]:
        """先限制实际确认人及修订范围，再读取或锁定发布关系。"""

        # 单独选择标量，防止锁等待后使用ORM identity map里的旧计数。
        document_id = await session.scalar(
            select(Version.document_id)
            .join(Operation, Operation.version_id == Version.version_id)
            .join(
                Revision,
                (Revision.version_id == Operation.version_id)
                & (Revision.revision_no == Operation.revision_no),
            )
            .where(
                Operation.operation_id == operation_id,
                Operation.actor_id == actor,
                Operation.action == "PUBLISH",
                Revision.permission_scope == scope,
            )
        )
        if document_id is None:
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
        library_query = select(Library).where(Library.library_id == "DEFAULT")
        document_query = select(Document).where(Document.document_id == document_id)
        task_query = select(Task).where(
            Task.operation_id == operation_id, Task.task_type == "INDEX"
        )
        operation_query = select(Operation).where(Operation.operation_id == operation_id)
        library = await session.scalar(library_query.with_for_update() if lock else library_query)
        document = await session.scalar(
            document_query.with_for_update() if lock else document_query
        )
        task = await session.scalar(task_query.with_for_update() if lock else task_query)
        operation = await session.scalar(
            operation_query.with_for_update() if lock else operation_query
        )
        if library is None or document is None or operation is None:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        return operation, library, document, task

    @staticmethod
    def _confirmation(operation: Operation, document: Document) -> ManagedKnowledgeConfirmation:
        """审计快照必须匹配实际操作，不能把任意JSON当成已确认目标。"""

        try:
            snapshot = ManagedKnowledgeConfirmation.model_validate(operation.confirmation_snapshot)
            if (
                snapshot.actor_id != operation.actor_id
                or snapshot.action != "PUBLISH"
                or snapshot.document_id != document.document_id
                or snapshot.version_id != operation.version_id
                or snapshot.revision_no != operation.revision_no
                or snapshot.generation_id is None
            ):
                raise ValueError("confirmation does not match operation")
            return snapshot
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None

    async def _receipt(
        self,
        session: AsyncSession,
        operation: Operation,
        library: Library,
        document: Document,
        *,
        replayed: bool,
    ) -> KnowledgePublicationReceipt:
        """返回已提交版本的原发布时间及当前状态，重放不能恢复被替代或停用的版本。"""

        snapshot = self._confirmation(operation, document)
        version = await session.get(Version, operation.version_id)
        if (
            operation.state != "SUCCEEDED"
            or operation.result_id != operation.version_id
            or version is None
            or version.published_revision_no != snapshot.revision_no
            or version.published_generation_id != snapshot.generation_id
        ):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        try:
            return KnowledgePublicationReceipt.model_validate(
                {
                    "operation_id": operation.operation_id,
                    "document_id": document.document_id,
                    "version_id": version.version_id,
                    "revision_no": snapshot.revision_no,
                    "generation_id": snapshot.generation_id,
                    "replaced_version_id": snapshot.previous_version_id,
                    "publication_state": version.publication_state,
                    "published_at": version.published_at,
                    "is_current_version": document.current_version_id == version.version_id,
                    "row_version": document.row_version,
                    "release_revision": library.release_revision,
                    "source_mode": library.source_mode,
                    "replayed": replayed,
                }
            )
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None

    async def _prepared(
        self,
        session: AsyncSession,
        operation: Operation,
        document: Document,
        task: Task | None,
        scope: str,
        *,
        lock: bool,
    ) -> PublicationFinalizeRead:
        """READY不是充分条件，同时核对操作、任务、确认、正文和索引身份。"""

        if operation.state not in {"CONFIRMED", "EXECUTING"}:
            raise KnowledgeManagementError("PUBLICATION_OPERATION_NOT_ACTIVE")
        snapshot = self._confirmation(operation, document)
        generation_query = select(Generation).where(
            Generation.generation_id == snapshot.generation_id
        )
        generation = await session.scalar(
            generation_query.with_for_update() if lock else generation_query
        )
        if generation is None:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        if generation.state != "READY" or (task is not None and task.state != "SUCCEEDED"):
            raise KnowledgeManagementError("PUBLICATION_INDEX_NOT_READY")
        if operation.state != ("EXECUTING" if task is not None else "CONFIRMED"):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        if task is not None and (
            task.generation_id != generation.generation_id
            or task.operation_action != "PUBLISH"
            or task.version_id != snapshot.version_id
            or task.revision_no != snapshot.revision_no
        ):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        record = await self._publication_candidate(
            session, document.document_id, operation.version_id, operation.revision_no, scope
        )
        try:
            target = KnowledgePublicationTarget(
                document_id=document.document_id,
                version_id=operation.version_id,
                expected_revision_no=operation.revision_no,
                expected_row_version=snapshot.expected_row_version + 1,
            )
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        fresh = publication_confirmation(record, target, operation.actor_id)
        if (
            fresh.model_copy(
                update={
                    "expected_row_version": snapshot.expected_row_version,
                    "generation_id": snapshot.generation_id,
                }
            )
            != snapshot
        ):
            raise KnowledgeManagementError("STALE_CONFIRMATION")
        try:
            index = KnowledgePublicationIndexIdentity.model_validate(
                {
                    "provider": generation.embedding_provider,
                    "model": generation.embedding_model,
                    "dimension": generation.embedding_dimension,
                    "index_version": generation.index_version,
                    "chunking_version": generation.chunking_version,
                }
            )
            generation_record = ManagedKnowledgeGenerationRecord.model_validate(
                {
                    key: getattr(generation, key)
                    for key in ManagedKnowledgeGenerationRecord.model_fields
                }
            )
            if (
                generation.version_id != snapshot.version_id
                or generation.revision_no != snapshot.revision_no
                or generation.input_hash
                != publication_generation_hash(
                    snapshot, record.revision.citation_document_id, index
                )
            ):
                raise ValueError("generation input does not match confirmation")
            query = (
                select(Chunk)
                .where(Chunk.generation_id == generation.generation_id)
                .order_by(Chunk.chunk_index)
            )
            rows = (
                await session.scalars(query.with_for_update(read=True) if lock else query)
            ).all()
            chunks = tuple(
                ManagedKnowledgeChunkRecord.model_validate(
                    {
                        **{
                            key: getattr(chunk, key)
                            for key in ManagedKnowledgeChunkRecord.model_fields
                        },
                        "section_path": tuple(chunk.section_path),
                        "embedding": tuple(float(value) for value in chunk.embedding),
                    }
                )
                for chunk in rows
            )
            if generation.chunk_count != len(chunks):
                raise ValueError("ready generation count does not match stored chunks")
        except (TypeError, ValueError):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        return PublicationFinalizeRead(
            operation.operation_id,
            snapshot,
            record,
            index,
            generation.generation_id,
            generation_record,
            chunks,
        )

    async def prepare_finalization(
        self,
        operation_id: str,
        *,
        actor: str,
        scope: str,
    ) -> PublicationFinalizeRead | KnowledgePublicationReceipt:
        """只读一致快照返回证据，耗时正文/分块校验在连接释放后完成。"""

        async with self.database.session() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            operation, library, document, task = await self._operation(
                session, operation_id, actor, scope, lock=False
            )
            if operation.state == "SUCCEEDED":
                return await self._receipt(session, operation, library, document, replayed=True)
            return await self._prepared(session, operation, document, task, scope, lock=False)

    async def commit_finalization(
        self,
        prepared: PublicationFinalizeRead,
        fingerprint: str,
        *,
        actor: str,
        scope: str,
    ) -> KnowledgePublicationReceipt:
        """最终授权后重新加锁和核对清单，旧版替代、新版封存、指针及计数同事务提交。"""

        async with self.database.session() as session, session.begin():
            operation, library, document, task = await self._operation(
                session, prepared.operation_id, actor, scope, lock=True
            )
            if operation.state == "SUCCEEDED":
                return await self._receipt(session, operation, library, document, replayed=True)
            current = await self._prepared(session, operation, document, task, scope, lock=True)
            if finalization_hash(current) != fingerprint:
                raise KnowledgeManagementError("STALE_CONFIRMATION")
            if max(document.row_version, library.release_revision) == 2**63 - 1:
                raise KnowledgeManagementError("KNOWLEDGE_COUNTER_EXHAUSTED")
            published = (
                await session.scalars(
                    select(Version)
                    .where(
                        Version.document_id == document.document_id,
                        Version.publication_state == "PUBLISHED",
                    )
                    .with_for_update()
                )
            ).all()
            previous_id = current.confirmation.previous_version_id
            if {version.version_id for version in published} != (
                {previous_id} if previous_id else set()
            ):
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            for previous in published:
                previous.publication_state = "SUPERSEDED"
            # 唯一约束即时检查，先封存旧版状态再把新版置为PUBLISHED。
            await session.flush()
            version = await session.get(Version, operation.version_id)
            assert version is not None
            now = await session.scalar(select(func.statement_timestamp()))
            version.publication_state, version.published_at = "PUBLISHED", now
            version.published_revision_no, version.published_generation_id = (
                operation.revision_no,
                current.generation_id,
            )
            document.current_version_id, document.row_version = (
                operation.version_id,
                document.row_version + 1,
            )
            library.release_revision += 1
            operation.state, operation.result_id, operation.finished_at = (
                "SUCCEEDED",
                operation.version_id,
                now,
            )
            await session.flush()
            return await self._receipt(session, operation, library, document, replayed=False)

    async def reject_finalization(
        self, operation_id: str, *, actor: str, scope: str, stale: bool
    ) -> None:
        """校验失败只结束原确认人的未完成操作，不修改历史成功或已发布指针。"""

        async with self.database.session() as session, session.begin():
            operation, _, _, _ = await self._operation(
                session, operation_id, actor, scope, lock=True
            )
            if operation.state in {"CONFIRMED", "EXECUTING"}:
                operation.state = "STALE" if stale else "FAILED"
                operation.error_code = "STALE_INPUT" if stale else "INDEX_VALIDATION_FAILED"
                operation.finished_at = await session.scalar(select(func.now()))
