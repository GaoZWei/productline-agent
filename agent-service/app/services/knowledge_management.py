"""知识原件上传、草稿修订和确定性解析，不发布、不生成向量或写业务事实。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterable
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.knowledge.managed_parsing import ParsedKnowledgeRevision, parse_managed_revision
from app.knowledge.storage import KnowledgeOriginalStorage
from app.repositories.managed_knowledge import ManagedKnowledgeRepository, managed_id
from app.schemas.business import BusinessIdentity, BusinessResponse
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeAuthorizationResponse,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_management import (
    KnowledgeManagementError,
    KnowledgeOriginalFile,
    KnowledgePreview,
    KnowledgePreviewChunk,
    KnowledgeUploadCommand,
    KnowledgeUploadResult,
)
from app.schemas.managed_knowledge import ManagedKnowledgeMetadata, ManagedKnowledgeRevisionSnapshot

_LOGGER = logging.getLogger(__name__)


class KnowledgeManagementAuthorizer(Protocol):
    """复用Java授权Client，授权期间不持有知识事务或写入原件。"""

    async def authorize(
        self,
        request: KnowledgeAuthorizationRequest,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> BusinessResponse[KnowledgeAuthorizationResponse]: ...


class KnowledgeRevisionParser(Protocol):
    """解析器只接收不可变原始输入，不能自行保存结果或执行模型。"""

    def __call__(
        self, raw: bytes, *, citation_document_id: str, title: str, file_format: str
    ) -> ParsedKnowledgeRevision: ...


class KnowledgeManagementService:
    """单实例管理服务，构造不触发SQL、文件创建或Java调用。"""

    def __init__(
        self,
        repository: ManagedKnowledgeRepository,
        storage: KnowledgeOriginalStorage,
        authorizer: KnowledgeManagementAuthorizer,
        *,
        parser: KnowledgeRevisionParser = parse_managed_revision,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.authorizer = authorizer
        self.parser = parser
        self.owner_id = managed_id("WORKER")
        self._started = False
        self._start_lock = asyncio.Lock()
        self._upload_lock = asyncio.Lock()

    async def start(self) -> None:
        """显式激活管理服务时恢复中断状态，不领取旧任务或访问外部模型。"""

        async with self._start_lock:
            if not self._started:
                try:
                    await self.repository.recover_interrupted(self.owner_id)
                except SQLAlchemyError:
                    raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
                self._started = True

    async def _authorize(
        self, action: KnowledgeManagementAction, identity: BusinessIdentity, trace_id: str | None
    ) -> tuple[str, str]:
        """角色授权来自Java，响应策略和操作者绑定不能由应用调用方指定。"""

        response = await self.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=action), identity=identity, trace_id=trace_id
        )
        if (
            response.data.user_id != identity.user_id
            or response.data.action != action
            or response.data.confirmation_required is not (action != KnowledgeManagementAction.READ)
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        return response.data.permission_scope.value, response.trace_id

    async def upload(
        self,
        command: KnowledgeUploadCommand,
        chunks: AsyncIterable[bytes],
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgeUploadResult:
        """人工上传提交只接收草稿，解析结果与成功接收的操作分开保存。"""

        scope, actual_trace = await self._authorize(
            KnowledgeManagementAction.UPLOAD, identity, trace_id
        )
        if command.metadata.permission_scope.value != scope:
            raise KnowledgeManagementError("PERMISSION_DENIED")
        async with self._upload_lock:
            await self.start()
            staged = await self.storage.stage(chunks, command.filename)
            try:
                payload = {
                    "command": command.model_dump(mode="json"),
                    "raw_hash": staged.raw_hash,
                    "byte_size": staged.byte_size,
                }
                input_hash = hashlib.sha256(
                    json.dumps(
                        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                result = await self.repository.find_upload(
                    identity.user_id, command.idempotency_key, input_hash
                )
                if result is None:
                    plan = await self.repository.plan_upload(command)
                    suffix = "md" if staged.file_format == "MD" else "txt"
                    key = (
                        f"versions/{plan.version_id}/revisions/{plan.revision_no}/original.{suffix}"
                    )
                    self.storage.commit(staged, key)
                    snapshot = ManagedKnowledgeRevisionSnapshot(
                        **command.metadata.model_dump(),
                        version_id=plan.version_id,
                        revision_no=plan.revision_no,
                        original_key=key,
                        original_filename=command.filename,
                        file_format=staged.file_format,
                        byte_size=staged.byte_size,
                        raw_hash=staged.raw_hash,
                        created_by=identity.user_id,
                    )
                    result = await self.repository.accept_upload(
                        command,
                        plan,
                        snapshot,
                        actor=identity.user_id,
                        input_hash=input_hash,
                        trace_id=actual_trace,
                        owner_id=self.owner_id,
                    )
                if result.task_state == "QUEUED":
                    await self.process_parse(result.task_id)
                return await self.repository.upload_result(
                    result.operation_id, replayed=result.replayed
                )
            except IntegrityError:
                raise KnowledgeManagementError("KNOWLEDGE_CONFLICT") from None
            except SQLAlchemyError:
                # 原件已经提交时保留为未引用文件，不假装文件系统与数据库能够原子回滚。
                raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
            finally:
                try:
                    self.storage.discard(staged)
                except KnowledgeManagementError:
                    _LOGGER.warning(
                        "knowledge_temporary_cleanup_failed",
                        extra={"trace_id": actual_trace, "error_code": "STORAGE_ERROR"},
                    )

    async def process_parse(self, task_id: str) -> bool:
        """内部确定性处理入口，只领取当前owner的任务，不是对外重试接口。"""

        record = await self.repository.claim_parse(task_id, self.owner_id)
        if record is None:
            return False
        snapshot = record.snapshot
        try:
            raw = self.storage.read(snapshot.original_key, snapshot.raw_hash, snapshot.byte_size)
        except KnowledgeManagementError:
            return await self.repository.finish_parse(
                task_id, self.owner_id, error_code="STORAGE_ERROR"
            )
        try:
            parsed = await asyncio.to_thread(
                self.parser,
                raw,
                citation_document_id=record.citation_document_id,
                title=snapshot.title,
                file_format=snapshot.file_format,
            )
            ManagedKnowledgeRevisionSnapshot.model_validate(
                {
                    **snapshot.model_dump(),
                    "body": parsed.body,
                    "normalized_hash": parsed.normalized_hash,
                }
            )
            if not parsed.chunks:
                raise ValueError("parsed revision requires preview chunks")
        except Exception:
            return await self.repository.finish_parse(
                task_id, self.owner_id, error_code="PARSE_FAILED"
            )
        return await self.repository.finish_parse(
            task_id, self.owner_id, body=parsed.body, normalized_hash=parsed.normalized_hash
        )

    async def preview(
        self,
        version_id: str,
        revision_no: int,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgePreview:
        """读取正文及分块前独立检查READ权限，结果绑定具体修订和资料版本。"""

        scope, _ = await self._authorize(KnowledgeManagementAction.READ, identity, trace_id)
        await self.start()
        try:
            record = await self.repository.read_revision(version_id, revision_no, scope)
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        snapshot = record.snapshot
        if snapshot.body is None:
            raise KnowledgeManagementError("PREVIEW_NOT_READY")
        try:
            parsed = parse_managed_revision(
                snapshot.body.encode(),
                citation_document_id=record.citation_document_id,
                title=snapshot.title,
                file_format=snapshot.file_format,
            )
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        metadata = ManagedKnowledgeMetadata.model_validate(
            snapshot.model_dump(include=set(ManagedKnowledgeMetadata.model_fields)),
        )
        return KnowledgePreview(
            document_id=record.document_id,
            version_id=version_id,
            revision_no=revision_no,
            row_version=record.row_version,
            is_current_revision=record.current_revision_no == revision_no,
            metadata=metadata,
            body=parsed.body,
            chunks=tuple(
                KnowledgePreviewChunk(
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    section_path=chunk.section_path,
                    content=chunk.content,
                )
                for chunk in parsed.chunks
            ),
        )

    async def read_original(
        self,
        version_id: str,
        revision_no: int,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgeOriginalFile:
        """原件读取独立验证READ与范围，不接收文件key或使用仓库正文兜底。"""

        scope, _ = await self._authorize(KnowledgeManagementAction.READ, identity, trace_id)
        await self.start()
        try:
            record = await self.repository.read_revision(version_id, revision_no, scope)
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        snapshot = record.snapshot
        raw = self.storage.read(snapshot.original_key, snapshot.raw_hash, snapshot.byte_size)
        return KnowledgeOriginalFile(filename=snapshot.original_filename, content=raw)
