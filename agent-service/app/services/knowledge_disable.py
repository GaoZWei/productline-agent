"""停用审查与明确确认入口，仅修改管理库，不恢复旧版或操作模型。"""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.knowledge.disable import disable_digest
from app.repositories.knowledge_disable import KnowledgeDisableRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_disable import (
    KnowledgeDisableCandidate,
    KnowledgeDisableCommand,
    KnowledgeDisableReceipt,
    KnowledgeDisableTarget,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.services.knowledge_management import KnowledgeManagementAuthorizer


class KnowledgeDisableService:
    """每次审查、停用及重放均查Java DISABLE权限，确认内容来自当前知识事实。"""

    def __init__(
        self, repository: KnowledgeDisableRepository, authorizer: KnowledgeManagementAuthorizer
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer

    async def _authorize(self, identity: BusinessIdentity, trace_id: str | None) -> str:
        """外部授权不持有知识事务，策略标识不等于用户已确认。"""

        response = await self.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=KnowledgeManagementAction.DISABLE),
            identity=identity,
            trace_id=trace_id,
        )
        if (
            response.data.user_id != identity.user_id
            or response.data.action != KnowledgeManagementAction.DISABLE
            or response.data.confirmation_required is not True
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        return response.data.permission_scope.value

    async def prepare(
        self,
        target: KnowledgeDisableTarget,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgeDisableCandidate:
        """返回指定当前发布版本的审查信息，不将浏览记成停用操作。"""

        scope = await self._authorize(identity, trace_id)
        try:
            read = await self.repository.prepare_disable(
                target, actor=identity.user_id, scope=scope
            )
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        assert read.confirmation.generation_id is not None
        return KnowledgeDisableCandidate(
            target=target,
            metadata=read.metadata,
            generation_id=read.confirmation.generation_id,
            published_at=read.published_at,
            confirmation_digest=disable_digest(read.confirmation),
        )

    async def disable(
        self,
        command: KnowledgeDisableCommand,
        *,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> KnowledgeDisableReceipt:
        """当前身份重新授权后接收明确停用，同键重放仍授权但不重复清指针。"""

        scope = await self._authorize(identity, trace_id)
        try:
            return await self.repository.disable(command, actor=identity.user_id, scope=scope)
        except IntegrityError:
            raise KnowledgeManagementError("KNOWLEDGE_CONFLICT") from None
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
