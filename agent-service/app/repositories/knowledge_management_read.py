"""管理资料的纯SELECT查询，不恢复任务、不加载正文、不访问旧索引。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.database import Database
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_management_read import (
    KnowledgeDocumentSummary,
    KnowledgePage,
    KnowledgeReadQuery,
    KnowledgeReadResult,
    KnowledgeTaskSummary,
    KnowledgeVersionSummary,
)
from app.schemas.managed_knowledge import ManagedKnowledgeMetadata

_TASK_ERRORS = {
    "PARSE_FAILED": "document parsing failed",
    "STORAGE_ERROR": "original file is unavailable or invalid",
    "PROCESSING_INTERRUPTED": "processing was interrupted",
    "STALE_INPUT": "task belongs to an outdated revision",
    "TOOL_TIMEOUT": "processing request timed out",
    "UPSTREAM_UNAVAILABLE": "processing service is unavailable",
    "MODEL_OUTPUT_VALIDATION_ERROR": "model output validation failed",
    "INDEX_BUILD_FAILED": "index construction failed",
    "INDEX_VALIDATION_FAILED": "index validation failed",
    "PERMISSION_DENIED": "operation permission was denied",
}


class KnowledgeManagementReadRepository:
    """所有列表、单项和计数都使用服务端授权范围。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def query(self, query: KnowledgeReadQuery, scope: str) -> KnowledgeReadResult:
        """一次读取事务中的计数和结果保持同一快照，不产生状态变更。"""

        metadata_columns = [
            getattr(Revision, name) for name in ManagedKnowledgeMetadata.model_fields
        ]
        versions = (
            select(
                Version.document_id,
                Version.version_id,
                Version.citation_document_id,
                Version.current_revision_no,
                Version.publication_state,
                Version.published_revision_no,
                Version.published_at,
                Version.created_at,
                Document.row_version,
                Document.created_at.label("document_created_at"),
                Revision.original_filename,
                Revision.file_format,
                Revision.byte_size,
                Revision.normalized_hash.is_not(None).label("parsed"),
                *metadata_columns,
            )
            .select_from(Version)
            .join(Document, Document.document_id == Version.document_id)
            .join(
                Revision,
                (Revision.version_id == Version.version_id)
                & (Revision.revision_no == Version.current_revision_no),
            )
            .where(Revision.permission_scope == scope)
        )
        async with self.database.session() as session:
            # GET不接管任务, 固定只读快照避免并发修订造成计数和分页互相矛盾。
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            if query.kind in {"tasks", "task"}:
                statement = (
                    select(
                        Version.document_id,
                        Version.current_revision_no,
                        Task.task_id,
                        Task.version_id,
                        Task.revision_no,
                        Task.task_type,
                        Task.state,
                        Task.attempt_no,
                        Task.error_code,
                        Task.created_at,
                        Task.started_at,
                        Task.finished_at,
                    )
                    .select_from(Task)
                    .join(Version, Version.version_id == Task.version_id)
                    .join(
                        Revision,
                        (Revision.version_id == Task.version_id)
                        & (Revision.revision_no == Task.revision_no),
                    )
                    .where(Revision.permission_scope == scope)
                )
                if query.kind == "task":
                    row = (
                        (await session.execute(statement.where(Task.task_id == query.task_id)))
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
                    return self._task(row)
                await self._require_document(session, versions, query.document_id)
                statement = statement.where(Version.document_id == query.document_id)
                total = await session.scalar(select(func.count()).select_from(statement.subquery()))
                task_rows = (
                    await session.execute(
                        statement.order_by(Task.created_at.desc(), Task.task_id.desc())
                        .offset((query.page - 1) * query.page_size)
                        .limit(query.page_size)
                    )
                ).mappings()
                return KnowledgePage[KnowledgeTaskSummary](
                    items=tuple(self._task(row) for row in task_rows),
                    page=query.page,
                    page_size=query.page_size,
                    total=total or 0,
                )

            if query.kind in {"documents", "document"}:
                ranked = versions.with_only_columns(
                    Version.version_id,
                    func.row_number()
                    .over(
                        partition_by=Version.document_id,
                        order_by=(Version.created_at.desc(), Version.version_id.desc()),
                    )
                    .label("position"),
                ).subquery()
                versions = versions.join(ranked, ranked.c.version_id == Version.version_id).where(
                    ranked.c.position == 1
                )
            if query.document_id is not None:
                versions = versions.where(Version.document_id == query.document_id)
            if query.kind == "version":
                versions = versions.where(Version.version_id == query.version_id)
            if query.kind in {"document", "version"}:
                row = (await session.execute(versions)).mappings().one_or_none()
                if row is None:
                    raise KnowledgeManagementError("RESOURCE_NOT_FOUND")
                return self._document(row) if query.kind == "document" else self._version(row)
            if query.kind == "versions":
                await self._require_document(session, versions, query.document_id)
            total = await session.scalar(select(func.count()).select_from(versions.subquery()))
            rows = (
                (
                    await session.execute(
                        versions.order_by(Version.created_at.desc(), Version.version_id.desc())
                        .offset((query.page - 1) * query.page_size)
                        .limit(query.page_size)
                    )
                )
                .mappings()
                .all()
            )
            if query.kind == "documents":
                return KnowledgePage[KnowledgeDocumentSummary](
                    items=tuple(self._document(row) for row in rows),
                    page=query.page,
                    page_size=query.page_size,
                    total=total or 0,
                )
            return KnowledgePage[KnowledgeVersionSummary](
                items=tuple(self._version(row) for row in rows),
                page=query.page,
                page_size=query.page_size,
                total=total or 0,
            )

    @staticmethod
    async def _require_document(
        session: AsyncSession, versions: Select[Any], document_id: str | None
    ) -> None:
        """不存在和无权访问使用相同结果，不能通过空子列表探测资料。"""

        if (
            await session.scalar(
                versions.with_only_columns(Version.version_id)
                .where(Version.document_id == document_id)
                .limit(1)
            )
            is None
        ):
            raise KnowledgeManagementError("RESOURCE_NOT_FOUND")

    @staticmethod
    def _version(row: RowMapping) -> KnowledgeVersionSummary:
        """仅映射公开字段，后续ORM增加内部属性也不会自动进入响应。"""

        data = {
            name: row[name] for name in KnowledgeVersionSummary.model_fields if name != "metadata"
        }
        data["metadata"] = ManagedKnowledgeMetadata.model_validate(
            {name: row[name] for name in ManagedKnowledgeMetadata.model_fields}
        )
        return KnowledgeVersionSummary.model_validate(data)

    @classmethod
    def _document(cls, row: RowMapping) -> KnowledgeDocumentSummary:
        """资料摘要固定携带最新可见版本，不用当前发布指针代替草稿。"""

        return KnowledgeDocumentSummary(
            document_id=row["document_id"],
            row_version=row["row_version"],
            created_at=row["document_created_at"],
            latest_version=cls._version(row),
        )

    @staticmethod
    def _task(row: RowMapping) -> KnowledgeTaskSummary:
        """即使历史数据混入未知错误也只返回固定错误，不透传原始内容。"""

        data = {name: row[name] for name in KnowledgeTaskSummary.model_fields if name in row}
        code = row["error_code"]
        data["error_code"] = (
            code if code in _TASK_ERRORS else ("PROCESSING_FAILED" if code else None)
        )
        data["error_message"] = (
            _TASK_ERRORS.get(code, "knowledge processing failed") if code else None
        )
        data["is_current_revision"] = row["revision_no"] == row["current_revision_no"]
        return KnowledgeTaskSummary.model_validate(data)
