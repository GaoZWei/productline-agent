"""最终发布服务：重新授权、完整证据校验和原子切换，不自动切换问答读源。"""

import asyncio

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.knowledge.index_build import validate_index_records
from app.repositories.knowledge_publication_finalize import (
    KnowledgePublicationFinalizeRepository,
    finalization_hash,
)
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationReceipt,
)
from app.services.knowledge_management import KnowledgeManagementAuthorizer

_STALE_CODES = {
    "STALE_DOCUMENT",
    "STALE_REVISION",
    "STALE_CONFIRMATION",
    "PUBLICATION_REQUIRES_DRAFT",
    "PUBLICATION_NOT_EFFECTIVE",
    "PUBLICATION_EXPIRED",
}


class KnowledgePublicationFinalizeService:
    """仅完成已明确确认的PUBLISH操作，不接受正文、发布状态或索引路径参数。"""

    def __init__(
        self,
        repository: KnowledgePublicationFinalizeRepository,
        authorizer: KnowledgeManagementAuthorizer,
        *,
        index_identity: KnowledgePublicationIndexIdentity | None,
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer
        self.index_identity = index_identity

    async def _authorize(self, identity: BusinessIdentity, trace_id: str | None) -> str:
        """每次最终发布及成功重放都重新授权，不保存或复用旧身份凭据。"""

        response = await self.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=KnowledgeManagementAction.PUBLISH),
            identity=identity,
            trace_id=trace_id,
        )
        if (
            response.data.user_id != identity.user_id
            or response.data.action != KnowledgeManagementAction.PUBLISH
            or response.data.confirmation_required is not True
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        return response.data.permission_scope.value

    async def finalize(
        self, operation_id: str, *, identity: BusinessIdentity, trace_id: str | None = None
    ) -> KnowledgePublicationReceipt:
        """验证READY候选后再次授权，事务成功才返回发布回执，重放不重新切换。"""

        scope = await self._authorize(identity, trace_id)
        try:
            prepared = await self.repository.prepare_finalization(
                operation_id, actor=identity.user_id, scope=scope
            )
            if isinstance(prepared, KnowledgePublicationReceipt):
                return prepared
            if self.index_identity is None:
                raise KnowledgeManagementError("KNOWLEDGE_INDEX_NOT_CONFIGURED")
            if prepared.index != self.index_identity:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
            try:
                await asyncio.to_thread(validate_index_records, prepared, prepared.chunks)
                fingerprint = await asyncio.to_thread(finalization_hash, prepared)
            except ValueError:
                raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
            scope = await self._authorize(identity, trace_id)
            return await self.repository.commit_finalization(
                prepared, fingerprint, actor=identity.user_id, scope=scope
            )
        except IntegrityError:
            raise KnowledgeManagementError("KNOWLEDGE_CONFLICT") from None
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        except KnowledgeManagementError as error:
            if error.code in _STALE_CODES or error.code == "KNOWLEDGE_DATA_INVALID":
                try:
                    await self.repository.reject_finalization(
                        operation_id,
                        actor=identity.user_id,
                        scope=scope,
                        stale=error.code in _STALE_CODES,
                    )
                except SQLAlchemyError:
                    raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
            raise
