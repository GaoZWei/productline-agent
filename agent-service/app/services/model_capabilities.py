"""从校验后的进程配置生成安全的模型能力视图。"""

from app.schemas.model_capabilities import ModelCapabilitiesResponse
from app.settings import Settings

# 能力查询服务
class ModelCapabilityService:
    """隔离Settings与HTTP响应, 避免路由误返回地址或密钥。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get(self) -> ModelCapabilitiesResponse:
        """返回配置能力, 不发网络请求, 也不判断供应商是否健康。"""

        if not self._settings.model_configured:
            return ModelCapabilitiesResponse(
                configured=False,
                provider=None,
                model_name=None,
            )
        return ModelCapabilitiesResponse(
            configured=True,
            provider=self._settings.model_provider,
            model_name=self._settings.model_name,
        )
