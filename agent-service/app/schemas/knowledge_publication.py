"""发布候选与明确确认契约，不允许调用方指定操作者、状态、正文或原件路径。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from pydantic import AwareDatetime, StrictBool, field_validator, model_validator

from app.schemas.knowledge import KnowledgeSchema
from app.schemas.knowledge_index import KnowledgeIndexIdentity
from app.schemas.knowledge_management import KnowledgePreview
from app.schemas.managed_knowledge import (
    ManagedIdentifier,
    NonnegativeCounter,
    PositiveRevision,
    Sha256,
)
from app.schemas.managed_knowledge_processing import ProcessingError, SafeOperationKey

if TYPE_CHECKING:
    from app.settings import Settings


class KnowledgePublicationIndexIdentity(KnowledgeIndexIdentity):
    """服务端注入的完整索引身份，不属于客户端确认参数。"""

    dimension: Literal[1536] = 1536
    chunking_version: Literal["heading-v1"] = "heading-v1"

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """沿用既有Embedding配置，读取身份不构造Provider或调用外部模型。"""

        return cls.model_validate(
            {
                "provider": settings.embedding_provider,
                "model": settings.embedding_model,
                "dimension": settings.embedding_dimension,
                "index_version": settings.embedding_index_version,
            }
        )


class KnowledgePublicationTarget(KnowledgeSchema):
    """用户选中的版本及并发计数，必须与当前知识事实一致。"""

    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    expected_revision_no: PositiveRevision
    expected_row_version: NonnegativeCounter


class KnowledgePublicationCandidate(KnowledgeSchema):
    """可审查的正文、元数据和分块，以及绑定实际用户的确认摘要。"""

    preview: KnowledgePreview
    previous_version_id: ManagedIdentifier | None
    confirmation_digest: Sha256
    action: Literal["PUBLISH"] = "PUBLISH"


class KnowledgePublicationConfirmCommand(KnowledgePublicationTarget):
    """明确人工确认才可提交，摘要用于内容绑定，不代表权限或发布成功。"""

    confirmed: StrictBool
    confirmation_digest: Sha256
    idempotency_key: SafeOperationKey

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        """拒绝取消、字符串和数字，不能把非明确确认变为发布意图。"""

        if not value:
            raise ValueError("explicit publication confirmation is required")
        return value


class KnowledgePublicationAcceptance(KnowledgeSchema):
    """接收和执行分开，返回原操作/批次及预留计数，不宣称已发布。"""

    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    operation_id: ManagedIdentifier
    operation_state: Literal["CONFIRMED", "EXECUTING", "SUCCEEDED", "FAILED", "STALE"]
    generation_id: ManagedIdentifier
    generation_state: Literal["BUILDING", "READY", "FAILED"]
    task_id: ManagedIdentifier | None
    task_state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "INTERRUPTED", "STALE"] | None
    reserved_row_version: NonnegativeCounter
    error_code: ProcessingError | None
    replayed: bool

    @model_validator(mode="after")
    def validate_task_reference(self) -> Self:
        """复用READY无需创建任务，新BUILDING批次必须有任务身份和状态。"""

        if (self.task_id is None) != (self.task_state is None):
            raise ValueError("task identity and state must be present together")
        if self.generation_state == "BUILDING" and self.task_id is None:
            raise ValueError("building generation requires an index task")
        return self


class KnowledgePublicationReceipt(KnowledgeSchema):
    """原发布结果和当前管理状态，历史重放不会重新发布或回退到旧版。"""

    operation_id: ManagedIdentifier
    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    generation_id: ManagedIdentifier
    replaced_version_id: ManagedIdentifier | None
    publication_state: Literal["PUBLISHED", "SUPERSEDED", "DISABLED"]
    published_at: AwareDatetime
    is_current_version: bool
    row_version: NonnegativeCounter
    release_revision: NonnegativeCounter
    source_mode: Literal["LEGACY", "MANAGED"]
    replayed: bool

    @model_validator(mode="after")
    def validate_current_pointer(self) -> Self:
        """PUBLISHED必须仍被当前指针选中，历史回执不能伪装成当前版本。"""

        if self.is_current_version != (self.publication_state == "PUBLISHED"):
            raise ValueError("current pointer must match publication state")
        return self
