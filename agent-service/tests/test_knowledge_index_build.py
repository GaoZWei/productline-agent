"""候选索引编排的授权、响应校验、超时、取消及数据库失败边界。"""

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ToolException
from app.knowledge.embeddings import (
    ChunkEmbedding,
    EmbeddingErrorCode,
    EmbeddingGeneration,
    EmbeddingIndexDescriptor,
    EmbeddingProviderError,
)
from app.knowledge.index_build import parse_index_input
from app.repositories.knowledge_index_build import IndexBuildClaim, KnowledgeIndexBuildRepository
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.services.knowledge_index_build import KnowledgeIndexBuildService
from tests.test_knowledge_publication import IDENTITY, PublicationHarness
from tests.test_knowledge_publication import publication as publication

INDEX = KnowledgePublicationIndexIdentity(
    provider="openai_compatible", model="test-embedding", index_version="test-v1"
)
DESCRIPTOR = EmbeddingIndexDescriptor(
    INDEX.provider, INDEX.model, INDEX.dimension, INDEX.index_version
)


@dataclass
class BuildHarness:
    """仅SQL和模型调用为替身，解析、完整校验和Java Client均运行真实代码。"""

    service: KnowledgeIndexBuildService
    repository: Mock
    generator: Mock
    claim: IndexBuildClaim


@pytest.fixture
def build(publication: PublicationHarness) -> BuildHarness:
    """复用真实授权Client，创建固定知识快照和可观察的模型替身。"""

    claim = IndexBuildClaim(
        "TASK-" + "1" * 32,
        "GEN-" + "1" * 32,
        IDENTITY.user_id,
        publication.repository.read_publication_candidate.return_value,
        INDEX,
    )
    repository = Mock(spec=KnowledgeIndexBuildRepository)
    repository.operation_action = "PUBLISH"
    repository.claim_index = AsyncMock(return_value=claim)
    repository.finish_index = AsyncMock(return_value=True)
    repository.fail_index = AsyncMock(return_value=True)

    async def generate(chunks: object) -> EmbeddingGeneration:
        """结果显式绑定所有输入Chunk，不访问网络。"""

        return valid_generation(claim)

    generator = Mock()
    generator.generate = AsyncMock(side_effect=generate)
    return BuildHarness(
        KnowledgeIndexBuildService(
            repository,
            publication.service.authorizer,
            generator,
            index_identity=INDEX,
            owner_id="worker-test",
        ),
        repository,
        generator,
        claim,
    )


def valid_generation(claim: IndexBuildClaim) -> EmbeddingGeneration:
    """每个片段使用不同非零向量，便于校验乱序响应仍按身份绑定。"""

    return EmbeddingGeneration(
        DESCRIPTOR,
        datetime(2026, 11, 6, tzinfo=UTC),
        tuple(
            ChunkEmbedding(chunk.chunk_id, (float(index + 1),) + (0.0,) * 1535)
            for index, chunk in enumerate(parse_index_input(claim).chunks)
        ),
    )


async def test_index_build_success_reauthorizes_and_binds_reordered_vectors(
    build: BuildHarness,
    publication: PublicationHarness,
) -> None:
    generated = valid_generation(build.claim)
    build.generator.generate.side_effect = None
    build.generator.generate.return_value = replace(
        generated, embeddings=tuple(reversed(generated.embeddings))
    )
    assert await build.service.process(build.claim.task_id, identity=IDENTITY)
    records = build.repository.finish_index.call_args.args[1]
    assert len(records) == len(generated.embeddings)
    assert [record.embedding[0] for record in records] == [
        float(i + 1) for i in range(len(records))
    ]
    assert publication.actions == ["PUBLISH", "PUBLISH"]
    build.repository.fail_index.assert_not_awaited()


@pytest.mark.parametrize(
    "outcome",
    [
        "missing",
        "duplicate",
        "foreign",
        "dimension",
        "nan",
        "infinity",
        "overflow",
        "zero",
        "model",
        "time",
    ],
)
async def test_index_build_invalid_generation_never_reaches_save(
    build: BuildHarness, outcome: str
) -> None:
    generated = valid_generation(build.claim)
    items = generated.embeddings
    if outcome == "missing":
        generated = replace(generated, embeddings=items[:-1])
    elif outcome == "duplicate":
        generated = replace(generated, embeddings=items + items[:1])
    elif outcome == "foreign":
        generated = replace(
            generated, embeddings=(ChunkEmbedding("foreign-id", items[0].vector), *items[1:])
        )
    elif outcome in {"dimension", "nan", "infinity", "overflow", "zero"}:
        value = {
            "nan": float("nan"),
            "infinity": float("inf"),
            "overflow": 1e39,
            "zero": 0.0,
            "dimension": 1.0,
        }[outcome]
        vector = (value,) * (10 if outcome == "dimension" else 1536)
        generated = replace(
            generated, embeddings=(ChunkEmbedding(items[0].chunk_id, vector), *items[1:])
        )
    elif outcome == "model":
        generated = replace(generated, descriptor=replace(DESCRIPTOR, model="another-model"))
    else:
        generated = replace(generated, generated_at=datetime(2026, 11, 6))
    build.generator.generate.side_effect = None
    build.generator.generate.return_value = generated
    assert not await build.service.process(build.claim.task_id, identity=IDENTITY)
    build.repository.finish_index.assert_not_awaited()
    assert build.repository.fail_index.call_args.kwargs["error_code"] == "INDEX_VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (EmbeddingErrorCode.TIMEOUT, "TOOL_TIMEOUT"),
        (EmbeddingErrorCode.UPSTREAM_UNAVAILABLE, "UPSTREAM_UNAVAILABLE"),
        (EmbeddingErrorCode.RATE_LIMITED, "UPSTREAM_UNAVAILABLE"),
        (EmbeddingErrorCode.AUTHENTICATION, "UPSTREAM_UNAVAILABLE"),
        (EmbeddingErrorCode.INVALID_RESPONSE, "INDEX_VALIDATION_FAILED"),
        (EmbeddingErrorCode.INVALID_REQUEST, "INDEX_BUILD_FAILED"),
    ],
)
async def test_index_build_provider_failure_is_safe(
    build: BuildHarness, code: EmbeddingErrorCode, expected: str
) -> None:
    build.generator.generate.side_effect = EmbeddingProviderError(
        code=code, message="private provider response", retryable=False
    )
    assert not await build.service.process(build.claim.task_id, identity=IDENTITY)
    assert build.repository.fail_index.call_args.kwargs["error_code"] == expected


async def test_index_build_duplicate_or_unowned_task_does_not_call_model(
    build: BuildHarness,
) -> None:
    build.repository.claim_index.return_value = None
    assert not await build.service.process(build.claim.task_id, identity=IDENTITY)
    build.generator.generate.assert_not_awaited()


async def test_index_build_denied_before_claim_does_not_touch_database(
    build: BuildHarness, publication: PublicationHarness
) -> None:
    publication.outcomes.append("DENIED")
    with pytest.raises(ToolException):
        await build.service.process(build.claim.task_id, identity=IDENTITY)
    build.repository.claim_index.assert_not_awaited()
    build.generator.generate.assert_not_awaited()


async def test_index_build_permission_revoked_after_model_fails_owned_task(
    build: BuildHarness, publication: PublicationHarness
) -> None:
    async def revoke(chunks: object) -> EmbeddingGeneration:
        """模拟模型执行期间撤销管理权限，不能保存候选。"""

        publication.outcomes.append("DENIED")
        return valid_generation(build.claim)

    build.generator.generate.side_effect = revoke
    assert not await build.service.process(build.claim.task_id, identity=IDENTITY)
    build.repository.finish_index.assert_not_awaited()
    assert build.repository.fail_index.call_args.kwargs["error_code"] == "PERMISSION_DENIED"


async def test_index_build_overall_timeout_and_cancellation_cleanup(build: BuildHarness) -> None:
    entered = asyncio.Event()

    async def wait_forever(chunks: object) -> EmbeddingGeneration:
        """等到取消，无真实等待时长或外部请求依赖。"""

        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    build.generator.generate.side_effect = wait_forever
    build.service.timeout_seconds = 0.02
    assert not await build.service.process(build.claim.task_id, identity=IDENTITY)
    assert build.repository.fail_index.call_args.kwargs["error_code"] == "TOOL_TIMEOUT"
    entered.clear()
    build.service.timeout_seconds = 120
    task = asyncio.create_task(build.service.process(build.claim.task_id, identity=IDENTITY))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert build.repository.fail_index.call_args.kwargs["error_code"] == "PROCESSING_INTERRUPTED"


async def test_index_build_save_sql_failure_is_reported_and_cleanup_attempted(
    build: BuildHarness,
) -> None:
    build.repository.finish_index.side_effect = SQLAlchemyError("private connection details")
    with pytest.raises(KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"):
        await build.service.process(build.claim.task_id, identity=IDENTITY)
    assert build.repository.fail_index.call_args.kwargs["error_code"] == "INDEX_BUILD_FAILED"
