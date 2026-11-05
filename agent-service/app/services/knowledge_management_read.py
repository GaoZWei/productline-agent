"""只读管理查询先请求Java授权，随后读取知识自有数据，不激活处理服务。"""

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ToolErrorCode, ToolException
from app.repositories.knowledge_management_read import KnowledgeManagementReadRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_management_read import KnowledgeReadQuery, KnowledgeReadResult
from app.services.knowledge_management import KnowledgeManagementAuthorizer


class KnowledgeReadAccessError(Exception):
    """HTTP层只读取稳定码、固定文案和受控状态码。"""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(code)


class KnowledgeManagementReadService:
    """每次查询重新授权，响应不可授予写权限，也不缓存授权。"""

    def __init__(
        self,
        repository: KnowledgeManagementReadRepository,
        authorizer: KnowledgeManagementAuthorizer,
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer

    async def query(
        self, query: KnowledgeReadQuery, *, identity: BusinessIdentity, trace_id: str | None = None
    ) -> KnowledgeReadResult:
        """Java失败不打开SQL事务, 知识不存在及范围不匹配统一返回404。"""

        try:
            response = await self.authorizer.authorize(
                KnowledgeAuthorizationRequest(action=KnowledgeManagementAction.READ),
                identity=identity,
                trace_id=trace_id,
            )
        except ToolException as error:
            if error.code == ToolErrorCode.PERMISSION_DENIED:
                status = 401 if error.status_code == 401 else 403
                raise KnowledgeReadAccessError(
                    "PERMISSION_DENIED", "knowledge read permission denied", status
                ) from None
            if error.code == ToolErrorCode.TOOL_TIMEOUT:
                raise KnowledgeReadAccessError(
                    "AUTHORIZATION_TIMEOUT", "knowledge authorization timed out", 504
                ) from None
            raise KnowledgeReadAccessError(
                "AUTHORIZATION_UNAVAILABLE", "knowledge authorization is unavailable", 502
            ) from None
        if (
            response.data.user_id != identity.user_id
            or response.data.action != KnowledgeManagementAction.READ
            or response.data.confirmation_required
        ):
            raise KnowledgeReadAccessError(
                "INVALID_AUTHORIZATION_RESPONSE", "invalid knowledge authorization response", 502
            )
        try:
            return await self.repository.query(query, response.data.permission_scope.value)
        except KnowledgeManagementError:
            raise KnowledgeReadAccessError(
                "RESOURCE_NOT_FOUND", "knowledge resource not found", 404
            ) from None
        except (SQLAlchemyError, ValidationError):
            raise KnowledgeReadAccessError(
                "KNOWLEDGE_READ_UNAVAILABLE", "knowledge data is unavailable", 503
            ) from None
