"""重试请求的规范哈希，不把哈希当成授权或已完成发布的凭证。"""

import hashlib
import json

from app.schemas.knowledge_index_retry import KnowledgeIndexRetryCommand
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation


def index_retry_digest(confirmation: ManagedKnowledgeConfirmation) -> str:
    """审查时绑定实际用户、当前事实以及原失败任务和批次。"""

    payload = {"contract": "knowledge-index-retry-v1", **confirmation.model_dump(mode="json")}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def index_retry_request_hash(command: KnowledgeIndexRetryCommand) -> str:
    """同键重放绑定原用户输入，不因服务器配置或后续任务状态变化而排队。"""

    payload = {"contract": "knowledge-index-retry-request-v1", **command.model_dump(mode="json")}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
