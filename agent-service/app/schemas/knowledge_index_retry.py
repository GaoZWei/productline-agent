"""人工索引重试的目标、确认及接收回执，不接受执行状态或重试计数。"""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator

from app.schemas.knowledge import KnowledgeSchema
from app.schemas.knowledge_publication import (
    KnowledgePublicationAcceptance,
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge import ManagedIdentifier, ManagedKnowledgeMetadata, Sha256
from app.schemas.managed_knowledge_processing import ProcessingError, SafeOperationKey

AttemptNumber = Annotated[int, Field(ge=1, le=2**63 - 1)]


class KnowledgeIndexRetryTarget(KnowledgePublicationTarget):
    """指定当前草稿及原失败任务，不能隐式选择最新任务或修订。"""

    task_id: ManagedIdentifier


class KnowledgeIndexRetryCandidate(KnowledgeSchema):
    """审查原任务的安全失败原因及索引身份，不返回供应商原始异常。"""

    target: KnowledgeIndexRetryTarget
    metadata: ManagedKnowledgeMetadata
    source_state: Literal["FAILED", "INTERRUPTED"]
    source_error_code: ProcessingError
    source_attempt_no: AttemptNumber
    source_generation_id: ManagedIdentifier
    index: KnowledgePublicationIndexIdentity
    confirmation_digest: Sha256


class KnowledgeIndexRetryCommand(KnowledgeIndexRetryTarget):
    """重试是新的人工意图，不复用原PUBLISH确认或其权限。"""

    confirmed: StrictBool
    confirmation_digest: Sha256
    idempotency_key: SafeOperationKey

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        """只接受明确布尔true，拒绝取消或字符串/数字转换。"""

        if not value:
            raise ValueError("explicit retry confirmation is required")
        return value


class KnowledgeIndexRetryReceipt(KnowledgePublicationAcceptance):
    """接收新任务或重放原状态，保留直接父任务及递增尝试号。"""

    retry_of_task_id: ManagedIdentifier
    attempt_no: AttemptNumber
