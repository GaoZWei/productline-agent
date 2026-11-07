"""首批演示规范只读纳管检查结果，不是导入授权凭证或发布回执。"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StrictBool, field_validator

from app.schemas.knowledge import (
    DocumentIdentifier,
    DocumentLifecycleValue,
    KnowledgeSchema,
    PermissionScopeValue,
)
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge import ManagedIdentifier, NonnegativeCounter, Sha256
from app.schemas.managed_knowledge_processing import SafeOperationKey


class KnowledgeImportVersionCheck(KnowledgeSchema):
    """目录规范身份与逻辑分组，不提前分配管理库UUID或虚构发布时间。"""

    source_document_id: DocumentIdentifier
    logical_document_key: DocumentIdentifier
    title: str
    specification_version: str
    lifecycle: DocumentLifecycleValue
    replaced_by: DocumentIdentifier | None
    file_path: str
    raw_hash: Sha256
    normalized_hash: Sha256
    source_metadata_hash: Sha256
    byte_size: Annotated[int, Field(gt=0)]
    chunk_count: Annotated[int, Field(gt=0)]


class KnowledgeImportPreflight(KnowledgeSchema):
    """只证明已读取源快照的一致性，实际纳管必须重新授权及复核。"""

    status: Literal["VALIDATED"] = "VALIDATED"
    is_demo: Literal[True] = True
    checked_by: str
    permission_scope: PermissionScopeValue
    source_mode: Literal["LEGACY"] = "LEGACY"
    source_catalog_hash: Sha256
    source_fingerprint: Sha256
    library_release_revision: NonnegativeCounter
    logical_document_count: Literal[14] = 14
    version_count: Literal[16] = 16
    active_count: Literal[14] = 14
    historical_count: Literal[2] = 2
    chunk_count: Literal[80] = 80
    index: KnowledgePublicationIndexIdentity
    versions: Annotated[
        tuple[KnowledgeImportVersionCheck, ...], Field(min_length=16, max_length=16)
    ]


class KnowledgeImportCandidate(KnowledgeSchema):
    """明确展示来源与版本清单，摘要绑定实际审查人、范围和库计数。"""

    preflight: KnowledgeImportPreflight
    confirmation_digest: Sha256


class KnowledgeImportCommand(KnowledgeSchema):
    """仅接受明确确认及所审查的源身份，不接受自报正文、状态或UUID。"""

    confirmed: StrictBool
    source_catalog_hash: Sha256
    source_fingerprint: Sha256
    expected_release_revision: NonnegativeCounter
    confirmation_digest: Sha256
    idempotency_key: SafeOperationKey

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        """取消及隐式布尔值不能变为整批纳管意图。"""

        if not value:
            raise ValueError("explicit catalog import confirmation is required")
        return value


class KnowledgeImportedVersion(KnowledgeSchema):
    """原纳管结果，后来停用或发布新版也不改变本次导入身份。"""

    source_document_id: DocumentIdentifier
    document_id: ManagedIdentifier
    version_id: ManagedIdentifier
    generation_id: ManagedIdentifier
    operation_id: ManagedIdentifier
    task_id: ManagedIdentifier
    imported_state: Literal["PUBLISHED", "HISTORICAL"]


class KnowledgeImportReceipt(KnowledgeSchema):
    """整批成功回执与当前库计数，重放不恢复旧指针或覆盖历史。"""

    source_catalog_hash: Sha256
    source_fingerprint: Sha256
    imported_by: str
    imported_at: AwareDatetime
    import_release_revision: NonnegativeCounter
    current_release_revision: NonnegativeCounter
    source_mode: Literal["LEGACY"] = "LEGACY"
    replayed: bool
    versions: Annotated[tuple[KnowledgeImportedVersion, ...], Field(min_length=16, max_length=16)]
