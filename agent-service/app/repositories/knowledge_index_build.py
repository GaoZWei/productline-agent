"""候选索引领取与完整保存的短事务，不调用模型或切换发布指针。"""

import asyncio
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import ValidationError
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.index_build import validate_index_records
from app.knowledge.publication import publication_confirmation, publication_generation_hash
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.managed_knowledge import ManagedKnowledgeRepository, PublicationRead
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeConfirmation,
    ProcessingError,
)


@dataclass(frozen=True, slots=True)
class IndexBuildClaim:
    """领取后的不可变知识快照和服务端索引身份，不保存身份令牌。"""

    task_id: str
    generation_id: str
    actor_id: str
    record: PublicationRead
    index: KnowledgePublicationIndexIdentity


class KnowledgeIndexBuildRepository(ManagedKnowledgeRepository):
    """复用管理候选校验，保持资料→任务→操作→批次的锁顺序。"""

    operation_action: ClassVar[Literal["PUBLISH", "RETRY_INDEX"]] = "PUBLISH"

    async def _index_rows(
        self, session: AsyncSession, task_id: str, actor: str
    ) -> tuple[Task, Operation, Generation] | None:
        """只定位实际确认人及服务端指定动作的INDEX任务，不领取解析任务。"""

        document_id = await session.scalar(
            select(Version.document_id)
            .join(Task, Task.version_id == Version.version_id)
            .join(Operation, Operation.operation_id == Task.operation_id)
            .where(
                Task.task_id == task_id,
                Task.task_type == "INDEX",
                Task.operation_action == self.operation_action,
                Operation.actor_id == actor,
            )
        )
        if document_id is None:
            return None
        await session.scalar(
            select(Document).where(Document.document_id == document_id).with_for_update()
        )
        task = await session.scalar(select(Task).where(Task.task_id == task_id).with_for_update())
        if task is None:
            return None
        operation = await session.scalar(
            select(Operation).where(Operation.operation_id == task.operation_id).with_for_update()
        )
        generation = await session.scalar(
            select(Generation)
            .where(Generation.generation_id == task.generation_id)
            .with_for_update()
        )
        if operation is None or generation is None:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        return task, operation, generation

    async def _check_input(
        self,
        session: AsyncSession,
        rows: tuple[Task, Operation, Generation],
        scope: str,
        index: KnowledgePublicationIndexIdentity,
    ) -> PublicationRead:
        """每次领取/保存都重新核对确认、预留计数和完整索引身份。"""

        task, operation, generation = rows
        try:
            confirmation = ManagedKnowledgeConfirmation.model_validate(
                operation.confirmation_snapshot
            )
        except ValidationError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        record = await self._publication_candidate(
            session, confirmation.document_id, task.version_id, task.revision_no, scope
        )
        target = KnowledgePublicationTarget(
            document_id=confirmation.document_id,
            version_id=task.version_id,
            expected_revision_no=task.revision_no,
            expected_row_version=confirmation.expected_row_version + 1,
        )
        fresh = publication_confirmation(record, target, operation.actor_id)
        if self.operation_action == "RETRY_INDEX":
            if task.retry_of_task_id is None:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            parent = await session.get(Task, task.retry_of_task_id)
            if (
                parent is None
                or parent.state not in {"FAILED", "INTERRUPTED"}
                or parent.task_type != "INDEX"
                or task.attempt_no != parent.attempt_no + 1
                or (parent.version_id, parent.revision_no) != (task.version_id, task.revision_no)
            ):
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        expected = fresh.model_copy(
            update={
                "expected_row_version": confirmation.expected_row_version,
                "generation_id": generation.generation_id,
                "action": self.operation_action,
                "task_id": task.retry_of_task_id
                if self.operation_action == "RETRY_INDEX"
                else None,
            }
        )
        stored_index = KnowledgePublicationIndexIdentity.model_validate(
            {
                "provider": generation.embedding_provider,
                "model": generation.embedding_model,
                "dimension": generation.embedding_dimension,
                "index_version": generation.index_version,
                "chunking_version": generation.chunking_version,
            }
        )
        if (
            confirmation != expected
            or stored_index != index
            or generation.input_hash
            != publication_generation_hash(expected, record.revision.citation_document_id, index)
            or (generation.version_id, generation.revision_no)
            != (task.version_id, task.revision_no)
        ):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        if (
            generation.build_method != "GENERATED"
            or generation.chunk_count != 0
            or await session.scalar(
                select(Chunk.chunk_id)
                .where(Chunk.generation_id == generation.generation_id)
                .limit(1)
            )
            is not None
        ):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        return record

    async def _terminate(
        self,
        session: AsyncSession,
        rows: tuple[Task, Operation, Generation],
        error: ProcessingError,
    ) -> None:
        """失败只修改仍持有执行权的记录，旧发布指针和原件保持。"""

        task, operation, generation = rows
        now = await session.scalar(select(func.now()))
        task.state = {"STALE_INPUT": "STALE", "PROCESSING_INTERRUPTED": "INTERRUPTED"}.get(
            error, "FAILED"
        )
        task.error_code, task.finished_at = error, now
        operation.state = "STALE" if error == "STALE_INPUT" else "FAILED"
        operation.error_code, operation.finished_at = error, now
        generation.state, generation.error_code, generation.finished_at = "FAILED", error, now

    @staticmethod
    def _input_error(error: KnowledgeManagementError) -> ProcessingError:
        """状态、范围和日期变化属于过期输入，数据损坏则明确索引校验失败。"""

        return (
            "INDEX_VALIDATION_FAILED" if error.code == "KNOWLEDGE_DATA_INVALID" else "STALE_INPUT"
        )

    async def claim_index(
        self,
        task_id: str,
        *,
        actor: str,
        scope: str,
        owner_id: str,
        index: KnowledgePublicationIndexIdentity,
    ) -> IndexBuildClaim | None:
        """单次领取当前owner的QUEUED任务，重复、跨用户或终态调用不再生成向量。"""

        async with self.database.session() as session, session.begin():
            rows = await self._index_rows(session, task_id, actor)
            if rows is None:
                return None
            task, operation, generation = rows
            if (
                task.owner_id != owner_id
                or task.state != "QUEUED"
                or operation.state != "CONFIRMED"
                or generation.state != "BUILDING"
            ):
                return None
            try:
                record = await self._check_input(session, rows, scope, index)
            except (KnowledgeManagementError, ValidationError) as error:
                code = (
                    self._input_error(error)
                    if isinstance(error, KnowledgeManagementError)
                    else "INDEX_VALIDATION_FAILED"
                )
                await self._terminate(session, rows, code)
                return None
            task.state, task.started_at = "RUNNING", await session.scalar(select(func.now()))
            operation.state = "EXECUTING"
            return IndexBuildClaim(task_id, generation.generation_id, actor, record, index)

    async def fail_index(
        self, task_id: str, *, actor: str, owner_id: str, error_code: ProcessingError
    ) -> bool:
        """内部失败收尾不要求已撤销的权限，仅允许原确认人及当前RUNNING owner。"""

        async with self.database.session() as session, session.begin():
            rows = await self._index_rows(session, task_id, actor)
            if rows is None:
                return False
            task, operation, generation = rows
            if (
                task.owner_id != owner_id
                or task.state != "RUNNING"
                or operation.state != "EXECUTING"
                or generation.state != "BUILDING"
            ):
                return False
            await self._terminate(session, rows, error_code)
            return True

    async def finish_index(
        self,
        claim: IndexBuildClaim,
        chunks: tuple[ManagedKnowledgeChunkRecord, ...],
        *,
        scope: str,
        owner_id: str,
    ) -> bool:
        """全部分块一次保存并标READY，任务成功仍不代表PUBLISH操作成功。"""

        try:
            await asyncio.to_thread(validate_index_records, claim, chunks)
        except ValueError:
            await self.fail_index(
                claim.task_id,
                actor=claim.actor_id,
                owner_id=owner_id,
                error_code="INDEX_VALIDATION_FAILED",
            )
            return False
        async with self.database.session() as session, session.begin():
            rows = await self._index_rows(session, claim.task_id, claim.actor_id)
            if rows is None:
                return False
            task, operation, generation = rows
            if (
                task.owner_id != owner_id
                or task.state != "RUNNING"
                or operation.state != "EXECUTING"
                or generation.state != "BUILDING"
                or generation.generation_id != claim.generation_id
            ):
                return False
            try:
                record = await self._check_input(session, rows, scope, claim.index)
                if record != claim.record:
                    # 数据库日期可能推进但仍有效，日期本身不是不可变内容。
                    if (
                        record.revision != claim.record.revision
                        or record.previous_version_id != claim.record.previous_version_id
                    ):
                        raise KnowledgeManagementError("STALE_CONFIRMATION")
            except (KnowledgeManagementError, ValidationError) as error:
                code = (
                    self._input_error(error)
                    if isinstance(error, KnowledgeManagementError)
                    else "INDEX_VALIDATION_FAILED"
                )
                await self._terminate(session, rows, code)
                return False
            if (
                not chunks
                or {chunk.generation_id for chunk in chunks} != {claim.generation_id}
                or len({chunk.chunk_id for chunk in chunks}) != len(chunks)
                or [chunk.chunk_index for chunk in chunks] != list(range(len(chunks)))
            ):
                await self._terminate(session, rows, "INDEX_VALIDATION_FAILED")
                return False
            await session.execute(
                insert(Chunk),
                [
                    chunk.model_dump()
                    | {"section_path": list(chunk.section_path), "embedding": list(chunk.embedding)}
                    for chunk in chunks
                ],
            )
            now = await session.scalar(select(func.now()))
            generation.state, generation.chunk_count, generation.finished_at = (
                "READY",
                len(chunks),
                now,
            )
            task.state, task.finished_at = "SUCCEEDED", now
            if self.operation_action == "RETRY_INDEX":
                # 重试只完成候选构建，PUBLISH必须由新的人工确认单独发起。
                operation.state, operation.result_id, operation.finished_at = (
                    "SUCCEEDED",
                    generation.generation_id,
                    now,
                )
            return True
