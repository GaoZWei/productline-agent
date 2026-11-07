"""停用当前发布版本的短事务，保留原件和引用，不构建或删除索引。"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from app.knowledge.disable import disable_digest, disable_request_hash
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeLibrary as Library
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.managed_knowledge import ManagedKnowledgeRepository, managed_id
from app.schemas.knowledge_disable import (
    KnowledgeDisableCommand,
    KnowledgeDisableReceipt,
    KnowledgeDisableTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge import ManagedKnowledgeMetadata
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation


@dataclass(frozen=True, slots=True)
class DisableRead:
    """停用审查只保存所需的发布身份和元数据，不读取正文或向量。"""

    confirmation: ManagedKnowledgeConfirmation
    metadata: ManagedKnowledgeMetadata
    published_at: datetime


class KnowledgeDisableRepository(ManagedKnowledgeRepository):
    """先串行化幂等键，再按库→资料→任务→操作→批次顺序保持一致性。"""

    async def _row(
        self, session: AsyncSession, document_id: str, version_id: str, revision_no: int, scope: str
    ) -> RowMapping:
        """单次SQL读取元数据和封存身份，历史重放也按原修订范围过滤。"""

        query = (
            select(
                Document.document_id,
                Document.row_version,
                Document.current_version_id,
                Library.source_mode,
                Library.release_revision,
                Version.version_id,
                Version.publication_state,
                Version.current_revision_no,
                Version.published_revision_no,
                Version.published_generation_id,
                Version.published_at,
                Version.specification_version.label("version_specification_version"),
                Revision.revision_no,
                Revision.raw_hash,
                Revision.normalized_hash,
                Revision.metadata_hash,
                *[getattr(Revision, key) for key in ManagedKnowledgeMetadata.model_fields],
            )
            .select_from(Document)
            .join(Library, Library.library_id == Document.library_id)
            .join(Version, Version.document_id == Document.document_id)
            .join(Revision, Revision.version_id == Version.version_id)
            .where(
                Document.document_id == document_id,
                Version.version_id == version_id,
                Revision.revision_no == revision_no,
                Revision.permission_scope == scope,
            )
        )
        row = (await session.execute(query)).mappings().one_or_none()
        if row is None:
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
        return row

    @staticmethod
    def _snapshot(row: RowMapping, target: KnowledgeDisableTarget, actor: str) -> DisableRead:
        """停用不要求有效期或索引可用，损坏向量也不能阻碍撤回当前依据。"""

        if (
            row["publication_state"] != "PUBLISHED"
            or row["current_version_id"] != target.version_id
        ):
            raise KnowledgeManagementError("DISABLE_REQUIRES_CURRENT_PUBLISHED")
        if row["row_version"] != target.expected_row_version:
            raise KnowledgeManagementError("STALE_DOCUMENT")
        if (
            row["published_revision_no"] != target.expected_revision_no
            or row["current_revision_no"] != target.expected_revision_no
        ):
            raise KnowledgeManagementError("STALE_REVISION")
        try:
            metadata = ManagedKnowledgeMetadata.model_validate(
                {key: row[key] for key in ManagedKnowledgeMetadata.model_fields}
            )
            if (
                metadata.metadata_digest() != row["metadata_hash"]
                or metadata.specification_version != row["version_specification_version"]
            ):
                raise ValueError("published metadata does not match its identity")
            if row["published_generation_id"] is None or not isinstance(
                row["published_at"], datetime
            ):
                raise ValueError("published version must retain sealed identity")
            confirmation = ManagedKnowledgeConfirmation(
                actor_id=actor,
                action="DISABLE",
                document_id=target.document_id,
                version_id=target.version_id,
                revision_no=target.expected_revision_no,
                raw_hash=row["raw_hash"],
                normalized_hash=row["normalized_hash"],
                metadata_hash=row["metadata_hash"],
                expected_row_version=row["row_version"],
                previous_version_id=target.version_id,
                generation_id=row["published_generation_id"],
            )
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        return DisableRead(confirmation, metadata, row["published_at"])

    async def prepare_disable(
        self, target: KnowledgeDisableTarget, *, actor: str, scope: str
    ) -> DisableRead:
        """仅生成审查快照，不创建人工操作，不恢复或修改任务。"""

        async with self.database.session() as session:
            row = await self._row(
                session, target.document_id, target.version_id, target.expected_revision_no, scope
            )
            return self._snapshot(row, target, actor)

    async def _receipt(
        self, session: AsyncSession, operation: Operation, scope: str, *, replayed: bool
    ) -> KnowledgeDisableReceipt:
        """相同请求只回查原停用结果，即使该资料后来又发布了新版本。"""

        try:
            snapshot = ManagedKnowledgeConfirmation.model_validate(operation.confirmation_snapshot)
            version = await session.scalar(
                select(Version).where(Version.version_id == operation.version_id)
            )
            if (
                version is None
                or snapshot.actor_id != operation.actor_id
                or snapshot.action != "DISABLE"
                or snapshot.version_id != operation.version_id
                or snapshot.revision_no != operation.revision_no
                or snapshot.document_id != version.document_id
                or operation.state != "SUCCEEDED"
                or operation.result_id != operation.version_id
            ):
                raise ValueError("disable receipt does not match original operation")
            row = await self._row(
                session, version.document_id, operation.version_id, operation.revision_no, scope
            )
            if (
                row["publication_state"] != "DISABLED"
                or row["published_generation_id"] != snapshot.generation_id
                or row["published_revision_no"] != snapshot.revision_no
            ):
                raise ValueError("disabled version does not retain sealed identity")
            return KnowledgeDisableReceipt.model_validate(
                {
                    "operation_id": operation.operation_id,
                    "document_id": snapshot.document_id,
                    "version_id": operation.version_id,
                    "revision_no": operation.revision_no,
                    "generation_id": snapshot.generation_id,
                    "disabled_at": operation.finished_at,
                    "current_version_id": row["current_version_id"],
                    "row_version": row["row_version"],
                    "release_revision": row["release_revision"],
                    "source_mode": row["source_mode"],
                    "replayed": replayed,
                }
            )
        except KnowledgeManagementError:
            raise
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None

    async def _invalidate_pending(
        self, session: AsyncSession, document_id: str, now: datetime
    ) -> None:
        """停用是新的人工事实，旧计数上的发布/索引意图及迟到结果必须失效。"""

        ids = list(
            await session.scalars(
                select(Operation.operation_id)
                .join(Version, Version.version_id == Operation.version_id)
                .where(
                    Version.document_id == document_id,
                    Operation.action.in_(("PUBLISH", "RETRY_INDEX")),
                    Operation.state.in_(("CONFIRMED", "EXECUTING")),
                )
            )
        )
        if not ids:
            return
        tasks = (
            await session.scalars(
                select(Task)
                .where(Task.operation_id.in_(ids), Task.task_type == "INDEX")
                .order_by(Task.task_id)
                .with_for_update()
            )
        ).all()
        operations = (
            await session.scalars(
                select(Operation)
                .where(
                    Operation.operation_id.in_(ids), Operation.state.in_(("CONFIRMED", "EXECUTING"))
                )
                .order_by(Operation.operation_id)
                .with_for_update()
            )
        ).all()
        active_ids = {operation.operation_id for operation in operations}
        generations = (
            await session.scalars(
                select(Generation)
                .where(
                    Generation.generation_id.in_(
                        [
                            task.generation_id
                            for task in tasks
                            if task.operation_id in active_ids and task.generation_id is not None
                        ]
                    ),
                    Generation.state == "BUILDING",
                )
                .order_by(Generation.generation_id)
                .with_for_update()
            )
        ).all()
        for task in tasks:
            if task.operation_id in active_ids and task.state in {"QUEUED", "RUNNING"}:
                task.state, task.error_code, task.finished_at = "STALE", "STALE_INPUT", now
        for operation in operations:
            operation.state, operation.error_code, operation.finished_at = (
                "STALE",
                "STALE_INPUT",
                now,
            )
        for generation in generations:
            generation.state, generation.error_code, generation.finished_at = (
                "FAILED",
                "STALE_INPUT",
                now,
            )

    async def disable(
        self, command: KnowledgeDisableCommand, *, actor: str, scope: str
    ) -> KnowledgeDisableReceipt:
        """明确停用在同事务校验、审计、清指针及失效旧意图，重放不再次修改。"""

        async with self.database.session() as session, session.begin():
            key = hashlib.sha256(f"{actor}:DISABLE:{command.idempotency_key}".encode()).digest()
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": int.from_bytes(key[:8], "big", signed=True)},
            )
            previous = await session.scalar(
                select(Operation).where(
                    Operation.actor_id == actor,
                    Operation.action == "DISABLE",
                    Operation.idempotency_key == command.idempotency_key,
                )
            )
            input_hash = disable_request_hash(command)
            if previous is not None:
                result = await self._receipt(session, previous, scope, replayed=True)
                if previous.input_hash != input_hash:
                    raise KnowledgeManagementError("IDEMPOTENCY_CONFLICT")
                return result
            # 首次读取只验证可见性，加锁后再读，不能使用锁等待前的旧快照。
            await self._row(
                session,
                command.document_id,
                command.version_id,
                command.expected_revision_no,
                scope,
            )
            library = await session.scalar(
                select(Library).where(Library.library_id == "DEFAULT").with_for_update()
            )
            document = await session.scalar(
                select(Document)
                .where(Document.document_id == command.document_id)
                .with_for_update()
            )
            assert library is not None and document is not None
            row = await self._row(
                session,
                command.document_id,
                command.version_id,
                command.expected_revision_no,
                scope,
            )
            read = self._snapshot(row, command, actor)
            if not hmac.compare_digest(
                command.confirmation_digest, disable_digest(read.confirmation)
            ):
                raise KnowledgeManagementError("STALE_CONFIRMATION")
            if max(document.row_version, library.release_revision) == 2**63 - 1:
                raise KnowledgeManagementError("KNOWLEDGE_COUNTER_EXHAUSTED")
            now = await session.scalar(select(func.statement_timestamp()))
            if not isinstance(now, datetime):
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            await self._invalidate_pending(session, document.document_id, now)
            version = await session.get(Version, command.version_id)
            assert version is not None
            version.publication_state = "DISABLED"
            document.current_version_id, document.row_version = None, document.row_version + 1
            library.release_revision += 1
            operation_id = managed_id("OP")
            await session.execute(
                insert(Operation).values(
                    operation_id=operation_id,
                    actor_id=actor,
                    action="DISABLE",
                    version_id=command.version_id,
                    revision_no=command.expected_revision_no,
                    target_id=command.version_id,
                    idempotency_key=command.idempotency_key,
                    input_hash=input_hash,
                    confirmation_snapshot=read.confirmation.model_dump(mode="json"),
                    state="SUCCEEDED",
                    result_id=command.version_id,
                    finished_at=now,
                )
            )
            await session.flush()
            operation = await session.get(Operation, operation_id)
            assert operation is not None
            return await self._receipt(session, operation, scope, replayed=False)
