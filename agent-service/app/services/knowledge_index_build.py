"""确定性候选索引执行：授权、短事务领取、事务外向量生成与完整保存。"""

import asyncio
import logging
import math

from sqlalchemy.exc import SQLAlchemyError

from app.errors import ToolErrorCode, ToolException
from app.knowledge.embeddings import EmbeddingErrorCode, EmbeddingProviderError
from app.knowledge.index_build import index_chunk_records, parse_index_input
from app.repositories.knowledge_index_build import KnowledgeIndexBuildRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge_processing import ProcessingError
from app.services.knowledge_ingestion import KnowledgeEmbeddingGenerator
from app.services.knowledge_management import KnowledgeManagementAuthorizer

_LOGGER = logging.getLogger(__name__)


class KnowledgeIndexBuildService:
    """执行服务端选定的PUBLISH或RETRY_INDEX任务，不自动轮询、排重试或发布。"""

    def __init__(
        self,
        repository: KnowledgeIndexBuildRepository,
        authorizer: KnowledgeManagementAuthorizer,
        generator: KnowledgeEmbeddingGenerator,
        *,
        index_identity: KnowledgePublicationIndexIdentity,
        owner_id: str,
        timeout_seconds: float = 120,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
            raise ValueError("index build timeout must be positive and at most 600 seconds")
        self.repository = repository
        self.authorizer = authorizer
        self.generator = generator
        self.index_identity = index_identity
        self.owner_id = owner_id
        self.timeout_seconds = timeout_seconds
        self.action = KnowledgeManagementAction(repository.operation_action)
        if self.action not in {
            KnowledgeManagementAction.PUBLISH,
            KnowledgeManagementAction.RETRY_INDEX,
        }:
            raise ValueError("index builder requires publish or retry action")

    async def _authorize(self, identity: BusinessIdentity, trace_id: str | None) -> str:
        """每次执行及保存前均经Java授权，不缓存身份或在SQL事务内等待HTTP。"""

        response = await self.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=self.action),
            identity=identity,
            trace_id=trace_id,
        )
        if (
            response.data.user_id != identity.user_id
            or response.data.action != self.action
            or response.data.confirmation_required is not True
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        return response.data.permission_scope.value

    async def _fail(self, task_id: str, actor: str, error: ProcessingError) -> bool:
        """只保存白名单错误，底层异常由调用边界统一脱敏。"""

        return await self.repository.fail_index(
            task_id, actor=actor, owner_id=self.owner_id, error_code=error
        )

    async def process(
        self, task_id: str, *, identity: BusinessIdentity, trace_id: str | None = None
    ) -> bool:
        """成功仅表示候选READY，失败或不能领取返回false，数据库不可用明确抛错。"""

        scope = await self._authorize(identity, trace_id)
        try:
            claim = await self.repository.claim_index(
                task_id,
                actor=identity.user_id,
                scope=scope,
                owner_id=self.owner_id,
                index=self.index_identity,
            )
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        if claim is None:
            return False
        error: ProcessingError
        try:
            async with asyncio.timeout(self.timeout_seconds):
                parsed = await asyncio.to_thread(parse_index_input, claim)
                generated = await self.generator.generate(parsed.chunks)
                records = await asyncio.to_thread(index_chunk_records, claim, parsed, generated)
            scope = await self._authorize(identity, trace_id)
            return await self.repository.finish_index(
                claim, records, scope=scope, owner_id=self.owner_id
            )
        except asyncio.CancelledError:
            try:
                await asyncio.shield(
                    self._fail(task_id, identity.user_id, "PROCESSING_INTERRUPTED")
                )
            except SQLAlchemyError:
                _LOGGER.warning(
                    "knowledge_index_cancel_cleanup_failed",
                    extra={"error_code": "PROCESSING_INTERRUPTED"},
                )
            raise
        except TimeoutError:
            error = "TOOL_TIMEOUT"
        except EmbeddingProviderError as exception:
            if exception.code == EmbeddingErrorCode.TIMEOUT:
                error = "TOOL_TIMEOUT"
            elif exception.code == EmbeddingErrorCode.INVALID_RESPONSE:
                error = "INDEX_VALIDATION_FAILED"
            elif exception.code == EmbeddingErrorCode.INVALID_REQUEST:
                error = "INDEX_BUILD_FAILED"
            else:
                error = "UPSTREAM_UNAVAILABLE"
        except ToolException as exception:
            if exception.code == ToolErrorCode.PERMISSION_DENIED:
                error = "PERMISSION_DENIED"
            elif exception.code == ToolErrorCode.TOOL_TIMEOUT:
                error = "TOOL_TIMEOUT"
            else:
                error = "UPSTREAM_UNAVAILABLE"
        except ValueError:
            error = "INDEX_VALIDATION_FAILED"
        except SQLAlchemyError:
            try:
                await self._fail(task_id, identity.user_id, "INDEX_BUILD_FAILED")
            except SQLAlchemyError:
                pass
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        except Exception:
            error = "INDEX_BUILD_FAILED"
        try:
            await self._fail(task_id, identity.user_id, error)
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        return False
