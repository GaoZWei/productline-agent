"""真实管理库和原件上传后的HTTP只读查询，不调用真实模型或Java服务。"""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, insert, select, text, update

from app.database import Database
from app.main import create_app
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeTask as Task
from app.models import ManagedKnowledgeVersion as Version
from app.repositories.knowledge_management_read import KnowledgeManagementReadRepository
from app.schemas.knowledge_management import KnowledgeManagementError
from app.schemas.knowledge_management_read import KnowledgePage, KnowledgeReadQuery
from app.settings import Settings
from tests.knowledge.managed_knowledge_database import managed_database as managed_database
from tests.knowledge.managed_knowledge_fixtures import CREATED_AT, byte_chunks, generation_payload
from tests.knowledge.test_knowledge_management_persistence import (
    IDENTITY,
    ManagementHarness,
    command,
    revision_command,
)
from tests.knowledge.test_knowledge_management_persistence import (
    management as management,
)

ROOT = "/api/agent/knowledge"
HEADERS = {"X-User-Id": IDENTITY.user_id, "X-User-Role": "REVIEWER"}


@pytest.mark.integration
async def test_knowledge_management_read_http_versions_tasks_scope_and_no_writes(
    management: ManagementHarness,
    managed_database: Database,
    tmp_path: Path,
) -> None:
    first_command = command()
    first = await management.service.upload(
        first_command, byte_chunks(b"# invalid title"), identity=IDENTITY
    )
    revised = await management.service.upload(
        revision_command(first_command, first.document_id, first.version_id, first.row_version, 1),
        byte_chunks("# 测试规范\n\n## 条款\n新正文".encode()),
        identity=IDENTITY,
    )
    second_version = await management.service.upload(
        command(
            document_id=first.document_id,
            expected_row_version=revised.row_version,
            idempotency_key="new-version",
            metadata={
                **first_command.metadata.model_dump(),
                "specification_version": "2.0",
                "effective_date": date(2030, 1, 1),
            },
        ),
        byte_chunks("# 测试规范\n\n未来规范".encode()),
        identity=IDENTITY,
    )
    other = await management.service.upload(
        command(idempotency_key="other-doc"),
        byte_chunks("# 测试规范\n\n另一资料".encode()),
        identity=IDENTITY,
    )
    async with managed_database.session() as session:
        # 留一个旧owner任务, GET不得像管理激活一样把它改成INTERRUPTED。
        await session.execute(
            update(Task)
            .where(Task.task_id == other.task_id)
            .values(
                state="QUEUED",
                owner_id="WORKER-" + "A" * 32,
                started_at=None,
                finished_at=None,
                error_code=None,
            )
        )
        generation_id = "GEN-" + "7" * 32
        await session.execute(
            insert(Generation).values(
                **generation_payload(
                    generation_id=generation_id,
                    version_id=first.version_id,
                    revision_no=2,
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
                publication_state="DISABLED",
                published_revision_no=2,
                published_generation_id=generation_id,
                published_at=func.now(),
            )
        )
        await session.commit()
    async with managed_database.session() as session:
        before = (await session.execute(select(Task))).scalars().all()
        facts = [(t.task_id, t.state, t.owner_id, t.error_code) for t in before]
    app = create_app(Settings(environment="test"))
    app.state.database = managed_database
    app.state.knowledge_authorization_client = management.service.authorizer
    paths = [
        "/documents",
        f"/documents/{first.document_id}",
        f"/documents/{first.document_id}/versions",
        f"/documents/{first.document_id}/versions/{first.version_id}",
        f"/documents/{first.document_id}/tasks",
        f"/tasks/{first.task_id}",
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = [await client.get(ROOT + path, headers=HEADERS) for path in paths]
        assert [response.status_code for response in responses] == [200] * 6
        listing, detail, versions, version, tasks, task = [r.json() for r in responses]
        assert listing["total"] == 2
        assert detail["latest_version"]["version_id"] == second_version.version_id
        assert detail["latest_version"]["metadata"]["effective_date"] == "2030-01-01"
        assert versions["total"] == 2
        assert {v["publication_state"] for v in versions["items"]} == {"DISABLED", "DRAFT"}
        assert version["current_revision_no"] == 2 and version["parsed"]
        assert tasks["total"] == 3
        assert task["state"] == "FAILED" and task["error_code"] == "PARSE_FAILED"
        assert not task["is_current_revision"] and not task["retry_available"]
        serialized = json.dumps([r.json() for r in responses], ensure_ascii=False)
        for forbidden in (
            "original_key",
            "raw_hash",
            "metadata_hash",
            "body",
            "owner_id",
            "confirmation",
            "input_hash",
            "generation_id",
            "trace_id",
        ):
            assert f'"{forbidden}"' not in serialized
        assert "新正文" not in serialized and str(tmp_path) not in serialized
        paged = await client.get(ROOT + "/documents?page_size=1", headers=HEADERS)
        next_page = await client.get(ROOT + "/documents?page=2&page_size=1", headers=HEADERS)
        assert paged.json()["total"] == next_page.json()["total"] == 2
        assert (
            paged.json()["items"][0]["document_id"] != next_page.json()["items"][0]["document_id"]
        )
        empty = await client.get(
            ROOT + f"/documents/{first.document_id}/versions?page=99", headers=HEADERS
        )
        assert empty.json()["total"] == 2 and empty.json()["items"] == []
        wrong_parent = await client.get(
            ROOT + f"/documents/{other.document_id}/versions/{first.version_id}", headers=HEADERS
        )
        assert wrong_parent.status_code == 404
        missing = await client.get(ROOT + "/documents/DOC-" + "F" * 32 + "/tasks", headers=HEADERS)
        assert missing.status_code == 404
        management.denied.add("READ")
        assert (
            await client.get(ROOT + f"/tasks/{first.task_id}", headers=HEADERS)
        ).status_code == 403
    repository = KnowledgeManagementReadRepository(managed_database)
    for kind, arguments in (
        ("documents", {}),
        ("document", {"document_id": first.document_id}),
        ("versions", {"document_id": first.document_id}),
        ("version", {"document_id": first.document_id, "version_id": first.version_id}),
        ("tasks", {"document_id": first.document_id}),
        ("task", {"task_id": first.task_id}),
    ):
        query = KnowledgeReadQuery.model_validate({"kind": kind, **arguments})
        if kind == "documents":
            result = await repository.query(query, "NO_ACCESS")
            assert isinstance(result, KnowledgePage) and result.total == 0
        else:
            with pytest.raises(KnowledgeManagementError, match="RESOURCE_NOT_FOUND"):
                await repository.query(query, "NO_ACCESS")
    async with managed_database.session() as session:
        after = (await session.execute(select(Task))).scalars().all()
        assert [(t.task_id, t.state, t.owner_id, t.error_code) for t in after] == facts
        assert (
            await session.scalar(text("SELECT source_mode FROM managed_knowledge_libraries"))
            == "LEGACY"
        )
        assert (
            await session.scalar(
                text("SELECT body FROM knowledge_documents WHERE document_id='legacy-doc'")
            )
            == "旧规范哨兵"
        )
