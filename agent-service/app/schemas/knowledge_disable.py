"""停用目标、明确确认及回执，不接受自报操作者、权限或发布状态。"""

from typing import Literal, Self

from pydantic import AwareDatetime, StrictBool, field_validator, model_validator

from app.schemas.knowledge import KnowledgeSchema
from app.schemas.managed_knowledge import (
    ManagedIdentifier,
    ManagedKnowledgeMetadata,
    NonnegativeCounter,
    PositiveRevision,
    Sha256,
)
from app.schemas.managed_knowledge_processing import SafeOperationKey


class KnowledgeDisableTarget(KnowledgeSchema):
    """指定所见发布版本和计数，不能隐式停用提交时的新当前版本。"""

    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    expected_revision_no: PositiveRevision
    expected_row_version: NonnegativeCounter


class KnowledgeDisableCandidate(KnowledgeSchema):
    """供人工审查的当前发布身份和元数据，不加载正文、原件或向量。"""

    target: KnowledgeDisableTarget
    metadata: ManagedKnowledgeMetadata
    generation_id: ManagedIdentifier
    published_at: AwareDatetime
    confirmation_digest: Sha256
    action: Literal["DISABLE"] = "DISABLE"


class KnowledgeDisableCommand(KnowledgeDisableTarget):
    """确认内容与目标一起提交，停用和发布各自使用独立动作及幂等身份。"""

    confirmed: StrictBool
    confirmation_digest: Sha256
    idempotency_key: SafeOperationKey

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        """只有明确布尔true表示确认，拒绝取消或隐式转换。"""

        if not value:
            raise ValueError("explicit disable confirmation is required")
        return value


class KnowledgeDisableReceipt(KnowledgeSchema):
    """停用原结果及当前管理计数，旧键重放不清空后来发布的新版本。"""

    operation_id: ManagedIdentifier
    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    generation_id: ManagedIdentifier
    publication_state: Literal["DISABLED"] = "DISABLED"
    disabled_at: AwareDatetime
    current_version_id: ManagedIdentifier | None
    row_version: NonnegativeCounter
    release_revision: NonnegativeCounter
    source_mode: Literal["LEGACY", "MANAGED"]
    replayed: bool

    @model_validator(mode="after")
    def validate_pointer(self) -> Self:
        """首版不允许恢复已停用版本，回执不能把该版本说成当前依据。"""

        if self.current_version_id == self.version_id:
            raise ValueError("disabled version cannot remain current")
        return self
