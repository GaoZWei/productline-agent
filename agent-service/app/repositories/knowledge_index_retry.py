"""索引重试审查与原子接收，保留失败链，不创建规范版本或直接发布。"""

import hashlib
import hmac
from dataclasses import dataclass

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.index_retry import index_retry_digest, index_retry_request_hash
from app.knowledge.publication import publication_confirmation, publication_generation_hash
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.knowledge_index_build import KnowledgeIndexBuildRepository
from app.repositories.managed_knowledge import PublicationRead, managed_id
from app.schemas.knowledge_index_retry import (
    KnowledgeIndexRetryCommand,
    KnowledgeIndexRetryReceipt,
    KnowledgeIndexRetryTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeConfirmation,
    ManagedKnowledgeGenerationRecord,
    ManagedKnowledgeTaskRecord,
)


@dataclass(frozen=True, slots=True)
class IndexRetryRead:
    """原任务及当前草稿的不可变审查事实，不保存调用者凭据。"""

    confirmation: ManagedKnowledgeConfirmation
    record: PublicationRead
    source: ManagedKnowledgeTaskRecord
    index: KnowledgePublicationIndexIdentity


class KnowledgeIndexRetryRepository(KnowledgeIndexBuildRepository):
    """RETRY_INDEX仓库固定对应同一授权动作，复用向量构建但不复用发布权限。"""

    operation_action = "RETRY_INDEX"

    async def _source(
        self,
        session: AsyncSession,
        target: KnowledgeIndexRetryTarget,
        *,
        actor: str,
        scope: str,
        index: KnowledgePublicationIndexIdentity,
    ) -> IndexRetryRead:
        """重新读取当前修订、失败链尾和原索引身份，不能对旧修订或成功任务重试。"""

        record = await self._publication_candidate(
            session, target.document_id, target.version_id, target.expected_revision_no, scope
        )
        fresh = publication_confirmation(record, target, actor)
        row = (
            await session.execute(
                select(Task, Operation, Generation)
                .join(Operation, Operation.operation_id == Task.operation_id)
                .outerjoin(Generation, Generation.generation_id == Task.generation_id)
                .where(
                    Task.task_id == target.task_id,
                    Task.version_id == target.version_id,
                    Task.revision_no == target.expected_revision_no,
                )
            )
        ).one_or_none()
        if row is None:
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
        task, operation, generation = row
        if (
            task.task_type != "INDEX"
            or task.operation_action not in {"PUBLISH", "RETRY_INDEX"}
            or task.state not in {"FAILED", "INTERRUPTED"}
        ):
            raise KnowledgeManagementError("INDEX_RETRY_NOT_ELIGIBLE")
        if operation.state != "FAILED" or generation is None or generation.state != "FAILED":
            raise KnowledgeManagementError("INDEX_RETRY_NOT_ELIGIBLE")
        try:
            source = ManagedKnowledgeTaskRecord.model_validate(
                {key: getattr(task, key) for key in ManagedKnowledgeTaskRecord.model_fields}
            )
            failed_index = ManagedKnowledgeGenerationRecord.model_validate(
                {
                    key: getattr(generation, key)
                    for key in ManagedKnowledgeGenerationRecord.model_fields
                }
            )
            original = ManagedKnowledgeConfirmation.model_validate(operation.confirmation_snapshot)
            old_index = KnowledgePublicationIndexIdentity.model_validate(
                {
                    "provider": failed_index.embedding_provider,
                    "model": failed_index.embedding_model,
                    "dimension": failed_index.embedding_dimension,
                    "index_version": failed_index.index_version,
                    "chunking_version": failed_index.chunking_version,
                }
            )
            if (
                original.actor_id != operation.actor_id
                or original.action != task.operation_action
                or original.document_id != target.document_id
                or original.version_id != target.version_id
                or original.revision_no != target.expected_revision_no
                or original.generation_id != task.generation_id
                or original.task_id != source.retry_of_task_id
                or failed_index.version_id != task.version_id
                or failed_index.revision_no != task.revision_no
                or failed_index.build_method != "GENERATED"
                or source.error_code is None
                or (original.raw_hash, original.normalized_hash, original.metadata_hash)
                != (fresh.raw_hash, fresh.normalized_hash, fresh.metadata_hash)
                or failed_index.input_hash
                != publication_generation_hash(
                    fresh, record.revision.citation_document_id, old_index
                )
            ):
                raise ValueError("failed task input does not match immutable revision")
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        if old_index != index:
            raise KnowledgeManagementError("INDEX_RETRY_IDENTITY_CHANGED")
        if (
            await session.scalar(
                select(Task.task_id).where(Task.retry_of_task_id == task.task_id).limit(1)
            )
            is not None
        ):
            raise KnowledgeManagementError("INDEX_RETRY_SOURCE_NOT_LATEST")
        if max(task.attempt_no, record.revision.row_version) == 2**63 - 1:
            raise KnowledgeManagementError("KNOWLEDGE_COUNTER_EXHAUSTED")
        active = await session.scalar(
            select(Operation.operation_id)
            .join(Version, Version.version_id == Operation.version_id)
            .where(
                Version.document_id == target.document_id,
                Operation.action.in_(("PUBLISH", "RETRY_INDEX")),
                Operation.state.in_(("CONFIRMED", "EXECUTING")),
            )
            .limit(1)
        )
        if active is not None:
            raise KnowledgeManagementError("PUBLICATION_IN_PROGRESS")
        confirmation = ManagedKnowledgeConfirmation.model_validate(
            {
                **fresh.model_dump(),
                "action": "RETRY_INDEX",
                "task_id": task.task_id,
                "generation_id": task.generation_id,
            }
        )
        return IndexRetryRead(confirmation, record, source, old_index)

    async def prepare_retry(
        self,
        target: KnowledgeIndexRetryTarget,
        *,
        actor: str,
        scope: str,
        index: KnowledgePublicationIndexIdentity,
    ) -> IndexRetryRead:
        """只读一致快照准备新重试意图，不改旧任务、不分配任务或调用模型。"""

        async with self.database.session() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            return await self._source(session, target, actor=actor, scope=scope, index=index)

    async def _retry_result(
        self, session: AsyncSession, operation_id: str, scope: str, *, replayed: bool
    ) -> KnowledgeIndexRetryReceipt:
        """回查本操作自己的任务状态，原失败或后续重试不改变该操作的幂等身份。"""

        row = (
            await session.execute(
                select(Operation, Task, Generation, Version.document_id)
                .select_from(Operation)
                .join(
                    Task,
                    (Task.operation_id == Operation.operation_id) & (Task.task_type == "INDEX"),
                )
                .join(Generation, Generation.generation_id == Task.generation_id)
                .join(Version, Version.version_id == Task.version_id)
                .join(
                    Revision,
                    (Revision.version_id == Task.version_id)
                    & (Revision.revision_no == Task.revision_no),
                )
                .where(
                    Operation.operation_id == operation_id,
                    Operation.action == "RETRY_INDEX",
                    Revision.permission_scope == scope,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
        operation, task, generation, document_id = row
        try:
            confirmation = ManagedKnowledgeConfirmation.model_validate(
                operation.confirmation_snapshot
            )
            if (
                confirmation.action != "RETRY_INDEX"
                or confirmation.actor_id != operation.actor_id
                or confirmation.document_id != document_id
                or confirmation.version_id != task.version_id
                or confirmation.revision_no != task.revision_no
                or confirmation.generation_id != generation.generation_id
                or confirmation.task_id != task.retry_of_task_id
                or task.operation_action != "RETRY_INDEX"
                or (
                    operation.state == "SUCCEEDED"
                    and operation.result_id != generation.generation_id
                )
            ):
                raise ValueError("retry operation identity is inconsistent")
            return KnowledgeIndexRetryReceipt.model_validate(
                {
                    "document_id": document_id,
                    "version_id": task.version_id,
                    "revision_no": task.revision_no,
                    "operation_id": operation.operation_id,
                    "operation_state": operation.state,
                    "generation_id": generation.generation_id,
                    "generation_state": generation.state,
                    "task_id": task.task_id,
                    "task_state": task.state,
                    "error_code": operation.error_code,
                    "reserved_row_version": confirmation.expected_row_version + 1,
                    "replayed": replayed,
                    "retry_of_task_id": task.retry_of_task_id,
                    "attempt_no": task.attempt_no,
                }
            )
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None

    async def accept_retry(
        self,
        command: KnowledgeIndexRetryCommand,
        *,
        actor: str,
        scope: str,
        index: KnowledgePublicationIndexIdentity | None,
        owner_id: str,
        trace_id: str,
    ) -> KnowledgeIndexRetryReceipt:
        """同一事务校验新意图、创建独立批次/任务并预留计数，原失败记录不覆盖。"""

        async with self.database.session() as session, session.begin():
            key = hashlib.sha256(f"{actor}:RETRY_INDEX:{command.idempotency_key}".encode()).digest()
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": int.from_bytes(key[:8], "big", signed=True)},
            )
            previous = await session.scalar(
                select(Operation).where(
                    Operation.actor_id == actor,
                    Operation.action == "RETRY_INDEX",
                    Operation.idempotency_key == command.idempotency_key,
                )
            )
            input_hash = index_retry_request_hash(command)
            if previous is not None:
                result = await self._retry_result(
                    session, previous.operation_id, scope, replayed=True
                )
                if previous.input_hash != input_hash:
                    raise KnowledgeManagementError("IDEMPOTENCY_CONFLICT")
                return result
            visible = await session.scalar(
                select(Version.document_id)
                .join(Revision, Revision.version_id == Version.version_id)
                .where(
                    Version.document_id == command.document_id,
                    Version.version_id == command.version_id,
                    Revision.revision_no == command.expected_revision_no,
                    Revision.permission_scope == scope,
                )
            )
            if visible is None:
                raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
            document = await session.scalar(
                select(Document)
                .where(Document.document_id == command.document_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if document is None:
                raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
            if index is None:
                raise KnowledgeManagementError("KNOWLEDGE_INDEX_NOT_CONFIGURED")
            read = await self._source(session, command, actor=actor, scope=scope, index=index)
            if not hmac.compare_digest(
                command.confirmation_digest, index_retry_digest(read.confirmation)
            ):
                raise KnowledgeManagementError("STALE_CONFIRMATION")
            generation_id, task_id, operation_id = (
                managed_id("GEN"),
                managed_id("TASK"),
                managed_id("OP"),
            )
            stored = ManagedKnowledgeConfirmation.model_validate(
                {**read.confirmation.model_dump(), "generation_id": generation_id}
            )
            await session.execute(
                insert(Operation).values(
                    operation_id=operation_id,
                    actor_id=actor,
                    action="RETRY_INDEX",
                    version_id=command.version_id,
                    revision_no=command.expected_revision_no,
                    target_id=command.version_id,
                    idempotency_key=command.idempotency_key,
                    input_hash=input_hash,
                    confirmation_snapshot=stored.model_dump(mode="json"),
                    state="CONFIRMED",
                )
            )
            await session.execute(
                insert(Generation).values(
                    generation_id=generation_id,
                    version_id=command.version_id,
                    revision_no=command.expected_revision_no,
                    embedding_provider=index.provider,
                    embedding_model=index.model,
                    embedding_dimension=index.dimension,
                    index_version=index.index_version,
                    chunking_version=index.chunking_version,
                    input_hash=publication_generation_hash(
                        stored, read.record.revision.citation_document_id, index
                    ),
                    build_method="GENERATED",
                    state="BUILDING",
                )
            )
            await session.execute(
                insert(Task).values(
                    task_id=task_id,
                    operation_id=operation_id,
                    operation_action="RETRY_INDEX",
                    task_type="INDEX",
                    version_id=command.version_id,
                    revision_no=command.expected_revision_no,
                    generation_id=generation_id,
                    owner_id=owner_id,
                    trace_id=trace_id,
                    state="QUEUED",
                    attempt_no=read.source.attempt_no + 1,
                    retry_of_task_id=command.task_id,
                )
            )
            document.row_version += 1
            await session.flush()
            return await self._retry_result(session, operation_id, scope, replayed=False)
