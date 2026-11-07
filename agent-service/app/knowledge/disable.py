"""停用确认的规范摘要，哈希只绑定内容，不授予权限。"""

import hashlib
import json

from app.schemas.knowledge_disable import KnowledgeDisableCommand
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation


def disable_digest(confirmation: ManagedKnowledgeConfirmation) -> str:
    """服务端事实绑定实际确认人、版本和已发布批次，不与PUBLISH摘要混用。"""

    payload = {"contract": "knowledge-disable-v1", **confirmation.model_dump(mode="json")}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def disable_request_hash(command: KnowledgeDisableCommand) -> str:
    """重放绑定原用户请求，不把服务器当前状态变化当作新的停用输入。"""

    payload = {"contract": "knowledge-disable-request-v1", **command.model_dump(mode="json")}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
