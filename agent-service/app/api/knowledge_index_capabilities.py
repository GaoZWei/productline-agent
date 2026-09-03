"""知识索引就绪状态的只读查询API。"""

from fastapi import APIRouter, Request

from app.repositories import KnowledgeIndexRepository
from app.schemas.knowledge_index import KnowledgeIndexCapabilitiesResponse
from app.services.knowledge_index_capabilities import KnowledgeIndexCapabilityService

router = APIRouter(prefix="/api/agent/capabilities", tags=["agent-capabilities"])


@router.get(
    "/knowledge-index",
    response_model=KnowledgeIndexCapabilitiesResponse,
    summary="查询知识索引就绪能力",
)
async def get_knowledge_index_capabilities(
    request: Request,
) -> KnowledgeIndexCapabilitiesResponse:
    """读取数据库统计并与当前目录和Embedding配置比较, 不访问外部Provider。"""

    service: KnowledgeIndexCapabilityService = request.app.state.knowledge_index_capability_service
    database = request.app.state.database
    async with database.session() as session:
        return await service.get(KnowledgeIndexRepository(session))


__all__ = ["router"]
