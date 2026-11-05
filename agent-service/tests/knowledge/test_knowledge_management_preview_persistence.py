"""真实隔离数据与HTTP预览，覆盖历史修订、只读恢复边界和损坏证据拒绝。"""

from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select, text, update

from app.database import Database
from app.main import create_app
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.repositories.managed_knowledge import ManagedKnowledgeRepository
from app.schemas.knowledge_management import KnowledgeManagementError
from app.services.knowledge_management import KnowledgeManagementService
from app.settings import Settings
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import byte_chunks
from tests.knowledge.test_knowledge_management_persistence import (
    IDENTITY,
    ManagementHarness,
    command,
)
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.knowledge.test_knowledge_management_upload_persistence import form
from tests.test_knowledge_upload_api import payload

ROOT = "/api/agent/knowledge"
HEADERS = {
    "X-User-Id": IDENTITY.user_id,
    "X-User-Role": "REVIEWER",
    "Idempotency-Key": "preview-upload",
}


def path(document_id: str, version_id: str, revision_no: int = 1) -> str:
    """预览必须携带明确的资料、规范版本及修订身份。"""

    return f"{ROOT}/documents/{document_id}/versions/{version_id}/revisions/{revision_no}/preview"


@pytest.mark.integration
async def test_knowledge_management_preview_http_history_raw_missing_and_no_task_recovery(
    management: ManagementHarness,
    managed_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = management.service
    raw = "\ufeff\n# 测试规范\r\n\r\n## 要求\r\n  OLD-PREVIEW  \r\n".encode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        uploaded = await client.post(
            ROOT + "/documents", headers=HEADERS, files=form(payload(), raw, "规范.md")
        )
        assert uploaded.status_code == 201
        first = uploaded.json()
        first_path = path(first["document_id"], first["version_id"])
        response = await client.get(first_path, headers=HEADERS)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        original_preview = response.json()
        assert original_preview["body"] == raw.decode().removeprefix("\ufeff").replace("\r\n", "\n")
        assert original_preview["is_current_revision"]
        repeated = await client.get(first_path, headers=HEADERS)
        assert repeated.json() == original_preview
        revision_url = (
            f"{ROOT}/documents/{first['document_id']}/versions/{first['version_id']}/revisions"
        )
        revised_raw = "\n# 测试规范\n\n## 要求\n  NEW-PREVIEW  \n".encode()
        revised = await client.post(
            revision_url,
            headers={**HEADERS, "Idempotency-Key": "preview-revise"},
            files=form(
                payload(expected_row_version=1, expected_revision_no=1), revised_raw, "规范.md"
            ),
        )
        assert revised.status_code == 201
        old = await client.get(first_path, headers=HEADERS)
        new = await client.get(path(first["document_id"], first["version_id"], 2), headers=HEADERS)
        assert old.json()["body"] == original_preview["body"]
        assert old.json()["chunks"] == original_preview["chunks"]
        assert not old.json()["is_current_revision"] and new.json()["is_current_revision"]
        assert new.json()["body"] == revised_raw.decode() and new.json()["row_version"] == 2
        # 删除的仅为本测试独立目录内原件，已存规范化证据仍应保持。
        original = (
            management.service.storage.root
            / f"versions/{first['version_id']}/revisions/1/original.md"
        )
        original.unlink()
        assert (await client.get(first_path, headers=HEADERS)).json() == old.json()
        txt = await client.post(
            ROOT + "/documents",
            headers={**HEADERS, "Idempotency-Key": "preview-txt"},
            files=form(payload(), b" retained TXT \r\n"),
        )
        assert txt.status_code == 201
        txt_preview = await client.get(
            path(txt.json()["document_id"], txt.json()["version_id"]), headers=HEADERS
        )
        assert txt_preview.json()["body"] == " retained TXT \n" and txt_preview.json()["chunks"]
        with monkeypatch.context() as patch:
            patch.setattr(management.service, "process_parse", AsyncMock(return_value=False))
            pending = await client.post(
                ROOT + "/documents",
                headers={**HEADERS, "Idempotency-Key": "preview-pending"},
                files=form(payload(), b"pending text"),
            )
        assert pending.status_code == 201 and pending.json()["task_state"] == "QUEUED"
        fresh = KnowledgeManagementService(
            ManagedKnowledgeRepository(managed_database),
            management.service.storage,
            management.service.authorizer,
        )
        app.state.knowledge_management_service = fresh
        async with managed_database.session() as session:
            tasks = [
                (task.task_id, task.state, task.owner_id, task.error_code, task.finished_at)
                for task in (await session.scalars(select(Task).order_by(Task.task_id))).all()
            ]
            operations = [
                (op.operation_id, op.state, op.finished_at)
                for op in (
                    await session.scalars(select(Operation).order_by(Operation.operation_id))
                ).all()
            ]
        assert (await client.get(first_path, headers=HEADERS)).status_code == 200
        not_ready = await client.get(
            path(pending.json()["document_id"], pending.json()["version_id"]), headers=HEADERS
        )
        assert not_ready.status_code == 409 and not_ready.json()["code"] == "PREVIEW_NOT_READY"
        missing_revision = await client.get(
            path(first["document_id"], first["version_id"], 99), headers=HEADERS
        )
        assert missing_revision.status_code == 404
        wrong_parent = await client.get(
            path(txt.json()["document_id"], first["version_id"]), headers=HEADERS
        )
        assert wrong_parent.status_code == 404
        management.denied.add("READ")
        denied = await client.get(first_path, headers=HEADERS)
        assert denied.status_code == 403 and "OLD-PREVIEW" not in denied.text
        assert not fresh._started
    async with managed_database.session() as session:
        assert [
            (task.task_id, task.state, task.owner_id, task.error_code, task.finished_at)
            for task in (await session.scalars(select(Task).order_by(Task.task_id))).all()
        ] == tasks
        assert [
            (op.operation_id, op.state, op.finished_at)
            for op in (
                await session.scalars(select(Operation).order_by(Operation.operation_id))
            ).all()
        ] == operations
        assert await session.scalar(select(func.count()).select_from(Generation)) == 0
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 0
        assert (
            await session.scalar(text("SELECT source_mode FROM managed_knowledge_libraries"))
            == "LEGACY"
        )


@pytest.mark.integration
async def test_knowledge_management_preview_http_future_scope_hash_and_parse_failure(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    first = await management.service.upload(
        command(metadata={**command().metadata.model_dump(), "effective_date": date(2030, 1, 1)}),
        byte_chunks("# 测试规范\n\n## 要求\n valid future evidence\n".encode()),
        identity=IDENTITY,
    )
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = management.service
    repository = management.service.repository
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        target = path(first.document_id, first.version_id)
        good = await client.get(target, headers=HEADERS)
        assert good.status_code == 200 and good.json()["metadata"]["effective_date"] == "2030-01-01"
        async with managed_database.session() as session:
            revision = await session.get(Revision, (first.version_id, 1))
            assert revision is not None
            original_body, original_hash = revision.body, revision.metadata_hash
        for changed in ({"body": "CORRUPTED PRIVATE BODY"}, {"metadata_hash": "b" * 64}):
            async with managed_database.session() as session, session.begin():
                await session.execute(
                    update(Revision)
                    .where(Revision.version_id == first.version_id)
                    .values(**changed)
                )
            damaged = await client.get(target, headers=HEADERS)
            assert damaged.status_code == 503
            assert damaged.json()["code"] == "KNOWLEDGE_PREVIEW_UNAVAILABLE"
            assert "CORRUPTED" not in damaged.text and "valid future evidence" not in damaged.text
            with pytest.raises(KnowledgeManagementError, match="RESOURCE_NOT_FOUND"):
                await repository.read_revision(
                    first.version_id, 1, "NO_ACCESS", document_id=first.document_id
                )
            with pytest.raises(KnowledgeManagementError, match="RESOURCE_NOT_FOUND"):
                await repository.read_revision(
                    first.version_id, 1, "INTERNAL_REVIEWER", document_id="DOC-" + "F" * 32
                )
            async with managed_database.session() as session, session.begin():
                await session.execute(
                    update(Revision)
                    .where(Revision.version_id == first.version_id)
                    .values(body=original_body, metadata_hash=original_hash)
                )
        assert (await client.get(target, headers=HEADERS)).json() == good.json()
        failed = await management.service.upload(
            command(idempotency_key="bad-markdown"),
            byte_chunks(b"# wrong title"),
            identity=IDENTITY,
        )
        assert failed.task_state == "FAILED"
        response = await client.get(path(failed.document_id, failed.version_id), headers=HEADERS)
        assert response.status_code == 409 and response.json()["code"] == "PREVIEW_NOT_READY"
