"""管理操作、任务和索引的严格内部记录，不接受任意审计载荷或凭据。"""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.schemas.knowledge import KnowledgeSchema, MetadataText
from app.schemas.managed_knowledge import (
    ManagedIdentifier,
    NonnegativeCounter,
    PositiveRevision,
    Sha256,
)

WriteAction = Literal["UPLOAD", "PUBLISH", "DISABLE", "RETRY_INDEX"]
ProcessingError = Literal[
    "PARSE_FAILED",
    "STORAGE_ERROR",
    "INDEX_BUILD_FAILED",
    "INDEX_VALIDATION_FAILED",
    "TOOL_TIMEOUT",
    "UPSTREAM_UNAVAILABLE",
    "PERMISSION_DENIED",
    "MODEL_OUTPUT_VALIDATION_ERROR",
    "PROCESSING_INTERRUPTED",
    "STALE_INPUT",
]
SafeOperationKey = Annotated[
    str, Field(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
]


class ManagedKnowledgeConfirmation(KnowledgeSchema):
    """人工操作的最小确认输入，真实权限与数据库事实仍须执行时复查。"""

    actor_id: MetadataText
    action: WriteAction
    library_id: Literal["DEFAULT"] = "DEFAULT"
    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    raw_hash: Sha256
    normalized_hash: Sha256 | None = None
    metadata_hash: Sha256
    expected_row_version: NonnegativeCounter
    previous_version_id: ManagedIdentifier | None = None
    task_id: ManagedIdentifier | None = None
    generation_id: ManagedIdentifier | None = None

    @model_validator(mode="after")
    def validate_action_evidence(self) -> Self:
        """上传不复用执行任务，发布和重试需要解析后的证据身份。"""

        if self.action != "UPLOAD" and self.normalized_hash is None:
            raise ValueError("non-upload confirmation requires normalized content hash")
        if self.action == "RETRY_INDEX":
            if self.task_id is None:
                raise ValueError("retry confirmation requires original task")
        elif self.task_id is not None:
            raise ValueError("original task is only applicable to retry")
        if self.action == "DISABLE" and self.previous_version_id != self.version_id:
            raise ValueError("disable must target current published version")
        if self.action == "UPLOAD" and self.generation_id is not None:
            raise ValueError("upload cannot reuse an index generation")
        return self


class ManagedKnowledgeOperationRecord(KnowledgeSchema):
    """操作幂等身份及可审查确认，不实现幂等重放或实际执行。"""

    operation_id: ManagedIdentifier
    actor_id: MetadataText
    action: WriteAction
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    target_type: Literal["VERSION"] = "VERSION"
    target_id: ManagedIdentifier
    idempotency_key: SafeOperationKey
    input_hash: Sha256
    confirmation_snapshot: ManagedKnowledgeConfirmation
    state: Literal["CONFIRMED", "EXECUTING", "SUCCEEDED", "FAILED", "STALE"] = "CONFIRMED"
    result_id: ManagedIdentifier | None = None
    error_code: ProcessingError | None = None
    created_at: AwareDatetime
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_snapshot_and_result(self) -> Self:
        """快照必须属于本次用户和目标，终态不得缺少结果或受控失败原因。"""

        snapshot = self.confirmation_snapshot
        if (snapshot.actor_id, snapshot.action, snapshot.version_id, snapshot.revision_no) != (
            self.actor_id,
            self.action,
            self.version_id,
            self.revision_no,
        ) or self.target_id != self.version_id:
            raise ValueError("confirmation must match operation identity")
        terminal = self.state in {"SUCCEEDED", "FAILED", "STALE"}
        if terminal != (self.finished_at is not None):
            raise ValueError("operation completion time must match state")
        if (self.state in {"FAILED", "STALE"}) != (self.error_code is not None):
            raise ValueError("operation error must match failure state")
        if (self.state == "SUCCEEDED") != (self.result_id is not None):
            raise ValueError("operation result must match successful state")
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise ValueError("operation cannot finish before creation")
        return self


class ManagedKnowledgeGenerationRecord(KnowledgeSchema):
    """候选索引身份及构建结果，READY不等于默认可检索或允许发布。"""

    generation_id: ManagedIdentifier
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    embedding_provider: Annotated[str, Field(min_length=1, max_length=64)]
    embedding_model: MetadataText
    embedding_dimension: Literal[1536] = 1536
    index_version: MetadataText
    chunking_version: MetadataText
    input_hash: Sha256
    build_method: Literal["GENERATED", "COPIED_LEGACY"]
    state: Literal["BUILDING", "READY", "FAILED"] = "BUILDING"
    chunk_count: NonnegativeCounter = 0
    error_code: ProcessingError | None = None
    created_at: AwareDatetime
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_build_result(self) -> Self:
        """仅验证本记录，实际分块数量、身份与向量完整性由后续事务核对。"""

        if (self.state != "BUILDING") != (self.finished_at is not None):
            raise ValueError("generation completion time must match state")
        if (self.state == "FAILED") != (self.error_code is not None):
            raise ValueError("generation error must match failure state")
        if self.state == "READY" and self.chunk_count == 0:
            raise ValueError("ready generation requires a positive chunk count")
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise ValueError("generation cannot finish before creation")
        return self


class ManagedKnowledgeTaskRecord(KnowledgeSchema):
    """解析/索引任务快照，旧失败记录通过重试关联保留。"""

    task_id: ManagedIdentifier
    operation_id: ManagedIdentifier
    operation_action: WriteAction
    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    task_type: Literal["PARSE", "INDEX"]
    generation_id: ManagedIdentifier | None = None
    state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "INTERRUPTED", "STALE"] = "QUEUED"
    owner_id: MetadataText
    attempt_no: Annotated[int, Field(ge=1, le=2**63 - 1)] = 1
    retry_of_task_id: ManagedIdentifier | None = None
    trace_id: SafeOperationKey
    error_code: ProcessingError | None = None
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_task_input_and_state(self) -> Self:
        """类型限定操作和索引批次，时间及失败原因须与任务状态一致。"""

        if self.task_type == "PARSE":
            if self.operation_action != "UPLOAD" or self.generation_id is not None:
                raise ValueError("parse task requires upload and cannot bind generation")
        elif self.operation_action not in {"PUBLISH", "RETRY_INDEX"} or self.generation_id is None:
            raise ValueError("index task requires publish/retry and generation")
        retrying = self.operation_action == "RETRY_INDEX"
        if retrying != (self.retry_of_task_id is not None) or retrying != (self.attempt_no > 1):
            raise ValueError("retry requires original task and a new attempt number")
        if self.retry_of_task_id == self.task_id:
            raise ValueError("task cannot retry itself")
        terminal = self.state in {"SUCCEEDED", "FAILED", "INTERRUPTED", "STALE"}
        if terminal != (self.finished_at is not None):
            raise ValueError("task completion time must match state")
        if (self.state in {"FAILED", "INTERRUPTED", "STALE"}) != (self.error_code is not None):
            raise ValueError("task error must match failure state")
        if self.state == "QUEUED" and self.started_at is not None:
            raise ValueError("queued task cannot have start time")
        if self.state in {"RUNNING", "SUCCEEDED"} and self.started_at is None:
            raise ValueError("running/succeeded task requires start time")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("task cannot start before creation")
        if self.finished_at is not None and self.finished_at < (self.started_at or self.created_at):
            raise ValueError("task cannot finish before creation/start")
        return self


class ManagedKnowledgeChunkRecord(KnowledgeSchema):
    """分块内容和完整1536维向量输入，保留原文且拒绝非有限数值。"""

    generation_id: ManagedIdentifier
    chunk_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
    chunk_index: NonnegativeCounter
    section_path: Annotated[tuple[MetadataText, ...], Field(min_length=1, max_length=16)]
    content: Annotated[str, StringConstraints(strip_whitespace=False), Field(min_length=1)]
    content_hash: Sha256
    token_count: Annotated[int, Field(ge=1, le=2**63 - 1)]
    search_document: Annotated[str, Field(min_length=1)]
    embedding: Annotated[
        tuple[
            Annotated[
                float,
                Field(allow_inf_nan=False, ge=-3.4028234663852886e38, le=3.4028234663852886e38),
            ],
            ...,
        ],
        Field(min_length=1536, max_length=1536),
    ]

    @model_validator(mode="after")
    def validate_content_identity(self) -> Self:
        """校验原文哈希与非零向量，稳定Chunk ID仍由既有分块算法产生。"""

        if (
            not self.content.strip()
            or hashlib.sha256(self.content.encode()).hexdigest() != self.content_hash
        ):
            raise ValueError("chunk content hash must match nonblank content")
        if not any(self.embedding):
            raise ValueError("cosine embedding cannot be a zero vector")
        return self
