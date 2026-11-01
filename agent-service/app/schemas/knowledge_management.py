"""上传应用输入及脱敏输出，不允许调用方提交知识状态、哈希或物理路径。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.schemas.knowledge import KnowledgeSchema
from app.schemas.managed_knowledge import (
    ManagedIdentifier,
    ManagedKnowledgeMetadata,
    NonnegativeCounter,
    PositiveRevision,
)
from app.schemas.managed_knowledge_processing import SafeOperationKey


class KnowledgeManagementError(ValueError):
    """稳定错误码对应固定安全文案，原始文件路径和数据库异常不向外返回。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class KnowledgeUploadCommand(KnowledgeSchema):
    """文件提交即明确上传操作，新资料、新版本和草稿修正使用同一内部命令。"""

    filename: Annotated[str, Field(min_length=1, max_length=256)]
    metadata: ManagedKnowledgeMetadata
    idempotency_key: SafeOperationKey
    document_id: ManagedIdentifier | None = None
    version_id: ManagedIdentifier | None = None
    expected_row_version: NonnegativeCounter | None = None
    expected_revision_no: PositiveRevision | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """已有资料必须携带并发快照，只有草稿修正携带已有规范版本和修订。"""

        if any(char in self.filename for char in ("/", "\\")) or any(
            ord(char) < 32 or ord(char) == 127 for char in self.filename
        ):
            raise ValueError("filename must be a display basename")
        if any(
            isinstance(value, str) and "\x00" in value
            for value in self.metadata.model_dump().values()
        ):
            raise ValueError("metadata cannot contain null characters")
        if (self.document_id is None) != (self.expected_row_version is None):
            raise ValueError("existing document requires expected row version")
        if self.version_id is not None and self.document_id is None:
            raise ValueError("revision update requires document identity")
        if (self.version_id is None) != (self.expected_revision_no is None):
            raise ValueError("revision update requires expected revision")
        return self


class KnowledgeUploadResult(KnowledgeSchema):
    """接收成功与解析结果分开，重放返回同一操作及任务身份。"""

    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    operation_id: ManagedIdentifier
    task_id: ManagedIdentifier
    row_version: NonnegativeCounter
    task_state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "INTERRUPTED", "STALE"]
    error_code: str | None
    is_current_revision: bool
    replayed: bool


class KnowledgePreviewChunk(KnowledgeSchema):
    """预览分块没有向量，不写入检索表。"""

    chunk_id: str
    chunk_index: int
    section_path: tuple[str, ...]
    content: Annotated[str, StringConstraints(strip_whitespace=False)]


class KnowledgePreview(KnowledgeSchema):
    """引用明确版本及修订的预览，不把历史预览当成当前发布确认。"""

    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    row_version: NonnegativeCounter
    is_current_revision: bool
    metadata: ManagedKnowledgeMetadata
    body: Annotated[str, StringConstraints(strip_whitespace=False)]
    chunks: tuple[KnowledgePreviewChunk, ...]


class KnowledgeOriginalFile(KnowledgeSchema):
    """授权读取后的原始字节及展示文件名，不包含存储目录。"""

    filename: str
    content: bytes
