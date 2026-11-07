"""管理库显式检索应用，先READ授权和查询向量，事务结束后再融合。"""

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from app.knowledge.hybrid import HybridSearchValidationError, RetrievalResult, fuse_hybrid_results
from app.knowledge.retrieval import QueryEmbeddingGenerator
from app.knowledge.search import preprocess_keyword_query
from app.repositories.managed_knowledge_search import ManagedKnowledgeSearchRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.managed_knowledge_search import (
    ManagedKnowledgeEvidence,
    ManagedKnowledgeReadContext,
    ManagedKnowledgeSearchFilter,
    ManagedKnowledgeSearchOptions,
)
from app.services.knowledge_management import KnowledgeManagementAuthorizer


@dataclass(frozen=True, slots=True)
class ManagedKnowledgeRetrievalResult:
    """现有RRF/引用候选附带管理版本定位，不伪造已接入Run观测或默认切源。"""

    context: ManagedKnowledgeReadContext
    results: tuple[RetrievalResult, ...]
    evidence: tuple[ManagedKnowledgeEvidence, ...]


class ManagedKnowledgeSearchService:
    """仅内部显式读取，不注册HTTP、Agent Tool或替换现有检索装配。"""

    def __init__(
        self,
        repository: ManagedKnowledgeSearchRepository,
        authorizer: KnowledgeManagementAuthorizer,
        embedding_generator: QueryEmbeddingGenerator,
        *,
        options: ManagedKnowledgeSearchOptions | None = None,
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer
        self.embedding_generator = embedding_generator
        self.options = options or ManagedKnowledgeSearchOptions()

    async def retrieve(
        self,
        query: str,
        *,
        filters: ManagedKnowledgeSearchFilter,
        identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> ManagedKnowledgeRetrievalResult:
        """页面范围只能收窄，Java范围不匹配时在模型和SQL之前拒绝。"""

        response = await self.authorizer.authorize(
            KnowledgeAuthorizationRequest(action=KnowledgeManagementAction.READ),
            identity=identity,
            trace_id=trace_id,
        )
        if (
            response.data.user_id != identity.user_id
            or response.data.action != KnowledgeManagementAction.READ
            or response.data.confirmation_required is not False
        ):
            raise KnowledgeManagementError("INVALID_AUTHORIZATION_RESPONSE")
        if response.data.permission_scope != filters.permission_scope:
            raise KnowledgeManagementError("PERMISSION_DENIED")
        preprocess_keyword_query(query)
        query_embedding = await self.embedding_generator.generate_query(query)
        try:
            snapshot = await self.repository.search(
                query, query_embedding, filters=filters, options=self.options
            )
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        try:
            results = fuse_hybrid_results(
                snapshot.keyword_hits, snapshot.vector_hits, top_k=self.options.hybrid_top_k
            )
        except HybridSearchValidationError:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None
        retained = {
            (result.document_id, chunk_id) for result in results for chunk_id in result.chunk_ids
        }
        evidence = tuple(
            item
            for item in snapshot.evidence
            if (item.citation_document_id, item.chunk_id) in retained
        )
        if {(item.citation_document_id, item.chunk_id) for item in evidence} != retained:
            raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID")
        return ManagedKnowledgeRetrievalResult(snapshot.context, results, evidence)
