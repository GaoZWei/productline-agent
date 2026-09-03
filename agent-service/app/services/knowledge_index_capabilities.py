"""依据目录、数据库统计和当前配置判断知识索引是否可用。"""

from __future__ import annotations

from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol

from app.repositories.knowledge import KnowledgeIndexState
from app.schemas.knowledge_index import (
    KnowledgeIndexCapabilitiesResponse,
    KnowledgeIndexIdentity,
    KnowledgeIndexStatus,
)
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT, load_document_catalog
from app.settings import Settings


class KnowledgeIndexCapabilityService:
    """只读取目录身份和索引统计, 不读取正文、向量或访问Embedding服务。"""

    def __init__(
        self,
        settings: Settings,
        *,
        knowledge_root: Path = DEFAULT_KNOWLEDGE_ROOT,
        catalog_path: Path | None = None,
    ) -> None:
        catalog = load_document_catalog(knowledge_root, catalog_path)
        self._expected_document_ids = frozenset(
            document.document_id for document in catalog.documents
        )
        self._expected_index = KnowledgeIndexIdentity(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
            index_version=settings.embedding_index_version,
        )

    async def get(
        self,
        repository: KnowledgeIndexStateReader,
    ) -> KnowledgeIndexCapabilitiesResponse:
        """区分从未入库、目录不完整、索引身份不匹配和可用状态。"""

        state = await repository.get_index_state()
        stored_index = _single_stored_index(state)
        document_ids = {document.document_id for document in state.documents}
        document_count = len(state.documents)
        chunk_count = state.chunk_count

        if document_count == 0 and chunk_count == 0:
            status = KnowledgeIndexStatus.NOT_INDEXED
        elif document_ids != self._expected_document_ids or any(
            document.chunk_count == 0 for document in state.documents
        ):
            status = KnowledgeIndexStatus.INCOMPLETE
        elif stored_index != self._expected_index:
            status = KnowledgeIndexStatus.INDEX_MISMATCH
        else:
            status = KnowledgeIndexStatus.READY

        return KnowledgeIndexCapabilitiesResponse(
            ready=status is KnowledgeIndexStatus.READY,
            status=status,
            expected_document_count=len(self._expected_document_ids),
            document_count=document_count,
            chunk_count=chunk_count,
            expected_index=self._expected_index,
            stored_index=stored_index,
        )


class KnowledgeIndexStateReader(Protocol):
    """能力服务只需要不含正文和向量的索引状态查询。"""

    def get_index_state(self) -> Awaitable[KnowledgeIndexState]: ...


def _single_stored_index(state: KnowledgeIndexState) -> KnowledgeIndexIdentity | None:
    """仅当所有文档具有同一套完整身份时公开已存索引身份。"""

    identities = {
        (
            document.embedding_provider,
            document.embedding_model,
            document.embedding_dimension,
            document.index_version,
        )
        for document in state.documents
    }
    if len(identities) != 1:
        return None
    provider, model, dimension, index_version = next(iter(identities))
    if provider is None or model is None or dimension is None or index_version is None:
        return None
    return KnowledgeIndexIdentity(
        provider=provider,
        model=model,
        dimension=dimension,
        index_version=index_version,
    )


__all__ = ["KnowledgeIndexCapabilityService", "KnowledgeIndexStateReader"]
