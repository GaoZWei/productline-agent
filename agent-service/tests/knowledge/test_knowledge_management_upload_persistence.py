"""真实数据库、原件目录和HTTP上传修订链路，Java授权仅在传输边界模拟。"""

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, insert, select, text, update

from app.database import Database
from app.main import create_app
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.schemas.business import BusinessIdentity, BusinessResponse
from app.schemas.knowledge_authorization import (
    KnowledgeAuthorizationRequest,
    KnowledgeAuthorizationResponse,
)
from app.settings import Settings
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import CREATED_AT, generation_payload
from tests.knowledge.test_knowledge_management_persistence import IDENTITY, ManagementHarness
from tests.knowledge.test_knowledge_management_persistence import management as management
from tests.test_knowledge_upload_api import payload

ROOT = "/api/agent/knowledge"
HEADERS = {"X-User-Id": IDENTITY.user_id, "X-User-Role": "REVIEWER", "Idempotency-Key": "upload-1"}


def form(
    command: dict[str, object], raw: bytes, filename: str = "规范.txt"
) -> dict[str, tuple[None, str] | tuple[str, bytes]]:
    """文件字节独立于JSON传输，保留BOM及换行。"""

    return {"command": (None, json.dumps(command, ensure_ascii=False)), "file": (filename, raw)}


@pytest.mark.integration
async def test_knowledge_management_upload_http_new_revision_version_replay_and_sealed(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = management.service
    app.state.database = managed_database
    app.state.knowledge_authorization_client = management.service.authorizer
    raw = b"\xef\xbb\xbfraw\r\ntext\r\n"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first_response = await client.post(
            ROOT + "/documents", headers=HEADERS, files=form(payload(), raw)
        )
        assert first_response.status_code == 201, first_response.text
        first = first_response.json()
        assert first["task_state"] == "SUCCEEDED" and not first["replayed"]
        original = await management.service.read_original(first["version_id"], 1, identity=IDENTITY)
        assert original.content == raw
        replay = await client.post(ROOT + "/documents", headers=HEADERS, files=form(payload(), raw))
        assert replay.status_code == 200 and replay.json()["replayed"]
        assert replay.json()["operation_id"] == first["operation_id"]
        conflict = await client.post(
            ROOT + "/documents", headers=HEADERS, files=form(payload(), b"different")
        )
        assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
        revision_path = (
            f"/documents/{first['document_id']}/versions/{first['version_id']}/revisions"
        )
        revision_command = payload(
            expected_row_version=first["row_version"], expected_revision_no=1
        )
        revised = await client.post(
            ROOT + revision_path,
            headers={**HEADERS, "Idempotency-Key": "revise-1"},
            files=form(revision_command, "修正正文".encode()),
        )
        assert revised.status_code == 201 and revised.json()["revision_no"] == 2
        assert (
            await management.service.read_original(first["version_id"], 1, identity=IDENTITY)
        ).content == raw
        assert (
            await management.service.preview(first["version_id"], 2, identity=IDENTITY)
        ).body == "修正正文"
        stale = await client.post(
            ROOT + revision_path,
            headers={**HEADERS, "Idempotency-Key": "stale"},
            files=form(revision_command, b"stale"),
        )
        assert stale.status_code == 409 and stale.json()["code"] == "STALE_DOCUMENT"
        # 仅构造已封存事实测试保护，不实现或调用发布流程。
        generation_id = "GEN-" + "7" * 32
        async with managed_database.session() as session, session.begin():
            await session.execute(
                insert(Generation).values(
                    **generation_payload(
                        generation_id=generation_id,
                        version_id=first["version_id"],
                        revision_no=2,
                        state="READY",
                        chunk_count=1,
                        finished_at=CREATED_AT,
                    )
                )
            )
            await session.execute(
                update(Version)
                .where(Version.version_id == first["version_id"])
                .values(
                    publication_state="PUBLISHED",
                    published_revision_no=2,
                    published_generation_id=generation_id,
                    published_at=func.now(),
                )
            )
            await session.execute(
                update(Document)
                .where(Document.document_id == first["document_id"])
                .values(current_version_id=first["version_id"])
            )
        sealed = await client.post(
            ROOT + revision_path,
            headers={**HEADERS, "Idempotency-Key": "sealed"},
            files=form(payload(expected_row_version=2, expected_revision_no=2), b"overwrite"),
        )
        assert (
            sealed.status_code == 409
            and sealed.json()["code"] == "SEALED_VERSION_REQUIRES_NEW_VERSION"
        )
        new_command = payload(expected_row_version=2)
        original_metadata = payload()["metadata"]
        assert isinstance(original_metadata, dict)
        metadata = dict(original_metadata)
        metadata["specification_version"] = "2.0"
        new_command["metadata"] = metadata
        new_version = await client.post(
            ROOT + f"/documents/{first['document_id']}/versions",
            headers={**HEADERS, "Idempotency-Key": "version-2"},
            files=form(new_command, b"new version"),
        )
        assert (
            new_version.status_code == 201
            and new_version.json()["version_id"] != first["version_id"]
        )
        invalid_md = await client.post(
            ROOT + "/documents",
            headers={**HEADERS, "Idempotency-Key": "parse-fail"},
            files=form(payload(), b"# wrong title", "spec.md"),
        )
        assert invalid_md.status_code == 201 and invalid_md.json()["task_state"] == "FAILED"
        assert invalid_md.json()["error_code"] == "PARSE_FAILED"
        task = await client.get(ROOT + f"/tasks/{invalid_md.json()['task_id']}", headers=HEADERS)
        assert task.status_code == 200 and task.json()["error_code"] == "PARSE_FAILED"
        assert "original_key" not in first_response.text and "raw_hash" not in first_response.text
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 4
        assert (
            await session.scalar(
                select(Document.current_version_id).where(
                    Document.document_id == first["document_id"]
                )
            )
            == first["version_id"]
        )
        assert (
            await session.scalar(text("SELECT source_mode FROM managed_knowledge_libraries"))
            == "LEGACY"
        )


@pytest.mark.integration
async def test_knowledge_management_upload_http_bad_files_never_create_drafts(
    management: ManagementHarness,
    managed_database: Database,
) -> None:
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = management.service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for raw, filename, code, status in (
            (b"", "spec.txt", "EMPTY_DOCUMENT", 422),
            (b"\xff", "spec.txt", "INVALID_ENCODING", 422),
            (b"text\x00binary", "spec.txt", "INVALID_TEXT_CONTENT", 422),
            (b"text", "spec.pdf", "UNSUPPORTED_FORMAT", 415),
            (b"text", "../spec.md", "INVALID_UPLOAD_COMMAND", 422),
            (b"a" * (10 * 1024 * 1024 + 1), "spec.txt", "FILE_TOO_LARGE", 413),
        ):
            response = await client.post(
                ROOT + "/documents", headers=HEADERS, files=form(payload(), raw, filename)
            )
            assert response.status_code == status and response.json()["code"] == code
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 0
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
    assert not list((management.service.storage.root / "_temporary").glob("*.part"))


@pytest.mark.integration
async def test_knowledge_management_upload_http_revocation_between_receive_and_submit(
    management: ManagementHarness,
    managed_database: Database,
    tmp_path: Path,
) -> None:
    original_authorizer = management.service.authorizer

    class RevokeAfterPreflight:
        """首次允许接收，第二次通过同一真实Client读取到权限已撤销。"""

        async def authorize(
            self,
            request: KnowledgeAuthorizationRequest,
            *,
            identity: BusinessIdentity,
            trace_id: str | None = None,
        ) -> BusinessResponse[KnowledgeAuthorizationResponse]:
            response = await original_authorizer.authorize(
                request, identity=identity, trace_id=trace_id
            )
            management.denied.add("UPLOAD")
            return response

    management.service.authorizer = RevokeAfterPreflight()
    app = create_app(Settings(environment="test"))
    app.state.knowledge_management_service = management.service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            ROOT + "/documents", headers=HEADERS, files=form(payload(), b"raw")
        )
        assert response.status_code == 403
    assert management.actions == ["UPLOAD", "UPLOAD"]
    assert not management.service.storage.root.exists()
    async with managed_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 0
