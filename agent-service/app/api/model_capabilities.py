"""模型配置能力的只读查询API。"""

from fastapi import APIRouter, Request

from app.schemas.model_capabilities import ModelCapabilitiesResponse
from app.services.model_capabilities import ModelCapabilityService

router = APIRouter(prefix="/api/agent/capabilities", tags=["agent-capabilities"])

# HTTP 查询接口
@router.get(
    "/model",
    response_model=ModelCapabilitiesResponse,
    summary="查询模型配置能力",
)
async def get_model_capabilities(request: Request) -> ModelCapabilitiesResponse:
    """返回安全配置状态, 该结果不证明模型可达或实际参与了Run。"""

    service: ModelCapabilityService = request.app.state.model_capability_service
    return service.get()
