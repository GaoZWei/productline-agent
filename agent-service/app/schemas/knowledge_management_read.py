"""知识管理查询的字段白名单，不包含原件位置、正文或内部执行快照。"""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.knowledge import KnowledgeSchema
from app.schemas.managed_knowledge import (
    ManagedIdentifier,
    ManagedKnowledgeMetadata,
    NonnegativeCounter,
    PositiveRevision,
)

KnowledgePageNumber = Annotated[int, Field(ge=1, le=1_000_000)]
KnowledgePageSize = Annotated[int, Field(ge=1, le=100)]


class KnowledgeReadQuery(KnowledgeSchema):
    """内部查询命令，权限范围只能由Java授权结果提供。"""

    kind: Literal["documents", "document", "versions", "version", "tasks", "task"]
    document_id: ManagedIdentifier | None = None
    version_id: ManagedIdentifier | None = None
    task_id: ManagedIdentifier | None = None
    page: KnowledgePageNumber = 1
    page_size: KnowledgePageSize = 20

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """单项和子集合必须指定所属资源，内部调用同样不能省略归属。"""

        required = {
            "documents": set(),
            "document": {"document_id"},
            "versions": {"document_id"},
            "version": {"document_id", "version_id"},
            "tasks": {"document_id"},
            "task": {"task_id"},
        }[self.kind]
        supplied = {
            name
            for name in ("document_id", "version_id", "task_id")
            if getattr(self, name) is not None
        }
        if required != supplied:
            raise ValueError("query target does not match query kind")
        return self


class KnowledgeVersionSummary(KnowledgeSchema):
    """当前草稿修订的元数据与规范版本状态，管理可见不代表问答可检索。"""

    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    citation_document_id: str
    current_revision_no: PositiveRevision
    publication_state: Literal["DRAFT", "PUBLISHED", "SUPERSEDED", "DISABLED", "HISTORICAL"]
    published_revision_no: PositiveRevision | None
    published_at: AwareDatetime | None
    created_at: AwareDatetime
    metadata: ManagedKnowledgeMetadata
    original_filename: str
    file_format: Literal["MD", "TXT"]
    byte_size: NonnegativeCounter
    parsed: bool


class KnowledgeDocumentSummary(KnowledgeSchema):
    """每份资料返回最新可访问版本，不能把它当作当前发布指针。"""

    document_id: ManagedIdentifier
    row_version: NonnegativeCounter
    created_at: AwareDatetime
    latest_version: KnowledgeVersionSummary


class KnowledgeTaskSummary(KnowledgeSchema):
    """任务仅返回处理事实，重试接口尚未提供，不宣称已经可以执行重试。"""

    document_id: ManagedIdentifier
    task_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    task_type: Literal["PARSE", "INDEX"]
    state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "INTERRUPTED", "STALE"]
    attempt_no: PositiveRevision
    is_current_revision: bool
    error_code: str | None
    error_message: str | None
    retry_available: Literal[False] = False
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None


class KnowledgePage[T](KnowledgeSchema):
    """范围过滤先于计数和分页，空集合保持明确的零总数。"""

    items: tuple[T, ...]
    page: KnowledgePageNumber
    page_size: KnowledgePageSize
    total: NonnegativeCounter


type KnowledgeReadResult = (
    KnowledgeDocumentSummary
    | KnowledgeVersionSummary
    | KnowledgeTaskSummary
    | KnowledgePage[KnowledgeDocumentSummary]
    | KnowledgePage[KnowledgeVersionSummary]
    | KnowledgePage[KnowledgeTaskSummary]
)


class KnowledgeReadError(KnowledgeSchema):
    """所有错误文案固定，不透传Java或数据库异常内容。"""

    trace_id: str
    code: str
    message: str
