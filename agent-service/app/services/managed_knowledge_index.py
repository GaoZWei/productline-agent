"""授权后的动态发布集合就绪检查，不调用模型、不选择或切换默认知识源。"""

import asyncio
from collections import defaultdict
from collections.abc import Mapping

from sqlalchemy.exc import SQLAlchemyError

from app.knowledge.managed_index_evidence import (
    prepare_managed_index,
    validate_managed_index_chunks,
)
from app.repositories.managed_knowledge_index import (
    ManagedKnowledgeIndexRepository,
    ManagedPublishedIndexSnapshot,
    PublishedIndexClaim,
)
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeManagementAction,
)
from app.schemas.knowledge_index import KnowledgeIndexStatus
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge_index import (
    MANAGED_INDEX_DESCRIPTIONS,
    ManagedKnowledgeIndexCapabilities,
    ManagedKnowledgeIndexIdentity,
)
from app.services.knowledge_management import KnowledgeManagementAuthorizer


def evaluate_published_index(
    snapshot: ManagedPublishedIndexSnapshot, expected: KnowledgePublicationIndexIdentity
) -> ManagedKnowledgeIndexCapabilities:
    """在SQL外检查所有发布批次，结构/证据缺陷优先于配置不匹配，结果不含正文。"""

    groups: dict[str, list[PublishedIndexClaim]] = defaultdict(list)
    for claim in snapshot.claims:
        groups[claim.document_id].append(claim)
    chunks: dict[object, list[Mapping[str, object]]] = defaultdict(list)
    for chunk in snapshot.chunks:
        chunks[chunk.get("generation_id")].append(chunk)
    identities: list[ManagedKnowledgeIndexIdentity] = []
    document_count = 0
    incomplete = False
    for claims in groups.values():
        if len(claims) != 1:
            incomplete = True
            continue
        claim = claims[0]
        revision, generation = claim.revision, claim.generation
        if (
            claim.document_id != claim.version.get("document_id")
            or claim.current_version_id != claim.version.get("version_id")
            or claim.version.get("publication_state") != "PUBLISHED"
            or revision is None
            or generation is None
        ):
            incomplete = True
            continue
        document_count += 1
        try:
            identity = ManagedKnowledgeIndexIdentity.model_validate(
                {
                    "provider": generation.get("embedding_provider"),
                    "model": generation.get("embedding_model"),
                    "dimension": generation.get("embedding_dimension"),
                    "index_version": generation.get("index_version"),
                    "chunking_version": generation.get("chunking_version"),
                }
            )
            identities.append(identity)
            if claim.metadata_hash is None:
                raise ValueError("missing sealed metadata hash")
            prepared = prepare_managed_index(
                claim.version, revision, generation, claim.metadata_hash
            )
            validate_managed_index_chunks(chunks.get(generation.get("generation_id"), ()), prepared)
        except ValueError:
            incomplete = True
    expected_index = ManagedKnowledgeIndexIdentity.model_validate(expected.model_dump())
    stored_index = (
        identities[0]
        if len(identities) == len(groups)
        and identities
        and all(item == identities[0] for item in identities)
        else None
    )
    if not groups:
        status = KnowledgeIndexStatus.NOT_INDEXED
    elif incomplete:
        status = KnowledgeIndexStatus.INCOMPLETE
    elif stored_index != expected_index:
        status = KnowledgeIndexStatus.INDEX_MISMATCH
    else:
        status = KnowledgeIndexStatus.READY
    reason, message = MANAGED_INDEX_DESCRIPTIONS[status]
    try:
        return ManagedKnowledgeIndexCapabilities.model_validate(
            {
                "source": "MANAGED",
                "configured_source_mode": snapshot.configured_source_mode,
                "release_revision": snapshot.release_revision,
                "ready": status == KnowledgeIndexStatus.READY,
                "status": status,
                "reason": reason,
                "message": message,
                "expected_document_count": len(groups),
                "document_count": document_count,
                "chunk_count": len(snapshot.chunks),
                "expected_index": expected_index,
                "stored_index": stored_index,
            }
        )
    except ValueError:
        raise KnowledgeManagementError("KNOWLEDGE_DATA_INVALID") from None


class ManagedKnowledgeIndexCapabilityService:
    """每次Java READ后检查当前发布快照，不按catalog缓存固定数量或回退旧库。"""

    def __init__(
        self,
        repository: ManagedKnowledgeIndexRepository,
        authorizer: KnowledgeManagementAuthorizer,
        *,
        index_identity: KnowledgePublicationIndexIdentity,
    ) -> None:
        self.repository = repository
        self.authorizer = authorizer
        self.index = index_identity

    async def get(
        self, *, identity: BusinessIdentity, trace_id: str | None = None
    ) -> ManagedKnowledgeIndexCapabilities:
        """授权期间不占SQL，完整校验在线程中运行且已释放读取连接。"""

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
        try:
            snapshot = await self.repository.read_published_snapshot(
                response.data.permission_scope.value
            )
        except SQLAlchemyError:
            raise KnowledgeManagementError("KNOWLEDGE_PERSISTENCE_UNAVAILABLE") from None
        return await asyncio.to_thread(evaluate_published_index, snapshot, self.index)
