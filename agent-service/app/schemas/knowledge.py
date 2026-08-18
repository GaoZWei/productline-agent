"""知识文档目录使用的严格元数据与版本关系契约。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMBEDDING_DIMENSION: Literal[1536] = 1536


# 限制文档类型
class DocumentType(StrEnum):
    """首批演示规范允许使用的稳定业务类型。"""

    DOM_PRODUCT_SPEC = "DOM_PRODUCT_SPEC"
    QUALITY_SPEC = "QUALITY_SPEC"
    COORDINATE_SYSTEM_SPEC = "COORDINATE_SYSTEM_SPEC"
    REVIEW_OPERATION_SPEC = "REVIEW_OPERATION_SPEC"
    DELIVERY_SPEC = "DELIVERY_SPEC"


# 过滤文档当前状态(ACTIVE/HISTORICAL)
class DocumentLifecycle(StrEnum):
    """文档是否允许参与默认的当前规范检索。"""

    ACTIVE = "ACTIVE"
    HISTORICAL = "HISTORICAL"


# 当前只有INTERNAL_REVIEWER
# 以后做检索时, 可以先过滤出INTERNAL_REVIEWER权限的文档
class PermissionScope(StrEnum):
    """首批知识文档的检索权限范围。"""

    INTERNAL_REVIEWER = "INTERNAL_REVIEWER"


DocumentTypeValue = Annotated[DocumentType, Field(strict=False)]
DocumentLifecycleValue = Annotated[DocumentLifecycle, Field(strict=False)]
PermissionScopeValue = Annotated[PermissionScope, Field(strict=False)]
DocumentIdentifier = Annotated[
    str,
    Field(min_length=5, max_length=128, pattern=r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$"),
]
MetadataText = Annotated[str, Field(min_length=1, max_length=128)]


# 建立了所有知识库Schema的统一规则
class KnowledgeSchema(BaseModel):
    """知识目录拒绝额外字段、隐式标量转换和加载后的修改。"""

    model_config = ConfigDict(
        extra="forbid",  # 拒绝 JSON出现未知字段时拒绝解析
        frozen=True,  # 解析后的元数据不能被随意修改
        strict=True,  # 尽量拒绝隐式类型转换
        str_strip_whitespace=True,  # 清理字符串首尾空格
    )


# 文档元数据Schema(完整规范文档)
class DocumentMetadata(KnowledgeSchema):
    """一份规范正文的身份、适用范围、版本和权限元数据。"""

    # 文档身份: 唯一定位文档
    document_id: DocumentIdentifier
    title: Annotated[str, Field(min_length=1, max_length=256)]
    file_path: Annotated[str, Field(min_length=1, max_length=512)]
    # 生命周期: 判断是否为当前有效规范
    lifecycle: DocumentLifecycleValue
    replaced_by: DocumentIdentifier | None = None
    # 适用范围: 检索前过滤出适用范围的文档
    document_type: DocumentTypeValue
    satellite_type: MetadataText | None = None
    product_type: MetadataText | None = None
    processing_level: MetadataText | None = None
    # 版本和权限: 版本、有效期和访问范围
    specification_version: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[0-9]+(?:\.[0-9]+)*$"),
    ]
    effective_date: date
    expiry_date: date | None = None
    permission_scope: PermissionScopeValue

    # 文件路径校验
    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        """只允许知识库内部受支持文本格式的POSIX相对路径。"""
        # 防止三类问题: 1. 绝对路径 2. 越过知识库目录 3. 不支持的文件格式
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.suffix.lower() not in {".md", ".txt"}
        ):
            raise ValueError("knowledge document path must be a safe supported text path")
        return value

    # 生命周期校验 保证目录位置、日期和生命周期表达同一件事
    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        """让目录位置、日期和替代关系表达同一个生命周期。"""

        expected_parent = (
            "active" if self.lifecycle is DocumentLifecycle.ACTIVE else "historical"
        )
        if PurePosixPath(self.file_path).parts[0] != expected_parent:
            raise ValueError("knowledge document path does not match lifecycle")
        if self.lifecycle is DocumentLifecycle.ACTIVE:
            if self.expiry_date is not None or self.replaced_by is not None:
                raise ValueError("active document cannot be expired or replaced")
            return self
        if self.expiry_date is None or self.replaced_by is None:
            raise ValueError("historical document requires expiry and replacement")
        if self.expiry_date < self.effective_date:
            raise ValueError("document expiry cannot precede effective date")
        if self.replaced_by == self.document_id:
            raise ValueError("historical document cannot replace itself")
        return self


# 目录级关系校验 不只是校验单份文档, 还校验整个目录
class DocumentCatalog(KnowledgeSchema):
    """知识目录文件及其跨文档唯一性和版本替代关系。"""

    schema_version: Literal[1]
    documents: tuple[DocumentMetadata, ...]

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        """拒绝重复身份、重复路径和无效的历史替代目标。"""
        # document_id不能重复
        documents_by_id: dict[str, DocumentMetadata] = {}
        # file_path不能重复
        file_paths: set[str] = set()
        for document in self.documents:
            if document.document_id in documents_by_id:
                raise ValueError("knowledge catalog contains duplicate document_id")
            if document.file_path in file_paths:
                raise ValueError("knowledge catalog contains duplicate file_path")
            documents_by_id[document.document_id] = document
            file_paths.add(document.file_path)

        for document in self.documents:
            if document.lifecycle is DocumentLifecycle.ACTIVE:
                continue
            assert document.replaced_by is not None
            assert document.expiry_date is not None

            # 历史版本替代关系校验 保证替代目标为当前有效规范
            replacement = documents_by_id.get(document.replaced_by)
            if replacement is None or replacement.lifecycle is not DocumentLifecycle.ACTIVE:
                raise ValueError("historical replacement must reference an active document")
            if (
                replacement.document_type is not document.document_type
                or replacement.satellite_type != document.satellite_type
                or replacement.product_type != document.product_type
                or replacement.processing_level != document.processing_level
                or replacement.effective_date <= document.expiry_date
            ):
                raise ValueError("historical replacement metadata is inconsistent")
        return self
