"""发布候选的确定性规则和摘要，供审查与接收事务复用。"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import (
    KnowledgePublicationConfirmCommand,
    KnowledgePublicationIndexIdentity,
    KnowledgePublicationTarget,
)
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation

if TYPE_CHECKING:
    from app.repositories.managed_knowledge import PublicationRead


def _digest(payload: dict[str, object]) -> str:
    """规范JSON确保重放不受字段顺序影响，不记录正文或凭据。"""

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def publication_digest(snapshot: ManagedKnowledgeConfirmation) -> str:
    """摘要只绑定审查内容，没有签名、授权或可直接执行的凭证语义。"""

    return _digest({"contract": "knowledge-publication-v1", **snapshot.model_dump(mode="json")})


def publication_request_hash(command: KnowledgePublicationConfirmCommand) -> str:
    """请求哈希只绑定用户输入，不让当前模型配置变化破坏既有操作重放。"""

    return _digest(
        {"contract": "knowledge-publication-request-v1", **command.model_dump(mode="json")}
    )


def publication_generation_hash(
    snapshot: ManagedKnowledgeConfirmation,
    citation_document_id: str,
    index: KnowledgePublicationIndexIdentity,
) -> str:
    """候选索引绑定不可变输入和完整模型/分块身份，不依赖用户或幂等键。"""

    return _digest(
        {
            "contract": "managed-knowledge-generation-v1",
            "version_id": snapshot.version_id,
            "revision_no": snapshot.revision_no,
            "citation_document_id": citation_document_id,
            "raw_hash": snapshot.raw_hash,
            "normalized_hash": snapshot.normalized_hash,
            "metadata_hash": snapshot.metadata_hash,
            "index": index.model_dump(mode="json"),
        }
    )


def publication_confirmation(
    record: PublicationRead, target: KnowledgePublicationTarget, actor: str
) -> ManagedKnowledgeConfirmation:
    """候选及接收事务使用同一规则，权限必须由应用层先经Java校验。"""

    revision = record.revision
    snapshot = revision.snapshot
    if revision.publication_state != "DRAFT":
        raise KnowledgeManagementError("PUBLICATION_REQUIRES_DRAFT")
    if revision.row_version != target.expected_row_version:
        raise KnowledgeManagementError("STALE_DOCUMENT")
    if revision.current_revision_no != target.expected_revision_no:
        raise KnowledgeManagementError("STALE_REVISION")
    if (
        record.previous_version_id == target.version_id
        or record.specification_version != snapshot.specification_version
    ):
        raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
    if not record.parse_succeeded or snapshot.body is None:
        raise KnowledgeManagementError("PUBLICATION_PARSE_NOT_READY")
    if snapshot.effective_date > record.today:
        raise KnowledgeManagementError("PUBLICATION_NOT_EFFECTIVE")
    if snapshot.expiry_date is not None and snapshot.expiry_date < record.today:
        raise KnowledgeManagementError("PUBLICATION_EXPIRED")
    return ManagedKnowledgeConfirmation(
        actor_id=actor,
        action="PUBLISH",
        document_id=target.document_id,
        version_id=target.version_id,
        revision_no=target.expected_revision_no,
        raw_hash=snapshot.raw_hash,
        normalized_hash=snapshot.normalized_hash,
        metadata_hash=revision.metadata_hash,
        expected_row_version=revision.row_version,
        previous_version_id=record.previous_version_id,
    )
