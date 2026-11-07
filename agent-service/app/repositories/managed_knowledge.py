"""管理上传及解析的短事务，不读写Java业务表，不进行文件或HTTP操作。"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import Date, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.knowledge.publication import (
    publication_confirmation,
    publication_digest,
    publication_generation_hash,
    publication_request_hash,
)
from app.models import (
    ManagedKnowledgeDocument as Document,
)
from app.models import (
    ManagedKnowledgeIndexGeneration as Generation,
)
from app.models import (
    ManagedKnowledgeOperation as Operation,
)
from app.models import (
    ManagedKnowledgeRevision as Revision,
)
from app.models import (
    ManagedKnowledgeTask as Task,
)
from app.models import (
    ManagedKnowledgeVersion as Version,
)
from app.schemas.knowledge_management import (
    KnowledgeManagementError,
    KnowledgeUploadCommand,
    KnowledgeUploadResult,
)
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationIndexIdentity,
)
from app.schemas.managed_knowledge import ManagedKnowledgeRevisionSnapshot
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation


def managed_id(prefix: str) -> str:
    """仅新管理数据生成身份，不改变固定业务或语料身份。"""

    return prefix + "-" + uuid4().hex.upper()


@dataclass(frozen=True, slots=True)
class UploadPlan:
    """原件提交前的目标快照，接收事务仍须重新验证。"""

    document_id: str
    version_id: str
    revision_no: int
    row_version: int
    previous_version_id: str | None
    new_document: bool
    new_version: bool


@dataclass(frozen=True, slots=True)
class RevisionRead:
    """解析/预览共用的不可变读取快照。"""

    document_id: str
    citation_document_id: str
    row_version: int
    current_revision_no: int
    publication_state: str
    snapshot: ManagedKnowledgeRevisionSnapshot
    metadata_hash: str


@dataclass(frozen=True, slots=True)
class PublicationRead:
    """一次SQL读取发布候选、原发布指针、解析状态和数据库UTC日期。"""

    revision: RevisionRead
    previous_version_id: str | None
    specification_version: str
    parse_succeeded: bool
    today: date


class ManagedKnowledgeRepository:
    """事务保护幂等、并发修订、任务执行权和解析只写一次。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def find_upload(
        self, actor: str, key: str, input_hash: str
    ) -> KnowledgeUploadResult | None:
        """授权后才调用，重放查原操作，不根据新的状态重新执行上传。"""

        async with self.database.session() as session:
            operation = await session.scalar(
                select(Operation).where(
                    Operation.actor_id == actor,
                    Operation.action == "UPLOAD",
                    Operation.idempotency_key == key,
                )
            )
            if operation is None:
                return None
            if operation.input_hash != input_hash:
                raise KnowledgeManagementError("IDEMPOTENCY_CONFLICT")
            return await self._result(session, operation, replayed=True)

    async def _result(
        self,
        session: AsyncSession,
        operation: Operation,
        *,
        replayed: bool,
    ) -> KnowledgeUploadResult:
        """返回原操作/任务身份及当前处理状态，不暴露原件key或错误原文。"""

        row = (
            await session.execute(
                select(Document, Version, Task)
                .join(
                    Version,
                    Version.document_id == Document.document_id,
                )
                .join(Task, Task.version_id == Version.version_id)
                .where(
                    Task.operation_id == operation.operation_id,
                    Task.task_type == "PARSE",
                )
            )
        ).one()
        document, version, task = row
        return KnowledgeUploadResult.model_validate(
            {
                "document_id": document.document_id,
                "version_id": version.version_id,
                "revision_no": task.revision_no,
                "operation_id": operation.operation_id,
                "task_id": task.task_id,
                "row_version": document.row_version,
                "task_state": task.state,
                "error_code": task.error_code,
                "is_current_revision": version.current_revision_no == task.revision_no,
                "replayed": replayed,
            }
        )

    async def upload_result(self, operation_id: str, *, replayed: bool) -> KnowledgeUploadResult:
        """仅由已完成授权的应用层按内部操作身份回读。"""

        async with self.database.session() as session:
            operation = await session.get(Operation, operation_id)
            if operation is None:
                raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
            return await self._result(session, operation, replayed=replayed)

    async def _check_target(
        self, session: AsyncSession, command: KnowledgeUploadCommand, *, lock: bool = False
    ) -> tuple[Document | None, Version | None]:
        """同一资料的修改先锁资料，再核对版本和修订，保持一致锁顺序。"""

        if command.document_id is None:
            return None, None
        statement = select(Document).where(Document.document_id == command.document_id)
        document = await session.scalar(statement.with_for_update() if lock else statement)
        if document is None:
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
        if document.row_version != command.expected_row_version:
            raise KnowledgeManagementError("STALE_DOCUMENT")
        if command.version_id is not None:
            version = await session.get(Version, command.version_id)
            if version is None or version.document_id != document.document_id:
                raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
            if version.publication_state != "DRAFT":
                raise KnowledgeManagementError("SEALED_VERSION_REQUIRES_NEW_VERSION")
            if version.current_revision_no != command.expected_revision_no:
                raise KnowledgeManagementError("STALE_REVISION")
            if version.specification_version != command.metadata.specification_version:
                raise KnowledgeManagementError("SPECIFICATION_VERSION_CONFLICT")
            return document, version
        duplicate = await session.scalar(
            select(Version.version_id).where(
                Version.document_id == document.document_id,
                Version.specification_version == command.metadata.specification_version,
            )
        )
        if duplicate is not None:
            raise KnowledgeManagementError("SPECIFICATION_VERSION_CONFLICT")
        return document, None

    async def plan_upload(self, command: KnowledgeUploadCommand) -> UploadPlan:
        """读取候选目标，文件落盘期间不持有数据库事务。"""

        async with self.database.session() as session:
            document, version = await self._check_target(session, command)
            return UploadPlan(
                document.document_id if document else managed_id("DOC"),
                version.version_id if version else managed_id("VER"),
                version.current_revision_no + 1 if version else 1,
                document.row_version if document else 0,
                document.current_version_id if document else None,
                document is None,
                version is None,
            )

    async def accept_upload(
        self,
        command: KnowledgeUploadCommand,
        plan: UploadPlan,
        snapshot: ManagedKnowledgeRevisionSnapshot,
        *,
        actor: str,
        input_hash: str,
        trace_id: str,
        owner_id: str,
    ) -> KnowledgeUploadResult:
        """保存原件引用、修订和任务，同一事务完成旧任务失效及上传成功记录。"""

        async with self.database.session() as session, session.begin():
            lock_hash = hashlib.sha256(
                f"{actor}:UPLOAD:{command.idempotency_key}".encode()
            ).digest()
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": int.from_bytes(lock_hash[:8], "big", signed=True)},
            )
            previous = await session.scalar(
                select(Operation).where(
                    Operation.actor_id == actor,
                    Operation.action == "UPLOAD",
                    Operation.idempotency_key == command.idempotency_key,
                )
            )
            if previous is not None:
                if previous.input_hash != input_hash:
                    raise KnowledgeManagementError("IDEMPOTENCY_CONFLICT")
                return await self._result(session, previous, replayed=True)
            document, version = await self._check_target(session, command, lock=True)
            if document is not None and document.row_version != plan.row_version:
                raise KnowledgeManagementError("STALE_DOCUMENT")
            if plan.new_document:
                await session.execute(
                    insert(Document).values(
                        document_id=plan.document_id,
                        created_by=actor,
                        row_version=0,
                    )
                )
            if plan.new_version:
                await session.execute(
                    insert(Version).values(
                        version_id=plan.version_id,
                        document_id=plan.document_id,
                        specification_version=command.metadata.specification_version,
                        citation_document_id=plan.version_id,
                        source_kind="UPLOAD",
                        created_by=actor,
                    )
                )
            else:
                if version is None or version.current_revision_no + 1 != plan.revision_no:
                    raise KnowledgeManagementError("STALE_REVISION")
                await session.execute(
                    update(Task)
                    .where(
                        Task.version_id == plan.version_id,
                        Task.state.in_(("QUEUED", "RUNNING")),
                    )
                    .values(state="STALE", error_code="STALE_INPUT", finished_at=func.now())
                )
                await session.execute(
                    update(Operation)
                    .where(
                        Operation.version_id == plan.version_id,
                        Operation.action.in_(("PUBLISH", "RETRY_INDEX")),
                        Operation.state.in_(("CONFIRMED", "EXECUTING")),
                    )
                    .values(state="STALE", error_code="STALE_INPUT", finished_at=func.now())
                )
                await session.execute(
                    update(Generation)
                    .where(
                        Generation.version_id == plan.version_id,
                        Generation.state == "BUILDING",
                    )
                    .values(state="FAILED", error_code="STALE_INPUT", finished_at=func.now())
                )
                await session.execute(
                    update(Version)
                    .where(Version.version_id == plan.version_id)
                    .values(
                        current_revision_no=plan.revision_no,
                    )
                )
            await session.execute(
                insert(Revision).values(
                    **snapshot.model_dump(),
                    metadata_hash=snapshot.metadata_digest(),
                )
            )
            operation_id, task_id = managed_id("OP"), managed_id("TASK")
            confirmation = ManagedKnowledgeConfirmation(
                actor_id=actor,
                action="UPLOAD",
                document_id=plan.document_id,
                version_id=plan.version_id,
                revision_no=plan.revision_no,
                raw_hash=snapshot.raw_hash,
                metadata_hash=snapshot.metadata_digest(),
                expected_row_version=plan.row_version,
                previous_version_id=plan.previous_version_id,
            )
            await session.execute(
                insert(Operation).values(
                    operation_id=operation_id,
                    actor_id=actor,
                    action="UPLOAD",
                    version_id=plan.version_id,
                    revision_no=plan.revision_no,
                    target_id=plan.version_id,
                    idempotency_key=command.idempotency_key,
                    input_hash=input_hash,
                    confirmation_snapshot=confirmation.model_dump(mode="json"),
                    state="SUCCEEDED",
                    result_id=plan.version_id,
                    finished_at=func.now(),
                )
            )
            await session.execute(
                insert(Task).values(
                    task_id=task_id,
                    operation_id=operation_id,
                    operation_action="UPLOAD",
                    version_id=plan.version_id,
                    revision_no=plan.revision_no,
                    task_type="PARSE",
                    owner_id=owner_id,
                    trace_id=trace_id,
                )
            )
            await session.execute(
                update(Document)
                .where(Document.document_id == plan.document_id)
                .values(
                    row_version=Document.row_version + 1,
                )
            )
            operation = await session.get(Operation, operation_id)
            assert operation is not None
            return await self._result(session, operation, replayed=False)

    @staticmethod
    def _read_record(document: Document, version: Version, revision: Revision) -> RevisionRead:
        """读取快照时校验元数据哈希，不把数据库损坏变成可用预览。"""

        try:
            snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
                {
                    key: getattr(revision, key)
                    for key in ManagedKnowledgeRevisionSnapshot.model_fields
                }
            )
        except ValidationError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        if snapshot.metadata_digest() != revision.metadata_hash:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        return RevisionRead(
            document.document_id,
            version.citation_document_id,
            document.row_version,
            version.current_revision_no,
            version.publication_state,
            snapshot,
            revision.metadata_hash,
        )

    async def read_revision(
        self, version_id: str, revision_no: int, scope: str, *, document_id: str | None = None
    ) -> RevisionRead:
        """权限及可选资料归属在SQL中核对，历史修订不回退其他正文或原件。"""

        async with self.database.session() as session:
            statement = (
                select(Document, Version, Revision)
                .join(
                    Version,
                    Version.document_id == Document.document_id,
                )
                .join(Revision, Revision.version_id == Version.version_id)
                .where(
                    Version.version_id == version_id,
                    Revision.revision_no == revision_no,
                    Revision.permission_scope == scope,
                )
            )
            if document_id is not None:
                statement = statement.where(Document.document_id == document_id)
            row = (await session.execute(statement)).one_or_none()
            if row is None:
                raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
            return self._read_record(*row)

    async def read_publication_candidate(
        self, document_id: str, version_id: str, revision_no: int, scope: str
    ) -> PublicationRead:
        """同一SQL快照核对归属及范围，不恢复任务、不预留执行权或改变发布指针。"""

        async with self.database.session() as session:
            return await self._publication_candidate(
                session, document_id, version_id, revision_no, scope
            )

    async def _publication_candidate(
        self, session: AsyncSession, document_id: str, version_id: str, revision_no: int, scope: str
    ) -> PublicationRead:
        """读候选和接收事务共用同一查询，日期取锁取得后该语句的数据库UTC时间。"""

        parsed = (
            select(Task.task_id)
            .where(
                Task.version_id == Version.version_id,
                Task.revision_no == Revision.revision_no,
                Task.task_type == "PARSE",
                Task.state == "SUCCEEDED",
            )
            .correlate(Version, Revision)
            .exists()
        )
        row = (
            await session.execute(
                select(
                    Document,
                    Version,
                    Revision,
                    parsed,
                    func.timezone("UTC", func.statement_timestamp()).cast(Date),
                )
                .join(Version, Version.document_id == Document.document_id)
                .join(Revision, Revision.version_id == Version.version_id)
                .where(
                    Document.document_id == document_id,
                    Version.version_id == version_id,
                    Revision.revision_no == revision_no,
                    Revision.permission_scope == scope,
                )
            )
        ).one_or_none()
        if row is None:
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
        document, version, revision, parse_succeeded, today = row
        return PublicationRead(
            self._read_record(document, version, revision),
            document.current_version_id,
            version.specification_version,
            parse_succeeded,
            today,
        )

    async def _publication_result(
        self, session: AsyncSession, operation: Operation, scope: str, *, replayed: bool
    ) -> KnowledgePublicationAcceptance:
        """重放只看原操作的状态，仍按原目标修订范围控制可见性，不重新排队。"""

        row = (
            await session.execute(
                select(Operation, Generation, Task, Version.document_id)
                .select_from(Operation)
                .join(
                    Revision,
                    (Revision.version_id == Operation.version_id)
                    & (Revision.revision_no == Operation.revision_no),
                )
                .join(Version, Version.version_id == Operation.version_id)
                .outerjoin(
                    Generation,
                    Generation.generation_id
                    == Operation.confirmation_snapshot["generation_id"].astext,
                )
                .outerjoin(
                    Task,
                    (Task.operation_id == Operation.operation_id) & (Task.task_type == "INDEX"),
                )
                .where(
                    Operation.operation_id == operation.operation_id,
                    Revision.permission_scope == scope,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
        operation, generation, task, document_id = row
        try:
            snapshot = ManagedKnowledgeConfirmation.model_validate(operation.confirmation_snapshot)
            if (
                snapshot.generation_id is None
                or snapshot.action != "PUBLISH"
                or snapshot.actor_id != operation.actor_id
                or snapshot.version_id != operation.version_id
                or snapshot.revision_no != operation.revision_no
                or snapshot.document_id != document_id
            ):
                raise ValueError("publication must bind its reserved generation")
            if (
                generation is None
                or (generation.version_id, generation.revision_no)
                != (operation.version_id, operation.revision_no)
                or (task is not None and task.generation_id != generation.generation_id)
            ):
                raise ValueError("publication reservation is inconsistent")
            return KnowledgePublicationAcceptance.model_validate(
                {
                    "document_id": snapshot.document_id,
                    "version_id": operation.version_id,
                    "revision_no": operation.revision_no,
                    "operation_id": operation.operation_id,
                    "operation_state": operation.state,
                    "generation_id": generation.generation_id,
                    "generation_state": generation.state,
                    "task_id": task.task_id if task else None,
                    "task_state": task.state if task else None,
                    "reserved_row_version": snapshot.expected_row_version + 1,
                    "error_code": operation.error_code,
                    "replayed": replayed,
                }
            )
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None

    async def accept_publication(
        self,
        command: KnowledgePublicationConfirmCommand,
        *,
        actor: str,
        scope: str,
        index: KnowledgePublicationIndexIdentity | None,
        trace_id: str,
        owner_id: str,
    ) -> KnowledgePublicationAcceptance:
        """授权后在短事务内串行化幂等键及资料修改，失败完整回滚，不执行外部调用。"""

        input_hash = publication_request_hash(command)
        async with self.database.session() as session, session.begin():
            lock_hash = hashlib.sha256(
                f"{actor}:PUBLISH:{command.idempotency_key}".encode()
            ).digest()
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": int.from_bytes(lock_hash[:8], "big", signed=True)},
            )
            previous = await session.scalar(
                select(Operation).where(
                    Operation.actor_id == actor,
                    Operation.action == "PUBLISH",
                    Operation.idempotency_key == command.idempotency_key,
                )
            )
            if previous is not None:
                result = await self._publication_result(session, previous, scope, replayed=True)
                if previous.input_hash != input_hash:
                    raise KnowledgeManagementError("IDEMPOTENCY_CONFLICT")
                return result
            visible = (
                select(Version.version_id)
                .join(Revision, Revision.version_id == Version.version_id)
                .where(
                    Version.document_id == Document.document_id,
                    Version.version_id == command.version_id,
                    Revision.revision_no == command.expected_revision_no,
                    Revision.permission_scope == scope,
                )
                .correlate(Document)
                .exists()
            )
            document = await session.scalar(
                select(Document)
                .where(Document.document_id == command.document_id, visible)
                .with_for_update()
            )
            if document is None:
                raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
            record = await self._publication_candidate(
                session,
                command.document_id,
                command.version_id,
                command.expected_revision_no,
                scope,
            )
            confirmation = publication_confirmation(record, command, actor)
            if not hmac.compare_digest(
                command.confirmation_digest, publication_digest(confirmation)
            ):
                raise KnowledgeManagementError("STALE_CONFIRMATION")
            if document.row_version == 2**63 - 1:
                raise KnowledgeManagementError("KNOWLEDGE_COUNTER_EXHAUSTED")
            pending = await session.scalar(
                select(Operation.operation_id)
                .join(Version, Version.version_id == Operation.version_id)
                .where(
                    Version.document_id == command.document_id,
                    Operation.action.in_(("PUBLISH", "RETRY_INDEX")),
                    Operation.state.in_(("CONFIRMED", "EXECUTING")),
                )
                .limit(1)
            )
            if pending is not None:
                raise KnowledgeManagementError("PUBLICATION_IN_PROGRESS")
            if index is None:
                raise KnowledgeManagementError("KNOWLEDGE_INDEX_NOT_CONFIGURED")
            generation_hash = publication_generation_hash(
                confirmation, record.revision.citation_document_id, index
            )
            ready = await session.scalar(
                select(Generation)
                .where(
                    Generation.version_id == command.version_id,
                    Generation.revision_no == command.expected_revision_no,
                    Generation.state == "READY",
                    Generation.input_hash == generation_hash,
                    Generation.embedding_provider == index.provider,
                    Generation.embedding_model == index.model,
                    Generation.embedding_dimension == index.dimension,
                    Generation.index_version == index.index_version,
                    Generation.chunking_version == index.chunking_version,
                )
                .order_by(Generation.created_at, Generation.generation_id)
                .limit(1)
            )
            generation_id = ready.generation_id if ready else managed_id("GEN")
            operation_id = managed_id("OP")
            stored = ManagedKnowledgeConfirmation.model_validate(
                {**confirmation.model_dump(), "generation_id": generation_id}
            )
            await session.execute(
                insert(Operation).values(
                    operation_id=operation_id,
                    actor_id=actor,
                    action="PUBLISH",
                    version_id=command.version_id,
                    revision_no=command.expected_revision_no,
                    target_id=command.version_id,
                    idempotency_key=command.idempotency_key,
                    input_hash=input_hash,
                    confirmation_snapshot=stored.model_dump(mode="json"),
                    state="CONFIRMED",
                )
            )
            if ready is None:
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
                        input_hash=generation_hash,
                        build_method="GENERATED",
                        state="BUILDING",
                    )
                )
                await session.execute(
                    insert(Task).values(
                        task_id=managed_id("TASK"),
                        operation_id=operation_id,
                        operation_action="PUBLISH",
                        task_type="INDEX",
                        version_id=command.version_id,
                        revision_no=command.expected_revision_no,
                        generation_id=generation_id,
                        owner_id=owner_id,
                        trace_id=trace_id,
                        state="QUEUED",
                    )
                )
            document.row_version += 1
            await session.flush()
            operation = await session.get(Operation, operation_id)
            assert operation is not None
            return await self._publication_result(session, operation, scope, replayed=False)

    async def _parse_rows(
        self, session: AsyncSession, task_id: str
    ) -> tuple[Document, Version, Revision, Task] | None:
        """所有任务状态修改都先锁资料，避免与修订提交采用相反锁顺序。"""

        document_id = await session.scalar(
            select(Version.document_id)
            .join(
                Task,
                Task.version_id == Version.version_id,
            )
            .where(Task.task_id == task_id, Task.task_type == "PARSE")
        )
        if document_id is None:
            return None
        document = await session.scalar(
            select(Document)
            .where(
                Document.document_id == document_id,
            )
            .with_for_update()
        )
        task = await session.scalar(select(Task).where(Task.task_id == task_id).with_for_update())
        if document is None or task is None:
            return None
        version = await session.get(Version, task.version_id)
        revision = await session.get(Revision, (task.version_id, task.revision_no))
        if version is None or revision is None:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        return document, version, revision, task

    @staticmethod
    def _current(version: Version, task: Task) -> bool:
        """只允许当前草稿修订接收迟到结果。"""

        return (
            version.publication_state == "DRAFT" and version.current_revision_no == task.revision_no
        )

    async def claim_parse(self, task_id: str, owner_id: str) -> RevisionRead | None:
        """当前进程只能领取自身QUEUED任务，重复调用不重复解析。"""

        async with self.database.session() as session, session.begin():
            rows = await self._parse_rows(session, task_id)
            if rows is None:
                return None
            document, version, revision, task = rows
            if task.state != "QUEUED" or task.owner_id != owner_id:
                return None
            if not self._current(version, task) or revision.body is not None:
                task.state, task.error_code, task.finished_at = (
                    "STALE",
                    "STALE_INPUT",
                    await session.scalar(select(func.now())),
                )
                return None
            record = self._read_record(document, version, revision)
            task.state, task.started_at = "RUNNING", await session.scalar(select(func.now()))
            return record

    async def finish_parse(
        self,
        task_id: str,
        owner_id: str,
        *,
        body: str | None = None,
        normalized_hash: str | None = None,
        error_code: str | None = None,
    ) -> bool:
        """执行权、当前修订及只写一次保护在同一短事务重新核对。"""

        async with self.database.session() as session, session.begin():
            rows = await self._parse_rows(session, task_id)
            if rows is None:
                return False
            _, version, revision, task = rows
            if task.owner_id != owner_id or task.state != "RUNNING":
                return False
            now = await session.scalar(select(func.now()))
            if not self._current(version, task) or revision.body is not None:
                task.state, task.error_code, task.finished_at = "STALE", "STALE_INPUT", now
                return False
            if error_code is not None:
                if error_code not in {"PARSE_FAILED", "STORAGE_ERROR"}:
                    raise KnowledgeManagementError("INVALID_PARSE_RESULT")
                task.state, task.error_code, task.finished_at = "FAILED", error_code, now
                return False
            if (
                body is None
                or normalized_hash is None
                or not body.strip()
                or body.startswith("\ufeff")
                or "\r" in body
                or hashlib.sha256(body.encode()).hexdigest() != normalized_hash
            ):
                raise KnowledgeManagementError("INVALID_PARSE_RESULT")
            revision.body, revision.normalized_hash = body, normalized_hash
            task.state, task.finished_at = "SUCCEEDED", now
            return True

    async def recover_interrupted(self, owner_id: str) -> int:
        """单实例管理服务显式启动时标记旧进程任务，不自动重试或调用模型。"""

        async with self.database.session() as session, session.begin():
            tasks = (
                await session.scalars(
                    select(Task)
                    .where(
                        Task.owner_id != owner_id,
                        Task.state.in_(("QUEUED", "RUNNING")),
                    )
                    .with_for_update()
                )
            ).all()
            operation_ids = [task.operation_id for task in tasks]
            generation_ids = [
                task.generation_id for task in tasks if task.generation_id is not None
            ]
            now = await session.scalar(select(func.now()))
            for task in tasks:
                task.state, task.error_code, task.finished_at = (
                    "INTERRUPTED",
                    "PROCESSING_INTERRUPTED",
                    now,
                )
            await session.execute(
                update(Operation)
                .where(
                    Operation.operation_id.in_(operation_ids),
                    Operation.action.in_(("PUBLISH", "RETRY_INDEX")),
                    Operation.state.in_(("CONFIRMED", "EXECUTING")),
                )
                .values(state="FAILED", error_code="PROCESSING_INTERRUPTED", finished_at=now)
            )
            await session.execute(
                update(Generation)
                .where(
                    Generation.generation_id.in_(generation_ids),
                    Generation.state == "BUILDING",
                )
                .values(state="FAILED", error_code="PROCESSING_INTERRUPTED", finished_at=now)
            )
            return len(tasks)
