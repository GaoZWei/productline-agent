"""隔离PostgreSQL、真实授权Client及独立原件目录的应用服务验收。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from app.clients.business import BusinessHttpClient
from app.clients.knowledge_authorization import KnowledgeAuthorizationClient
from app.database import Database
from app.errors import ToolErrorCode, ToolException
from app.knowledge.managed_parsing import ParsedKnowledgeRevision, parse_managed_revision
from app.knowledge.storage import KnowledgeOriginalStorage
from app.models import (
    ManagedKnowledgeChunk as Chunk,
)
from app.models import (
    ManagedKnowledgeDocument as Document,
)
from app.models import (
    ManagedKnowledgeIndexGeneration as Generation,
)
from app.models import (
    ManagedKnowledgeOperation as Operation,
)
from app.models import (
    ManagedKnowledgeRevision as Revision,
)
from app.models import (
    ManagedKnowledgeTask as Task,
)
from app.models import (
    ManagedKnowledgeVersion as Version,
)
from app.repositories.managed_knowledge import ManagedKnowledgeRepository
from app.schemas.business import BusinessIdentity
from app.schemas.knowledge_management import KnowledgeManagementError, KnowledgeUploadCommand
from app.services.knowledge_management import KnowledgeManagementService
from app.settings import Settings
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import CREATED_AT, byte_chunks, generation_payload

IDENTITY = BusinessIdentity(user_id="demo-reviewer", role="REVIEWER")


@dataclass
class ManagementHarness:
    """仅HTTP边界使用替身，持久化和文件系统均为真实隔离实现。"""

    service: KnowledgeManagementService
    client: BusinessHttpClient
    denied: set[str] = field(default_factory=set)
    actions: list[str] = field(default_factory=list)
    authorization_barrier: asyncio.Barrier | None = None


@pytest_asyncio.fixture
async def management(
    managed_database: Database, tmp_path: Path
) -> AsyncIterator[ManagementHarness]:
    """真实Client校验Java信封，同时断言HTTP调用时没有借用SQL连接。"""

    denied: set[str] = set()
    actions: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        """仅模拟固定授权查询，不访问真实Java或外部模型。"""
        assert cast(QueuePool, managed_database.engine.pool).checkedout() == 0
        if harness.authorization_barrier is not None:
            await harness.authorization_barrier.wait()
        action = json.loads(request.content)["action"]
        actions.append(action)
        trace = request.headers["X-Trace-Id"]
        allowed = action not in denied and request.headers["X-User-Role"] == "REVIEWER"
        return httpx.Response(
            200 if allowed else 403,
            headers={"X-Trace-Id": trace},
            json={
                "success": allowed,
                "code": "SUCCESS" if allowed else "PERMISSION_DENIED",
                "message": "success" if allowed else "permission denied",
                "trace_id": trace,
                "retryable": False,
                "data": {
                    "userId": request.headers["X-User-Id"],
                    "action": action,
                    "permissionScope": "INTERNAL_REVIEWER",
                    "confirmationRequired": action != "READ",
                }
                if allowed
                else None,
            },
        )

    client = BusinessHttpClient(
        Settings(environment="test"), transport=httpx.MockTransport(handler)
    )
    service = KnowledgeManagementService(
        ManagedKnowledgeRepository(managed_database),
        KnowledgeOriginalStorage(tmp_path / "originals"),
        KnowledgeAuthorizationClient(client),
    )
    harness = ManagementHarness(service, client, denied, actions)
    yield harness
    await client.aclose()


def command(**updates: object) -> KnowledgeUploadCommand:
    """新版本资料使用固定业务元数据，允许未来生效草稿但不发布。"""

    return KnowledgeUploadCommand.model_validate(
        {
            "filename": "规范.md",
            "idempotency_key": "upload-1",
            "metadata": {
                "title": "测试规范",
                "document_type": "QUALITY_SPEC",
                "specification_version": "1.0",
                "effective_date": CREATED_AT.date(),
                "permission_scope": "INTERNAL_REVIEWER",
                "change_summary": "首次上传",
            },
            **updates,
        }
    )


def revision_command(
    original: KnowledgeUploadCommand,
    document_id: str,
    version_id: str,
    row_version: int,
    revision_no: int,
    **updates: object,
) -> KnowledgeUploadCommand:
    """修订必须带原版本、当前修订及资料并发计数，不仅提交文件名。"""

    return KnowledgeUploadCommand.model_validate(
        {
            **original.model_dump(),
            "document_id": document_id,
            "version_id": version_id,
            "expected_row_version": row_version,
            "expected_revision_no": revision_no,
            "idempotency_key": f"revise-{revision_no}",
            **updates,
        }
    )


@pytest.mark.integration
async def test_knowledge_management_upload_preview_replay_and_original_keep_exact_evidence(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service = management.service
    raw = "\ufeff# 测试规范\r\n\r\n## 要求\r\n  正文\r\n".encode()
    first = await service.upload(command(), byte_chunks(raw[:7], raw[7:]), identity=IDENTITY)
    assert first.task_state == "SUCCEEDED" and first.row_version == 1
    preview = await service.preview(first.version_id, 1, identity=IDENTITY)
    assert preview.body == raw.decode().removeprefix("\ufeff").replace("\r\n", "\n")
    assert [chunk.section_path for chunk in preview.chunks] == [("测试规范",), ("测试规范", "要求")]
    assert preview.is_current_revision
    original = await service.read_original(first.version_id, 1, identity=IDENTITY)
    assert original.content == raw and original.filename == "规范.md"
    second = await service.upload(command(), byte_chunks(raw), identity=IDENTITY)
    assert second.replayed
    assert (first.operation_id, first.task_id, first.version_id) == (
        second.operation_id,
        second.task_id,
        second.version_id,
    )
    async with managed_database.session() as session:
        for model in (Document, Version, Revision, Operation, Task):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
        for index_model in (Generation, Chunk):
            assert await session.scalar(select(func.count()).select_from(index_model)) == 0
        assert (await session.get(Document, first.document_id)).current_version_id is None  # type: ignore[union-attr]
    assert len(list(service.storage.root.rglob("original.md"))) == 1
    assert list((service.storage.root / "_temporary").iterdir()) == []


@pytest.mark.integration
async def test_knowledge_management_authorization_precedes_file_and_db_and_is_not_cached(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service = management.service
    management.denied.add("UPLOAD")
    with pytest.raises(ToolException) as failure:
        await service.upload(command(), byte_chunks(b"never consumed"), identity=IDENTITY)
    assert failure.value.code is ToolErrorCode.PERMISSION_DENIED
    assert not service.storage.root.exists()
    management.denied.clear()
    first = await service.upload(
        command(), byte_chunks("# 测试规范\n正文".encode()), identity=IDENTITY
    )
    management.denied.update(("UPLOAD", "READ"))
    with pytest.raises(ToolException):
        await service.upload(command(), byte_chunks("# 测试规范\n正文".encode()), identity=IDENTITY)
    with pytest.raises(ToolException):
        await service.preview(first.version_id, 1, identity=IDENTITY)
    with pytest.raises(ToolException):
        await service.read_original(first.version_id, 1, identity=IDENTITY)
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Operation)) == 1


@pytest.mark.integration
async def test_knowledge_management_failed_parse_can_be_corrected_by_metadata_revision(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service = management.service
    raw = "# 另一标题\n正文".encode()
    first = await service.upload(command(), byte_chunks(raw), identity=IDENTITY)
    assert first.task_state == "FAILED" and first.error_code == "PARSE_FAILED"
    with pytest.raises(KnowledgeManagementError, match="PREVIEW_NOT_READY"):
        await service.preview(first.version_id, 1, identity=IDENTITY)
    fixed_metadata = {
        **command().metadata.model_dump(),
        "title": "另一标题",
        "change_summary": "修正标题",
    }
    fixed = revision_command(
        command(), first.document_id, first.version_id, 1, 1, metadata=fixed_metadata
    )
    second = await service.upload(fixed, byte_chunks(raw), identity=IDENTITY)
    assert second.version_id == first.version_id and second.revision_no == 2
    assert second.task_state == "SUCCEEDED"
    async with managed_database.session() as session:
        assert (await session.get(Task, first.task_id)).state == "FAILED"  # type: ignore[union-attr]
        operation = await session.get(Operation, first.operation_id)
        assert operation is not None and operation.state == "SUCCEEDED"
        revisions = (await session.scalars(select(Revision).order_by(Revision.revision_no))).all()
        assert revisions[0].raw_hash == revisions[1].raw_hash
        assert revisions[0].metadata_hash != revisions[1].metadata_hash
        assert revisions[0].body is None


@pytest.mark.integration
async def test_knowledge_management_conflict_and_old_revision_preview_do_not_overwrite(
    management: ManagementHarness,
) -> None:
    service = management.service
    raw = "# 测试规范\n正文一".encode()
    first = await service.upload(command(), byte_chunks(raw), identity=IDENTITY)
    with pytest.raises(KnowledgeManagementError, match="IDEMPOTENCY_CONFLICT"):
        await service.upload(
            command(), byte_chunks("# 测试规范\n正文二".encode()), identity=IDENTITY
        )
    revised = revision_command(command(), first.document_id, first.version_id, 1, 1)
    second = await service.upload(
        revised, byte_chunks("# 测试规范\n正文二".encode()), identity=IDENTITY
    )
    assert second.row_version == 2
    old = await service.preview(first.version_id, 1, identity=IDENTITY)
    assert not old.is_current_revision and old.body.endswith("正文一")
    assert (await service.preview(first.version_id, 2, identity=IDENTITY)).body.endswith("正文二")
    with pytest.raises(KnowledgeManagementError, match="STALE_DOCUMENT"):
        await service.upload(
            revision_command(
                command(), first.document_id, first.version_id, 1, 1, idempotency_key="stale-row"
            ),
            byte_chunks(raw),
            identity=IDENTITY,
        )
    with pytest.raises(KnowledgeManagementError, match="STALE_REVISION"):
        await service.upload(
            revision_command(
                command(),
                first.document_id,
                first.version_id,
                2,
                1,
                idempotency_key="stale-revision",
            ),
            byte_chunks(raw),
            identity=IDENTITY,
        )
    replayed = await service.upload(command(), byte_chunks(raw), identity=IDENTITY)
    assert replayed.replayed and not replayed.is_current_revision


def cancelled_parser(
    raw: bytes, *, citation_document_id: str, title: str, file_format: str
) -> ParsedKnowledgeRevision:
    """模拟提交原件后进程停止，不把取消改写成解析失败。"""

    raise asyncio.CancelledError


@pytest.mark.integration
@pytest.mark.parametrize("restart", [False, True])
async def test_knowledge_management_restart_and_late_task_cannot_replace_current_revision(
    management: ManagementHarness,
    managed_database: Database,
    restart: bool,
) -> None:
    service = management.service
    service.parser = cancelled_parser
    raw = "# 测试规范\n旧正文".encode()
    with pytest.raises(asyncio.CancelledError):
        await service.upload(command(), byte_chunks(raw), identity=IDENTITY)
    async with managed_database.session() as session:
        task = await session.scalar(select(Task))
        document = await session.scalar(select(Document))
        assert task is not None and document is not None and task.state == "RUNNING"
        task_id, version_id, document_id = task.task_id, task.version_id, document.document_id
        old_owner = service.owner_id
    if restart:
        service = KnowledgeManagementService(
            ManagedKnowledgeRepository(managed_database),
            KnowledgeOriginalStorage(service.storage.root), service.authorizer,
        )
        await service.start()
        replay = await service.upload(command(), byte_chunks(raw), identity=IDENTITY)
        assert replay.task_state == "INTERRUPTED"
    else:
        service.parser = parse_managed_revision
    updated = await service.upload(
        revision_command(command(), document_id, version_id, 1, 1),
        byte_chunks("# 测试规范\n新正文".encode()),
        identity=IDENTITY,
    )
    old = parse_managed_revision(
        raw, citation_document_id=version_id, title="测试规范", file_format="MD"
    )
    assert not await service.repository.finish_parse(
        task_id, old_owner, body=old.body, normalized_hash=old.normalized_hash
    )
    assert (await service.preview(updated.version_id, 2, identity=IDENTITY)).body.endswith("新正文")
    async with managed_database.session() as session:
        task = await session.get(Task, task_id)
        assert task is not None and task.state == ("INTERRUPTED" if restart else "STALE")
        assert (await session.get(Revision, (version_id, 1))).body is None  # type: ignore[union-attr]
        assert await session.scalar(select(func.count()).select_from(Version)) == 1


@pytest.mark.integration
async def test_knowledge_management_database_failure_keeps_orphan_and_same_bytes_can_retry(
    management: ManagementHarness,
    managed_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = management.service
    first = await service.upload(
        command(), byte_chunks("# 测试规范\n正文一".encode()), identity=IDENTITY
    )
    next_command = revision_command(command(), first.document_id, first.version_id, 1, 1)
    original_accept = service.repository.accept_upload

    async def unavailable(*args: object, **kwargs: object) -> object:
        """数据库异常含秘密时，应用错误和任务记录也不能复制它。"""
        raise SQLAlchemyError("private-path-and-token")

    monkeypatch.setattr(service.repository, "accept_upload", unavailable)
    next_raw = "# 测试规范\n正文二".encode()
    with pytest.raises(
        KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"
    ) as failure:
        await service.upload(next_command, byte_chunks(next_raw), identity=IDENTITY)
    assert "private-path" not in str(failure.value)
    assert len(list(service.storage.root.rglob("original.md"))) == 2
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Revision)) == 1
    monkeypatch.setattr(service.repository, "accept_upload", original_accept)
    with pytest.raises(KnowledgeManagementError, match="ORIGINAL_CONFLICT"):
        await service.upload(
            next_command, byte_chunks("# 测试规范\n不同文件".encode()), identity=IDENTITY
        )
    retried = await service.upload(next_command, byte_chunks(next_raw), identity=IDENTITY)
    assert retried.revision_no == 2 and retried.task_state == "SUCCEEDED"
    assert len(list(service.storage.root.rglob("original.md"))) == 2


@pytest.mark.integration
async def test_knowledge_management_sealed_version_requires_new_spec_and_old_release_stays(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    service = management.service
    first = await service.upload(
        command(), byte_chunks("# 测试规范\n已发布正文".encode()), identity=IDENTITY
    )
    generation_id = "GEN-" + "7" * 32
    async with managed_database.session() as session, session.begin():
        await session.execute(
            insert(Generation).values(
                **generation_payload(
                    generation_id=generation_id,
                    version_id=first.version_id,
                    state="READY",
                    chunk_count=1,
                    finished_at=CREATED_AT,
                )
            )
        )
        await session.execute(
            update(Version)
            .where(Version.version_id == first.version_id)
            .values(
                publication_state="PUBLISHED",
                published_revision_no=1,
                published_generation_id=generation_id,
                published_at=func.now(),
            )
        )
        await session.execute(update(Document).values(current_version_id=first.version_id))
    with pytest.raises(KnowledgeManagementError, match="SEALED_VERSION_REQUIRES_NEW_VERSION"):
        await service.upload(
            revision_command(command(), first.document_id, first.version_id, 1, 1),
            byte_chunks("# 测试规范\n覆盖正文".encode()),
            identity=IDENTITY,
        )
    new_command = command(
        document_id=first.document_id,
        expected_row_version=1,
        idempotency_key="version-2",
        metadata={**command().metadata.model_dump(), "specification_version": "2.0"},
    )
    second = await service.upload(
        new_command, byte_chunks("# 测试规范\n新版本".encode()), identity=IDENTITY
    )
    assert second.version_id != first.version_id
    async with managed_database.session() as session:
        document = await session.get(Document, first.document_id)
        assert document is not None and document.current_version_id == first.version_id
    assert (await service.preview(first.version_id, 1, identity=IDENTITY)).body.endswith(
        "已发布正文"
    )


@pytest.mark.integration
async def test_knowledge_management_missing_original_does_not_rewrite_existing_preview(
    management: ManagementHarness,
) -> None:
    service = management.service
    result = await service.upload(
        command(filename="test.txt"), byte_chunks(b" retained text \r\n"), identity=IDENTITY
    )
    original_path = next(service.storage.root.rglob("original.txt"))
    original_path.unlink()
    with pytest.raises(KnowledgeManagementError, match="ORIGINAL_NOT_FOUND"):
        await service.read_original(result.version_id, 1, identity=IDENTITY)
    preview = await service.preview(result.version_id, 1, identity=IDENTITY)
    assert preview.body == " retained text \n"


@pytest.mark.integration
async def test_knowledge_management_concurrent_same_upload_returns_one_operation(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    management.authorization_barrier = asyncio.Barrier(2)
    raw = "# 测试规范\n并发正文".encode()
    results = await asyncio.gather(
        *(
            management.service.upload(command(), byte_chunks(raw), identity=IDENTITY)
            for _ in range(2)
        )
    )
    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].operation_id == results[1].operation_id
    assert results[0].task_id == results[1].task_id
    async with managed_database.session() as session:
        for model in (Document, Version, Revision, Operation, Task):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
