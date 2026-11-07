"""首批纳管确认应用，原件在事务外复制，管理库整批原子提交。"""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.knowledge.catalog_import import import_digest, import_plan
from app.knowledge.import_preflight import capture_import_files, file_fingerprint
from app.knowledge.storage import KnowledgeOriginalStorage
from app.repositories.catalog_import import KnowledgeCatalogImportRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_import import (
    KnowledgeImportCandidate,
    KnowledgeImportCommand,
    KnowledgeImportReceipt,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge_processing import ManagedKnowledgeChunkRecord
from app.services.knowledge_import import KnowledgeImportPreflightService


class KnowledgeCatalogImportService:
    """没有HTTP、CLI或启动自动执行，显式人工确认后才允许纳管。"""

    def __init__(
        self,
        repository: KnowledgeCatalogImportRepository,
        preflight: KnowledgeImportPreflightService,
        storage: KnowledgeOriginalStorage,
    ) -> None:
        self.repository = repository
        self.preflight = preflight
        self.storage = storage
        self.owner_id = "catalog-import-" + uuid4().hex

    async def prepare(
        self, *, identity: BusinessIdentity, trace_id: str | None = None
    ) -> KnowledgeImportCandidate:
        """只返回可审查的16版本与绑定内容的摘要，不产生任何管理写入。"""

        report = await self.preflight.check(identity=identity, trace_id=trace_id)
        return KnowledgeImportCandidate(preflight=report, confirmation_digest=import_digest(report))

    async def confirm(
        self,
        command: KnowledgeImportCommand,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgeImportReceipt:
        """重放仍授权，初次导入在复制后重新授权，任何失败均不切换问答源。"""

        trace_id = trace_id or "trace-" + uuid4().hex
        scope = await self.preflight.authorize(identity=identity, trace_id=trace_id)
        try:
            replay = await self.repository.replay(command, actor=identity.user_id, scope=scope)
            if replay is not None:
                return replay
            try:
                source = await self.preflight.read_authorized_source(identity=identity, scope=scope)
            except KnowledgeManagementError as error:
                if error.code not in {"IMPORT_ALREADY_PRESENT", "IMPORT_TARGET_CONFLICT"}:
                    raise
                # 同键并发可能刚完成整批提交，先回查，不能把成功重放误判为新导入。
                replay = await self.repository.replay(command, actor=identity.user_id, scope=scope)
                if replay is None:
                    raise
                return replay
            report = source.report
            if (
                command.source_catalog_hash != report.source_catalog_hash
                or command.source_fingerprint != report.source_fingerprint
            ):
                raise KnowledgeManagementError("IMPORT_SOURCE_CHANGED")
            if command.expected_release_revision != report.library_release_revision:
                raise KnowledgeManagementError("STALE_LIBRARY")
            if command.confirmation_digest != import_digest(report):
                raise KnowledgeManagementError("STALE_CONFIRMATION")
            plan = import_plan(source.files, command, actor=identity.user_id, index=report.index)
            generations = {item.source_id: item.generation_id for item in plan}
            try:
                chunks = tuple(
                    ManagedKnowledgeChunkRecord(
                        generation_id=generations[chunk.document_id],
                        chunk_id=chunk.chunk_id,
                        chunk_index=chunk.chunk_index,
                        section_path=chunk.section_path,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        token_count=chunk.token_count,
                        search_document=chunk.search_document,
                        embedding=chunk.embedding,
                    )
                    for chunk in source.stored.chunks
                )
            except ValueError:
                raise KnowledgeManagementError("IMPORT_LEGACY_CHUNKS_INVALID") from None
            for item in plan:

                async def original(raw: bytes = item.raw) -> AsyncIterator[bytes]:
                    """复制已核验的原字节，不重新打开可变化的仓库文件。"""
                    yield raw

                staged = await self.storage.stage(original(), item.snapshot.original_filename)
                try:
                    await asyncio.to_thread(self.storage.commit, staged, item.snapshot.original_key)
                finally:
                    await asyncio.to_thread(self.storage.discard, staged)
                await asyncio.to_thread(
                    self.storage.read,
                    item.snapshot.original_key,
                    item.snapshot.raw_hash,
                    item.snapshot.byte_size,
                )
            after = await asyncio.to_thread(capture_import_files, self.preflight.knowledge_root)
            if file_fingerprint(after) != file_fingerprint(source.files):
                raise KnowledgeManagementError("IMPORT_SOURCE_CHANGED")
            if scope != await self.preflight.authorize(identity=identity, trace_id=trace_id):
                raise KnowledgeManagementError("PERMISSION_DENIED")
            return await self.repository.commit(
                command,
                actor=identity.user_id,
                scope=scope,
                expected_source=source.stored,
                plan=plan,
                chunks=chunks,
                index=report.index,
                owner_id=self.owner_id,
                trace_id=trace_id,
            )
        except IntegrityError:
            raise KnowledgeManagementError("KNOWLEDGE_CONFLICT") from None
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
