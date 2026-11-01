"""管理库首批持久化契约，这些内部快照不是对外上传或授权请求。"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.schemas.knowledge import (
    DocumentIdentifier,
    DocumentLifecycleValue,
    DocumentTypeValue,
    KnowledgeSchema,
    MetadataText,
    PermissionScopeValue,
)

ManagedIdentifier = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]*-[0-9A-F]{32}$", max_length=128)]
SpecificationVersion = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[0-9]+(?:\.[0-9]+)*$")
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveRevision = Annotated[int, Field(ge=1, le=2**31 - 1)]
NonnegativeCounter = Annotated[int, Field(ge=0, le=2**63 - 1)]


class ManagedKnowledgeLibraryState(KnowledgeSchema):
    """首批内部库状态，不能借内部数据输入提前激活管理检索源。"""

    library_id: Literal["DEFAULT"] = "DEFAULT"
    source_mode: Literal["LEGACY"] = "LEGACY"
    release_revision: NonnegativeCounter = 0
    source_catalog_hash: Sha256 | None = None
    activated_at: None = None


class ManagedKnowledgeDocumentState(KnowledgeSchema):
    """逻辑资料的内部记录，指针归属由数据库组合外键核实。"""

    document_id: ManagedIdentifier
    library_id: Literal["DEFAULT"] = "DEFAULT"
    current_version_id: ManagedIdentifier | None = None
    row_version: NonnegativeCounter = 0
    created_by: Annotated[str, Field(min_length=1, max_length=128)]


class ManagedKnowledgeMetadata(KnowledgeSchema):
    """每次修订保留独立业务元数据，不套用固定catalog的生命周期约束。"""

    title: Annotated[str, Field(min_length=1, max_length=256)]
    document_type: DocumentTypeValue
    satellite_type: MetadataText | None = None
    product_type: MetadataText | None = None
    processing_level: MetadataText | None = None
    specification_version: SpecificationVersion
    effective_date: date
    expiry_date: date | None = None
    permission_scope: PermissionScopeValue
    is_demo: Literal[True] = True
    maintainer: Literal["演示维护用户"] = "演示维护用户"
    change_summary: Annotated[str, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """未来生效和已过期草稿可以保存，日期倒置必须拒绝。"""

        if self.expiry_date is not None and self.expiry_date < self.effective_date:
            raise ValueError("expiry date cannot precede effective date")
        return self

    def metadata_digest(self) -> str:
        """由服务端按固定字段和规范JSON计算哈希，不接收客户端自报值。"""

        payload = self.model_dump(mode="json", include=set(ManagedKnowledgeMetadata.model_fields))
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ManagedKnowledgeVersionIdentity(KnowledgeSchema):
    """规范版本的共同身份及来源，草稿输入和完整状态分别定义。"""

    version_id: ManagedIdentifier
    document_id: ManagedIdentifier
    specification_version: SpecificationVersion
    citation_document_id: DocumentIdentifier
    current_revision_no: PositiveRevision = 1
    source_kind: Literal["UPLOAD", "CATALOG_IMPORT"]
    source_document_id: DocumentIdentifier | None = None
    source_catalog_hash: Sha256 | None = None
    source_lifecycle: DocumentLifecycleValue | None = None
    source_replaced_by: DocumentIdentifier | None = None
    created_by: Annotated[str, Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        """上传引用使用稳定版本身份，导入保留可核对的原始目录身份。"""

        provenance = (self.source_document_id, self.source_catalog_hash, self.source_lifecycle)
        if self.source_kind == "UPLOAD":
            if any(value is not None for value in (*provenance, self.source_replaced_by)):
                raise ValueError("upload cannot claim catalog provenance")
            if self.citation_document_id != self.version_id:
                raise ValueError("upload citation identity must equal version identity")
        else:
            if any(value is None for value in provenance):
                raise ValueError("catalog import requires source identity, hash and lifecycle")
            if self.citation_document_id != self.source_document_id:
                raise ValueError("catalog citation identity must preserve source identity")
            historical = self.source_lifecycle == "HISTORICAL"
            if historical != (self.source_replaced_by is not None):
                raise ValueError("catalog replacement must match source lifecycle")
            if self.source_replaced_by == self.source_document_id:
                raise ValueError("catalog source cannot replace itself")
        return self


class ManagedKnowledgeDraftVersion(ManagedKnowledgeVersionIdentity):
    """新建和修正入口只接收草稿，不允许上传参数自报发布状态。"""

    publication_state: Literal["DRAFT"] = "DRAFT"


class ManagedKnowledgeVersionState(ManagedKnowledgeVersionIdentity):
    """完整持久化状态，只核对行内关系，不能代替权限及发布事务检查。"""

    publication_state: Literal["DRAFT", "PUBLISHED", "SUPERSEDED", "DISABLED", "HISTORICAL"]
    published_revision_no: PositiveRevision | None = None
    published_generation_id: ManagedIdentifier | None = None
    published_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_publication_fields(self) -> Self:
        """已封存版本绑定最后修订，历史导入不能伪造平台发布时间。"""

        if self.publication_state == "DRAFT":
            if any(
                value is not None
                for value in (
                    self.published_revision_no,
                    self.published_generation_id,
                    self.published_at,
                )
            ):
                raise ValueError("draft cannot contain publication fields")
            return self
        if (
            self.published_revision_no != self.current_revision_no
            or self.published_generation_id is None
        ):
            raise ValueError("sealed version requires its current revision and generation")
        if self.publication_state == "HISTORICAL":
            if (
                self.source_kind != "CATALOG_IMPORT"
                or self.source_lifecycle != "HISTORICAL"
                or self.published_at is not None
            ):
                raise ValueError("historical import cannot claim platform publication")
        elif self.published_at is None:
            raise ValueError("published version requires actual publication time")
        return self


class ManagedKnowledgeRevisionSnapshot(ManagedKnowledgeMetadata):
    """原件接收后的内部快照，解析未完成时正文和规范化哈希均为空。"""

    version_id: ManagedIdentifier
    revision_no: PositiveRevision
    original_key: Annotated[str, Field(min_length=1, max_length=512)]
    original_filename: Annotated[str, Field(min_length=1, max_length=256)]
    file_format: Literal["MD", "TXT"]
    byte_size: Annotated[int, Field(ge=1, le=10 * 1024 * 1024)]
    raw_hash: Sha256
    # 正文保留规范化后的首尾空白，不能继承元数据的自动strip而改变引用哈希。
    body: Annotated[str, StringConstraints(strip_whitespace=False), Field(min_length=1)] | None = (
        None
    )
    normalized_hash: Sha256 | None = None
    created_by: Annotated[str, Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def validate_original_and_parse_result(self) -> Self:
        """原件key只由服务端身份生成，解析正文与哈希必须成对。"""

        suffix = "md" if self.file_format == "MD" else "txt"
        expected = f"versions/{self.version_id}/revisions/{self.revision_no}/original.{suffix}"
        if self.original_key != expected:
            raise ValueError("original key must match version, revision and file format")
        if (self.body is None) != (self.normalized_hash is None):
            raise ValueError("parsed body and normalized hash must be present together")
        if self.body is not None:
            if not self.body.strip() or self.body.startswith("\ufeff") or "\r" in self.body:
                raise ValueError("parsed body must be normalized nonblank text")
            digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
            if digest != self.normalized_hash:
                raise ValueError("normalized hash must match parsed body")
        return self
