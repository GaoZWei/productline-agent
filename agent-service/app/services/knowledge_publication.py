"""发布候选、确认校验及接收预留，不构建向量或切换发布指针。"""

import asyncio
import hmac

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.knowledge.managed_parsing import ParsedKnowledgeRevision, parse_managed_revision
from app.knowledge.publication import publication_confirmation, publication_digest
from app.repositories.managed_knowledge import (
    ManagedKnowledgeRepository,
    PublicationRead,
    managed_id,
)
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_management import (
    KnowledgeManagementError,
    KnowledgePreview,
    KnowledgePreviewChunk,
)
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationCandidate,
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge import ManagedKnowledgeMetadata
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation
from app.services.knowledge_management import KnowledgeManagementAuthorizer


class KnowledgePublicationService:
    """连接Java授权、知识快照及接收事务，最终发布仍需再次授权和事务复核。"""

    def __init__(
        self,
        repository: ManagedKnowledgeRepository,
        authorizer: KnowledgeManagementAuthorizer,
        *,
        index_identity: KnowledgePublicationIndexIdentity | None = None,
        owner_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer
        self.index_identity = index_identity
        self.owner_id = owner_id or managed_id("WORKER")

    async def _authorize(self, identity: BusinessIdentity, trace_id: str | None) -> tuple[str, str]:
        """每次接收或重放都先查询Java，不在SQL事务内调用外部服务。"""

        response = await self.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=KnowledgeManagementAction.PUBLISH),
            identity=identity,
            trace_id=trace_id,
        )
        authorization = response.data
        if (
            authorization.user_id != identity.user_id
            or authorization.action != KnowledgeManagementAction.PUBLISH
            or authorization.confirmation_required is not True
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        return authorization.permission_scope.value, response.trace_id

    async def _candidate(
        self,
        target: KnowledgePublicationTarget,
        identity: BusinessIdentity,
        trace_id: str | None,
    ) -> tuple[PublicationRead, ManagedKnowledgeConfirmation, ParsedKnowledgeRevision]:
        """先授权再读取及分块，审查与事务复核共享确定性候选规则。"""

        scope, _ = await self._authorize(identity, trace_id)
        try:
            record = await self.repository.read_publication_candidate(
                target.document_id,
                target.version_id,
                target.expected_revision_no,
                scope,
            )
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        revision = record.revision
        snapshot = revision.snapshot
        confirmation = publication_confirmation(record, target, identity.user_id)
        assert snapshot.body is not None
        try:
            parsed = await asyncio.to_thread(
                parse_managed_revision,
                snapshot.body.encode(),
                citation_document_id=revision.citation_document_id,
                title=snapshot.title,
                file_format=snapshot.file_format,
            )
        except ValueError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        return record, confirmation, parsed

    async def prepare(
        self,
        target: KnowledgePublicationTarget,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgePublicationCandidate:
        """生成待审查内容，不把浏览候选记为已确认人工操作。"""

        record, confirmation, parsed = await self._candidate(target, identity, trace_id)
        revision = record.revision
        snapshot = revision.snapshot
        return KnowledgePublicationCandidate(
            preview=KnowledgePreview(
                document_id=target.document_id,
                version_id=target.version_id,
                revision_no=target.expected_revision_no,
                row_version=revision.row_version,
                is_current_revision=True,
                metadata=ManagedKnowledgeMetadata.model_validate(
                    snapshot.model_dump(include=set(ManagedKnowledgeMetadata.model_fields))
                ),
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
            ),
            previous_version_id=record.previous_version_id,
            confirmation_digest=publication_digest(confirmation),
        )

    async def validate_confirmation(
        self,
        command: KnowledgePublicationConfirmCommand,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> ManagedKnowledgeConfirmation:
        """再次授权和重建事实后比对摘要，返回内部快照，不表示已持久化或预留执行权。"""

        _, confirmation, _ = await self._candidate(command, identity, trace_id)
        if not hmac.compare_digest(command.confirmation_digest, publication_digest(confirmation)):
            raise KnowledgeManagementError("STALE_CONFIRMATION")
        return confirmation

    async def accept(
        self,
        command: KnowledgePublicationConfirmCommand,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgePublicationAcceptance:
        """明确确认后原子接收并预留，幂等返回原状态，不启动索引或发布执行。"""

        scope, actual_trace = await self._authorize(identity, trace_id)
        try:
            return await self.repository.accept_publication(
                command,
                actor=identity.user_id,
                scope=scope,
                index=self.index_identity,
                trace_id=actual_trace,
                owner_id=self.owner_id,
            )
        except IntegrityError:
            raise KnowledgeManagementError("KNOWLEDGE_CONFLICT") from None
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
