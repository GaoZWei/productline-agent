"""首批演示规范整批纳管事务，保留旧表并只切换管理库内部指针。"""

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.knowledge.catalog_import import CatalogImportVersion, import_keys, import_request_hash
from app.knowledge.import_preflight import LegacyImportSnapshot
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
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeOperation as Operation,
)
from app.models.managed_knowledge_processing import (
    ManagedKnowledgeTask as Task,
)
from app.repositories.knowledge_import import KnowledgeImportPreflightRepository
from app.schemas.knowledge_import import (
    KnowledgeImportCommand,
    KnowledgeImportedVersion,
    KnowledgeImportReceipt,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge_processing import (
    ManagedKnowledgeChunkRecord,
    ManagedKnowledgeConfirmation,
)


class KnowledgeCatalogImportRepository:
    """完整成功才落审计和来源标记，事务失败不留下部分发布集合。"""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.source = KnowledgeImportPreflightRepository(database)

    async def replay(
        self, command: KnowledgeImportCommand, *, actor: str, scope: str
    ) -> KnowledgeImportReceipt | None:
        """先查成功幂等结果，旧文件或模型配置改变不应重新执行已完成导入。"""

        async with self.database.session() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            return await self._replay(session, command, actor=actor, scope=scope)

    async def _replay(
        self, session: AsyncSession, command: KnowledgeImportCommand, *, actor: str, scope: str
    ) -> KnowledgeImportReceipt | None:
        """同一批的32条UPLOAD/PUBLISH操作须完整，不能把部分记录当成功。"""

        operations = tuple(
            await session.scalars(
                select(Operation)
                .where(
                    Operation.actor_id == actor,
                    Operation.action.in_(("UPLOAD", "PUBLISH")),
                    Operation.idempotency_key.in_(import_keys(command)),
                )
                .order_by(Operation.idempotency_key, Operation.action)
            )
        )
        if not operations:
            return None
        if any(item.input_hash != import_request_hash(command) for item in operations):
            raise KnowledgeManagementError("IDEMPOTENCY_CONFLICT")
        if len(operations) != 32 or any(item.state != "SUCCEEDED" for item in operations):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        rows = (
            await session.execute(
                select(Version, Revision)
                .join(
                    Revision,
                    (Revision.version_id == Version.version_id) & (Revision.revision_no == 1),
                )
                .where(
                    Version.version_id.in_({item.version_id for item in operations}),
                    Revision.permission_scope == scope,
                )
            )
        ).all()
        versions = {version.version_id: (version, revision) for version, revision in rows}
        if len(versions) != 16:
            raise KnowledgeManagementError("PERMISSION_DENIED")
        tasks = {
            item.operation_id: item
            for item in await session.scalars(
                select(Task).where(
                    Task.operation_id.in_({item.operation_id for item in operations})
                )
            )
        }
        if len(tasks) != 32 or any(item.state != "SUCCEEDED" for item in tasks.values()):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        entries: list[KnowledgeImportedVersion] = []
        times = set()
        for operation in operations:
            version, revision = versions[operation.version_id]
            try:
                snapshot = ManagedKnowledgeConfirmation.model_validate(
                    operation.confirmation_snapshot
                )
            except ValueError:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
            if (
                version.source_kind != "CATALOG_IMPORT"
                or version.source_catalog_hash != command.source_catalog_hash
                or version.source_document_id is None
                or snapshot.actor_id != actor
                or snapshot.action != operation.action
                or snapshot.document_id != version.document_id
                or snapshot.version_id != version.version_id
                or snapshot.raw_hash != revision.raw_hash
                or snapshot.metadata_hash != revision.metadata_hash
                or operation.result_id != version.version_id
            ):
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            task = tasks[operation.operation_id]
            if operation.action == "UPLOAD":
                if task.task_type != "PARSE":
                    raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
                continue
            if snapshot.generation_id is None or task.generation_id != snapshot.generation_id:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            times.add(operation.finished_at)
            entries.append(
                KnowledgeImportedVersion(
                    source_document_id=version.source_document_id,
                    document_id=version.document_id,
                    version_id=version.version_id,
                    generation_id=snapshot.generation_id,
                    operation_id=operation.operation_id,
                    task_id=task.task_id,
                    imported_state="PUBLISHED"
                    if version.source_lifecycle == "ACTIVE"
                    else "HISTORICAL",
                )
            )
        library = await session.get(Library, "DEFAULT")
        if (
            library is None
            or library.source_catalog_hash != command.source_catalog_hash
            or len(entries) != 16
            or len(times) != 1
            or None in times
        ):
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        imported_at = times.pop()
        assert imported_at is not None
        return KnowledgeImportReceipt(
            source_catalog_hash=command.source_catalog_hash,
            source_fingerprint=command.source_fingerprint,
            imported_by=actor,
            imported_at=imported_at,
            import_release_revision=command.expected_release_revision + 1,
            current_release_revision=library.release_revision,
            replayed=True,
            versions=tuple(entries),
        )

    async def commit(
        self,
        command: KnowledgeImportCommand,
        *,
        actor: str,
        scope: str,
        expected_source: LegacyImportSnapshot,
        plan: tuple[CatalogImportVersion, ...],
        chunks: tuple[ManagedKnowledgeChunkRecord, ...],
        index: KnowledgePublicationIndexIdentity,
        owner_id: str,
        trace_id: str,
    ) -> KnowledgeImportReceipt:
        """源表锁防旧CLI改写，库锁防另一批导入或发布，与最终写入同事务。"""

        async with self.database.session() as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await session.execute(
                text("LOCK TABLE knowledge_documents, knowledge_chunks IN SHARE MODE")
            )
            library = await session.scalar(
                select(Library).where(Library.library_id == "DEFAULT").with_for_update()
            )
            if library is None:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            replayed = await self._replay(session, command, actor=actor, scope=scope)
            if replayed is not None:
                return replayed
            if library.source_catalog_hash is not None:
                raise KnowledgeManagementError(
                    "IMPORT_ALREADY_PRESENT"
                    if library.source_catalog_hash == command.source_catalog_hash
                    else "IMPORT_SOURCE_CONFLICT"
                )
            if library.release_revision != command.expected_release_revision:
                raise KnowledgeManagementError("STALE_LIBRARY")
            current = await self.source.read_in_session(
                session, tuple(item.source_id for item in plan), scope
            )
            if current != expected_source:
                raise KnowledgeManagementError("IMPORT_SOURCE_CHANGED")
            now = await session.scalar(select(func.now()))
            assert now is not None
            document_ids = sorted({item.document_id for item in plan})
            await session.execute(
                insert(Document),
                [
                    dict(document_id=identifier, created_by=actor, created_at=now, row_version=1)
                    for identifier in document_ids
                ],
            )
            await session.execute(
                insert(Version),
                [
                    dict(
                        version_id=item.version_id,
                        document_id=item.document_id,
                        specification_version=item.snapshot.specification_version,
                        citation_document_id=item.source_id,
                        source_kind="CATALOG_IMPORT",
                        source_document_id=item.source_id,
                        source_catalog_hash=command.source_catalog_hash,
                        source_lifecycle=item.lifecycle,
                        source_replaced_by=item.replaced_by,
                        created_by=actor,
                        created_at=now,
                    )
                    for item in plan
                ],
            )
            await session.execute(
                insert(Revision),
                [
                    dict(
                        **item.snapshot.model_dump(),
                        metadata_hash=item.snapshot.metadata_digest(),
                        created_at=now,
                    )
                    for item in plan
                ],
            )
            await session.execute(
                insert(Generation),
                [
                    dict(
                        generation_id=item.generation_id,
                        version_id=item.version_id,
                        revision_no=1,
                        embedding_provider=index.provider,
                        embedding_model=index.model,
                        embedding_dimension=index.dimension,
                        index_version=index.index_version,
                        chunking_version=index.chunking_version,
                        input_hash=item.generation_hash,
                        build_method="COPIED_LEGACY",
                        state="READY",
                        chunk_count=sum(
                            chunk.generation_id == item.generation_id for chunk in chunks
                        ),
                        created_at=now,
                        finished_at=now,
                    )
                    for item in plan
                ],
            )
            await session.execute(insert(Chunk), [item.model_dump(mode="json") for item in chunks])
            for item in plan:
                for action, operation_id, task_id, task_type in (
                    ("UPLOAD", item.upload_operation_id, item.parse_task_id, "PARSE"),
                    ("PUBLISH", item.publish_operation_id, item.index_task_id, "INDEX"),
                ):
                    await session.execute(
                        insert(Operation).values(
                            operation_id=operation_id,
                            actor_id=actor,
                            action=action,
                            version_id=item.version_id,
                            revision_no=1,
                            target_id=item.version_id,
                            idempotency_key=item.operation_key,
                            input_hash=import_request_hash(command),
                            confirmation_snapshot=item.confirmation(actor, action).model_dump(
                                mode="json"
                            ),
                            state="SUCCEEDED",
                            result_id=item.version_id,
                            created_at=now,
                            finished_at=now,
                        )
                    )
                    await session.execute(
                        insert(Task).values(
                            task_id=task_id,
                            operation_id=operation_id,
                            operation_action=action,
                            version_id=item.version_id,
                            revision_no=1,
                            task_type=task_type,
                            generation_id=item.generation_id if action == "PUBLISH" else None,
                            state="SUCCEEDED",
                            owner_id=owner_id,
                            trace_id=trace_id,
                            created_at=now,
                            started_at=now,
                            finished_at=now,
                        )
                    )
                await session.execute(
                    update(Version)
                    .where(Version.version_id == item.version_id)
                    .values(
                        publication_state="PUBLISHED"
                        if item.lifecycle == "ACTIVE"
                        else "HISTORICAL",
                        published_revision_no=1,
                        published_generation_id=item.generation_id,
                        published_at=now if item.lifecycle == "ACTIVE" else None,
                    )
                )
                if item.lifecycle == "ACTIVE":
                    await session.execute(
                        update(Document)
                        .where(Document.document_id == item.document_id)
                        .values(current_version_id=item.version_id)
                    )
            library.source_catalog_hash = command.source_catalog_hash
            library.release_revision += 1
            await session.flush()
            receipt = await self._replay(session, command, actor=actor, scope=scope)
            assert receipt is not None
            return receipt.model_copy(update={"replayed": False})
