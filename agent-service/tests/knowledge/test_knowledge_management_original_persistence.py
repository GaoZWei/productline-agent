"""真实HTTP/数据库/原件目录的附件下载、历史保留及失败隔离验收。"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock
from urllib.parse import unquote

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
from app.services.knowledge_management import KnowledgeManagementService
from app.settings import Settings
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.test_knowledge_management_persistence import ManagementHarness
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.knowledge.test_knowledge_management_upload_persistence import form
from tests.test_knowledge_upload_api import payload

ROOT = "/api/agent/knowledge"
HEADERS = {
    "X-User-Id": "demo-reviewer",
    "X-User-Role": "REVIEWER",
    "Idempotency-Key": "original-upload",
}


def path(document_id: str, version_id: str, revision_no: int = 1) -> str:
    """同一修订分别有预览和原件入口，下载不依赖预览是否完成。"""

    return f"{ROOT}/documents/{document_id}/versions/{version_id}/revisions/{revision_no}/original"


@pytest.mark.integration
async def test_knowledge_management_original_http_history_pending_failed_and_no_recovery(
    management: ManagementHarness,
    managed_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = management.service
    raw = "\ufeff# 测试规范\r\n\r\n## 要求\r\n OLD-ORIGINAL \r\n".encode()
    filename = '中文 "规范";v1%.md'
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        uploaded = await client.post(
            ROOT + "/documents", headers=HEADERS, files=form(payload(), raw, filename)
        )
        assert uploaded.status_code == 201
        first = uploaded.json()
        target = path(first["document_id"], first["version_id"])
        download = await client.get(target, headers=HEADERS)
        assert download.status_code == 200 and download.content == raw
        assert download.headers["content-type"] == "application/octet-stream"
        assert download.headers["content-length"] == str(len(raw))
        assert (
            unquote(download.headers["content-disposition"].split("filename*=UTF-8''", 1)[1])
            # HTTPX将multipart文件名中的引号写为%22，下载保留实际接收名，不再次解码%。
            == "中文 %22规范%22;v1%.md"
        )
        revision_url = (
            f"{ROOT}/documents/{first['document_id']}/versions/{first['version_id']}/revisions"
        )
        new_raw = "# 测试规范\n\n## 要求\n NEW-ORIGINAL\n".encode()
        revised = await client.post(
            revision_url,
            headers={**HEADERS, "Idempotency-Key": "original-revise"},
            files=form(
                payload(expected_row_version=1, expected_revision_no=1), new_raw, "新规范.md"
            ),
        )
        assert revised.status_code == 201
        assert (await client.get(target, headers=HEADERS)).content == raw
        assert (
            await client.get(path(first["document_id"], first["version_id"], 2), headers=HEADERS)
        ).content == new_raw
        with monkeypatch.context() as patch:
            patch.setattr(management.service, "process_parse", AsyncMock(return_value=False))
            pending = await client.post(
                ROOT + "/documents",
                headers={**HEADERS, "Idempotency-Key": "original-pending"},
                files=form(payload(), b" pending TXT\r\n", "原始规范.txt"),
            )
        assert pending.status_code == 201 and pending.json()["task_state"] == "QUEUED"
        failed = await client.post(
            ROOT + "/documents",
            headers={**HEADERS, "Idempotency-Key": "original-failed"},
            files=form(payload(), b"# wrong title", "错误规范.md"),
        )
        assert failed.status_code == 201 and failed.json()["task_state"] == "FAILED"
        fresh = KnowledgeManagementService(
            ManagedKnowledgeRepository(managed_database),
            management.service.storage,
            management.service.authorizer,
        )
        app.state.knowledge_management_service = fresh
        async with managed_database.session() as session:
            tasks = [
                (t.task_id, t.state, t.owner_id, t.error_code, t.finished_at)
                for t in (await session.scalars(select(Task).order_by(Task.task_id))).all()
            ]
            operations = [
                (op.operation_id, op.state, op.finished_at)
                for op in (
                    await session.scalars(select(Operation).order_by(Operation.operation_id))
                ).all()
            ]
        conditional = await client.get(
            target, headers={**HEADERS, "Range": "bytes=0-1", "If-None-Match": '"old"'}
        )
        assert conditional.status_code == 200 and conditional.content == raw
        assert "etag" not in conditional.headers and "accept-ranges" not in conditional.headers
        pending_download = await client.get(
            path(pending.json()["document_id"], pending.json()["version_id"]), headers=HEADERS
        )
        assert (
            pending_download.status_code == 200 and pending_download.content == b" pending TXT\r\n"
        )
        failed_download = await client.get(
            path(failed.json()["document_id"], failed.json()["version_id"]), headers=HEADERS
        )
        assert failed_download.status_code == 200 and failed_download.content == b"# wrong title"
        with monkeypatch.context() as patch:
            read = Mock(wraps=fresh.storage.read)
            patch.setattr(fresh.storage, "read", read)
            wrong = await client.get(
                path(pending.json()["document_id"], first["version_id"]), headers=HEADERS
            )
            missing = await client.get(
                path(first["document_id"], first["version_id"], 99), headers=HEADERS
            )
            assert wrong.status_code == missing.status_code == 404
            management.denied.add("READ")
            denied = await client.get(target, headers={**HEADERS, "If-None-Match": '"old"'})
            assert denied.status_code == 403 and "OLD-ORIGINAL" not in denied.text
            read.assert_not_called()
        assert not fresh._started
    async with managed_database.session() as session:
        assert [
            (t.task_id, t.state, t.owner_id, t.error_code, t.finished_at)
            for t in (await session.scalars(select(Task).order_by(Task.task_id))).all()
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
async def test_knowledge_management_original_http_integrity_missing_symlink_and_filename(
    management: ManagementHarness,
    managed_database: Database,
    tmp_path: Path,
) -> None:
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = management.service
    raw = b" retained ORIGINAL\r\n"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        uploaded = await client.post(
            ROOT + "/documents", headers=HEADERS, files=form(payload(), raw)
        )
        assert uploaded.status_code == 201
        first = uploaded.json()
        target = path(first["document_id"], first["version_id"])
        original = (
            management.service.storage.root
            / f"versions/{first['version_id']}/revisions/1/original.txt"
        )
        preview_url = target.removesuffix("original") + "preview"
        good_preview = (await client.get(preview_url, headers=HEADERS)).json()
        for damaged in (b"x" * len(raw), b"short"):
            original.write_bytes(damaged)
            response = await client.get(target, headers=HEADERS)
            assert (
                response.status_code == 503
                and response.json()["code"] == "ORIGINAL_INTEGRITY_ERROR"
            )
            assert "content-disposition" not in response.headers
            assert response.headers["Cache-Control"] == "no-store"
            assert (await client.get(preview_url, headers=HEADERS)).json() == good_preview
        original.unlink()
        missing = await client.get(target, headers=HEADERS)
        assert missing.status_code == 404 and missing.json()["code"] == "ORIGINAL_NOT_FOUND"
        assert (await client.get(preview_url, headers=HEADERS)).json() == good_preview
        # 以下文件与符号链接仅存在于本测试的临时目录，不触碰用户原件。
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"PRIVATE OUTSIDE FILE")
        original.symlink_to(outside)
        response = await client.get(target, headers=HEADERS)
        assert (
            response.status_code == 503
            and response.json()["code"] == "KNOWLEDGE_ORIGINAL_UNAVAILABLE"
        )
        assert b"PRIVATE OUTSIDE FILE" not in response.content
        assert outside.read_bytes() == b"PRIVATE OUTSIDE FILE"
        original.unlink()
        original.write_bytes(raw)
        assert (await client.get(target, headers=HEADERS)).content == raw
        for filename in ("../../private.txt", "bad\r\nInjected: yes.txt"):
            async with managed_database.session() as session, session.begin():
                await session.execute(
                    update(Revision)
                    .where(Revision.version_id == first["version_id"])
                    .values(original_filename=filename)
                )
            response = await client.get(target, headers=HEADERS)
            assert response.status_code == 503 and "content-disposition" not in response.headers
            assert "private.txt" not in response.text and "Injected" not in response.text
            assert raw not in response.content and str(tmp_path) not in response.text
