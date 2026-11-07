"""授权后只读检查首批纳管源，不接收人工发布确认或执行实际纳管。"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.knowledge.import_preflight import (
    ImportFiles,
    LegacyImportSnapshot,
    capture_import_files,
    file_fingerprint,
    validate_import_source,
)
from app.repositories.knowledge_import import KnowledgeImportPreflightRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_import import KnowledgeImportPreflight
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT
from app.services.knowledge_management import KnowledgeManagementAuthorizer


@dataclass(frozen=True, slots=True)
class CheckedImportSource:
    """已授权、验证过的内存源，实际纳管仍须最终重新授权及锁内复查。"""

    files: ImportFiles
    stored: LegacyImportSnapshot
    report: KnowledgeImportPreflight


class KnowledgeImportPreflightService:
    """先查Java上传和发布权限，再核对原件、索引和目标库隔离边界。"""

    def __init__(
        self,
        repository: KnowledgeImportPreflightRepository,
        authorizer: KnowledgeManagementAuthorizer,
        *,
        index_identity: KnowledgePublicationIndexIdentity,
        knowledge_root: Path = DEFAULT_KNOWLEDGE_ROOT,
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer
        self.index_identity = index_identity
        self.knowledge_root = knowledge_root

    async def check(
        self, *, identity: BusinessIdentity, trace_id: str | None = None
    ) -> KnowledgeImportPreflight:
        """报告只证明已读快照，未来写入须重新授权、确认并重查源指纹。"""

        scope = await self.authorize(identity=identity, trace_id=trace_id)
        return (await self.read_authorized_source(identity=identity, scope=scope)).report

    async def authorize(self, *, identity: BusinessIdentity, trace_id: str | None) -> str:
        """只查询Java两个动作，不持有知识事务，不代替明确人工确认。"""

        scopes: list[str] = []
        for action in (KnowledgeManagementAction.UPLOAD, KnowledgeManagementAction.PUBLISH):
            response = await self.authorizer.authorize(
                KnowledgeAuthorizationRequest(action=action), identity=identity, trace_id=trace_id
            )
            if (
                response.data.user_id != identity.user_id
                or response.data.action != action
                or response.data.confirmation_required is not True
            ):
                raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
            scopes.append(response.data.permission_scope.value)
        if scopes[0] != scopes[1]:
            raise KnowledgeManagementError("PERMISSION_DENIED")
        return scopes[0]

    async def read_authorized_source(
        self, *, identity: BusinessIdentity, scope: str
    ) -> CheckedImportSource:
        """仅供已完成本次Java授权的内部流程调用，不是外部调用入口。"""

        files = await asyncio.to_thread(capture_import_files, self.knowledge_root)
        if any(item.metadata.permission_scope.value != scope for item in files.files):
            raise KnowledgeManagementError("PERMISSION_DENIED")
        try:
            stored = await self.repository.read_source(
                tuple(sorted(item.metadata.document_id for item in files.files)), scope
            )
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        report = await asyncio.to_thread(
            validate_import_source,
            files,
            stored,
            actor=identity.user_id,
            scope=scope,
            expected_index=self.index_identity,
        )
        after = await asyncio.to_thread(capture_import_files, self.knowledge_root)
        if file_fingerprint(files) != file_fingerprint(after):
            raise KnowledgeManagementError("IMPORT_SOURCE_CHANGED")
        return CheckedImportSource(files, stored, report)
