"""索引失败任务的人工重试确认，不自动运行模型或复用旧发布授权。"""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.knowledge.index_retry import index_retry_digest
from app.repositories.knowledge_index_retry import KnowledgeIndexRetryRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_index_retry import (
    KnowledgeIndexRetryCandidate,
    KnowledgeIndexRetryCommand,
    KnowledgeIndexRetryReceipt,
    KnowledgeIndexRetryTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge import ManagedKnowledgeMetadata
from app.services.knowledge_management import KnowledgeManagementAuthorizer


class KnowledgeIndexRetryService:
    """每次审查、提交及重放均查RETRY_INDEX权限，新意图与原失败审计分开。"""

    def __init__(
        self,
        repository: KnowledgeIndexRetryRepository,
        authorizer: KnowledgeManagementAuthorizer,
        *,
        index_identity: KnowledgePublicationIndexIdentity | None,
        owner_id: str,
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer
        self.index_identity = index_identity
        self.owner_id = owner_id

    async def _authorize(self, identity: BusinessIdentity, trace_id: str | None) -> tuple[str, str]:
        """授权HTTP在知识事务外，原PUBLISH权限及Token不保存、不继承。"""

        response = await self.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=KnowledgeManagementAction.RETRY_INDEX),
            identity=identity,
            trace_id=trace_id,
        )
        if (
            response.data.user_id != identity.user_id
            or response.data.action != KnowledgeManagementAction.RETRY_INDEX
            or response.data.confirmation_required is not True
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        return response.data.permission_scope.value, response.trace_id

    async def prepare(
        self,
        target: KnowledgeIndexRetryTarget,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgeIndexRetryCandidate:
        """只审查当前草稿的失败链尾，不创建任务、恢复进程或调用模型。"""

        scope, _ = await self._authorize(identity, trace_id)
        if self.index_identity is None:
            raise KnowledgeManagementError("KNOWLEDGE_INDEX_NOT_CONFIGURED")
        try:
            read = await self.repository.prepare_retry(
                target, actor=identity.user_id, scope=scope, index=self.index_identity
            )
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        assert read.source.error_code is not None and read.source.generation_id is not None
        return KnowledgeIndexRetryCandidate(
            target=target,
            metadata=ManagedKnowledgeMetadata.model_validate(
                read.record.revision.snapshot.model_dump(
                    include=set(ManagedKnowledgeMetadata.model_fields)
                )
            ),
            source_state="FAILED" if read.source.state == "FAILED" else "INTERRUPTED",
            source_error_code=read.source.error_code,
            source_attempt_no=read.source.attempt_no,
            source_generation_id=read.source.generation_id,
            index=read.index,
            confirmation_digest=index_retry_digest(read.confirmation),
        )

    async def retry(
        self,
        command: KnowledgeIndexRetryCommand,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgeIndexRetryReceipt:
        """保存独立重试意图及新批次/任务，同键重放只返回原状态，不再次运行。"""

        scope, actual_trace = await self._authorize(identity, trace_id)
        try:
            return await self.repository.accept_retry(
                command,
                actor=identity.user_id,
                scope=scope,
                index=self.index_identity,
                owner_id=self.owner_id,
                trace_id=actual_trace,
            )
        except IntegrityError:
            raise KnowledgeManagementError("KNOWLEDGE_CONFLICT") from None
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
