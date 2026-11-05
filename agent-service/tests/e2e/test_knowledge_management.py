"""KB-02真实Java/Agent HTTP与独立持久化卷验收，不调用模型或运行环境。"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.database import Database
from app.models import KnowledgeChunk, KnowledgeDocument
from app.models import ManagedKnowledgeChunk as Chunk
from app.models import ManagedKnowledgeDocument as Document
from app.models import ManagedKnowledgeIndexGeneration as Generation
from app.models import ManagedKnowledgeLibrary as Library
from app.models import ManagedKnowledgeOperation as Operation
from app.models import ManagedKnowledgeRevision as Revision
from app.models import ManagedKnowledgeTask as Task
from app.schemas.agent import OrderDiagnosisResponse

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "/api/agent/knowledge"
HEADERS = {"X-User-Id": "kb02-reviewer", "X-User-Role": "REVIEWER"}
pytestmark = pytest.mark.e2e


@dataclass(frozen=True)
class KnowledgeE2E:
    """地址均由隔离脚本生成，不能用本机默认服务地址代替。"""

    agent_url: str
    business_url: str
    project: str
    env_file: str
    database: Database


async def wait_health(client: httpx.AsyncClient, url: str) -> None:
    """只对启动期间的网络/非就绪结果有限等待，不触发管理或模型。"""

    for _ in range(90):
        try:
            response = await client.get(url + "/health")
            if response.status_code == 200:
                return
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.5)
    raise AssertionError("isolated service did not become healthy")


@pytest_asyncio.fixture
async def knowledge_e2e() -> AsyncIterator[KnowledgeE2E]:
    """没有专用脚本参数就跳过，禁止回退到开发或运行数据库。"""

    names = ("AGENT_URL", "BUSINESS_URL", "PROJECT", "ENV_FILE", "DATABASE_URL")
    values = {name: os.environ.get("KB02_E2E_" + name) for name in names}
    if not all(values.values()):
        pytest.skip("需要make test-knowledge-management-e2e提供独立服务")
    project = values["PROJECT"] or ""
    assert project.startswith("productline-agent-kb02-test-")
    database = Database(values["DATABASE_URL"] or "")
    assert database.engine.url.database == "knowledge_management_test"
    harness = KnowledgeE2E(
        values["AGENT_URL"] or "",
        values["BUSINESS_URL"] or "",
        project,
        values["ENV_FILE"] or "",
        database,
    )
    try:
        for service, container_port, expected_url in (
            ("agent-service", "8000", harness.agent_url),
            ("business-service", "8080", harness.business_url),
        ):
            address = urlparse(expected_url)
            assert address.scheme == "http" and address.hostname == "127.0.0.1"
            binding = await compose(harness, "port", service, container_port)
            assert address.port == int(binding.rsplit(":", 1)[1])
        binding = await compose(harness, "port", "postgres", "5432")
        assert database.engine.url.host == "127.0.0.1"
        assert database.engine.url.port == int(binding.rsplit(":", 1)[1])
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            await wait_health(client, harness.business_url)
            await wait_health(client, harness.agent_url)
        yield harness
    finally:
        await database.dispose()


async def compose(harness: KnowledgeE2E, *arguments: str) -> str:
    """只操作固定前缀的隔离项目，不继承本机COMPOSE_FILE或默认项目。"""

    process = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        "--file",
        str(ROOT / "docker-compose.yml"),
        "--project-name",
        harness.project,
        "--env-file",
        harness.env_file,
        *arguments,
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, _ = await process.communicate()
    assert process.returncode == 0, "isolated compose command failed"
    return output.decode().strip()


def command(**updates: object) -> dict[str, object]:
    """独立、显著标记的验收资料，不覆盖16份固定演示规范。"""

    return {
        "metadata": {
            "title": "KB02独立验收规范",
            "document_type": "QUALITY_SPEC",
            "specification_version": "1.0",
            "effective_date": "2030-01-01",
            "permission_scope": "INTERNAL_REVIEWER",
            "change_summary": "KB02隔离验收资料",
        },
        **updates,
    }


def form(
    payload: dict[str, object], raw: bytes, filename: str = "KB02验收.md"
) -> dict[str, tuple[None, str] | tuple[str, bytes]]:
    """JSON与原字节分别传输，BOM和CRLF应可完整下载。"""

    return {"command": (None, json.dumps(payload, ensure_ascii=False)), "file": (filename, raw)}


def revision_path(document_id: str, version_id: str, number: int, suffix: str) -> str:
    """具体修订的读取入口不隐式选择最新版。"""

    return f"{PREFIX}/documents/{document_id}/versions/{version_id}/revisions/{number}/{suffix}"


async def legacy_counts(database: Database) -> tuple[int, int]:
    """只查询Agent自有旧索引表，不能直接查询Java业务表。"""

    async with database.session() as session:
        return (
            await session.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0,
            await session.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0,
        )


async def test_knowledge_management_real_http_restart_and_golden_order(
    knowledge_e2e: KnowledgeE2E,
) -> None:
    """同一场景自建全部状态，实际重启Agent进程并核对原件、任务和Java事实。"""

    harness = knowledge_e2e
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        overview_url = harness.business_url + "/api/orders/ORDER-003/overview"
        before = await client.get(overview_url)
        assert before.status_code == 200
        facts = before.json()["data"]
        task = next(row for row in facts["tasks"] if row["task"]["taskId"] == "TASK-003")
        assert task["task"]["status"] == "COMPLETED"
        issue = next(row for row in task["qualityIssues"] if row["issue"]["issueId"] == "ISSUE-001")
        assert (
            issue["issue"]["issueType"] == "COORDINATE_SYSTEM"
            and issue["issue"]["status"] == "OPEN"
        )
        assert any(review["status"] == "PENDING" for review in issue["reviews"])
        assert any(record["status"] == "BLOCKED" for record in facts["deliveryRecords"])
        counts = await legacy_counts(harness.database)
        assert counts == (0, 0)
        capabilities = await client.get(harness.agent_url + "/api/agent/capabilities")
        assert not capabilities.json()["model"]["configured"]
        assert not capabilities.json()["knowledge_index"]["ready"]

        base = harness.agent_url
        missing = await client.get(base + PREFIX + "/documents")
        denied_headers = {**HEADERS, "X-User-Role": "ADMIN", "Idempotency-Key": "denied-upload"}
        denied = await client.post(
            base + PREFIX + "/documents", headers=denied_headers, files=form(command(), b"denied")
        )
        assert missing.status_code == 401 and denied.status_code == 403
        async with harness.database.session() as session:
            assert await session.scalar(select(func.count()).select_from(Document)) == 0

        for number, (invalid_raw, filename, status, code) in enumerate(
            (
                (b"", "empty.txt", 422, "EMPTY_DOCUMENT"),
                (b"\xff", "invalid.txt", 422, "INVALID_ENCODING"),
                (b"text", "unsupported.pdf", 415, "UNSUPPORTED_FORMAT"),
            )
        ):
            invalid = await client.post(
                base + PREFIX + "/documents",
                headers={**HEADERS, "Idempotency-Key": f"kb02-invalid-{number}"},
                files=form(command(), invalid_raw, filename),
            )
            assert invalid.status_code == status and invalid.json()["code"] == code
        async with harness.database.session() as session:
            assert await session.scalar(select(func.count()).select_from(Document)) == 0

        raw = "\ufeff# KB02独立验收规范\r\n\r\n## 条款\r\n OLD-EVIDENCE\r\n".encode()
        upload_headers = {**HEADERS, "Idempotency-Key": "kb02-first"}
        response = await client.post(
            base + PREFIX + "/documents", headers=upload_headers, files=form(command(), raw)
        )
        assert response.status_code == 201, response.text
        first = response.json()
        assert first["task_state"] == "SUCCEEDED"
        old_preview_path = revision_path(first["document_id"], first["version_id"], 1, "preview")
        old_original_path = revision_path(first["document_id"], first["version_id"], 1, "original")
        old_preview = await client.get(base + old_preview_path, headers=HEADERS)
        assert old_preview.status_code == 200 and "OLD-EVIDENCE" in old_preview.json()["body"]
        assert (await client.get(base + old_original_path, headers=HEADERS)).content == raw
        replay = await client.post(
            base + PREFIX + "/documents", headers=upload_headers, files=form(command(), raw)
        )
        assert replay.status_code == 200 and replay.json()["operation_id"] == first["operation_id"]
        conflict = await client.post(
            base + PREFIX + "/documents",
            headers=upload_headers,
            files=form(command(), b"different"),
        )
        assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

        revisions_url = (
            base
            + PREFIX
            + f"/documents/{first['document_id']}/versions/{first['version_id']}/revisions"
        )
        revised_raw = "# KB02独立验收规范\n\n## 条款\n NEW-EVIDENCE\n".encode()
        revised = await client.post(
            revisions_url,
            headers={**HEADERS, "Idempotency-Key": "kb02-revise"},
            files=form(command(expected_row_version=1, expected_revision_no=1), revised_raw),
        )
        assert revised.status_code == 201 and revised.json()["revision_no"] == 2
        second = revised.json()
        current_preview = revision_path(first["document_id"], first["version_id"], 2, "preview")
        current_original = revision_path(first["document_id"], first["version_id"], 2, "original")
        assert (
            "NEW-EVIDENCE"
            in (await client.get(base + current_preview, headers=HEADERS)).json()["body"]
        )
        stale = await client.post(
            revisions_url,
            headers={**HEADERS, "Idempotency-Key": "kb02-stale"},
            files=form(command(expected_row_version=1, expected_revision_no=1), revised_raw),
        )
        assert stale.status_code == 409

        # 预置属于旧owner的运行中记录，测试恢复规则，不冒充正在解析时的真实崩溃注入。
        async with harness.database.session() as session, session.begin():
            original_task = await session.get(Task, second["task_id"])
            assert original_task is not None
            old_owner = original_task.owner_id
            await session.execute(
                update(Revision)
                .where(Revision.version_id == first["version_id"], Revision.revision_no == 2)
                .values(body=None, normalized_hash=None)
            )
            await session.execute(
                update(Task)
                .where(Task.task_id == second["task_id"])
                .values(state="RUNNING", started_at=func.now(), finished_at=None, error_code=None)
            )
        await harness.database.dispose()
        previous_container = await compose(harness, "ps", "--quiet", "agent-service")
        await compose(harness, "up", "--detach", "--no-deps", "--force-recreate", "agent-service")
        current_container = await compose(harness, "ps", "--quiet", "agent-service")
        assert previous_container and current_container and previous_container != current_container
        binding = await compose(harness, "port", "agent-service", "8000")
        port = int(binding.rsplit(":", 1)[1])
        base = f"http://127.0.0.1:{port}"
        revisions_url = (
            base
            + PREFIX
            + f"/documents/{first['document_id']}/versions/{first['version_id']}/revisions"
        )
        await wait_health(client, base)
        task_url = base + PREFIX + "/tasks/" + second["task_id"]
        assert (await client.get(task_url, headers=HEADERS)).json()["state"] == "RUNNING"
        assert (await client.get(base + current_preview, headers=HEADERS)).status_code == 409
        assert (await client.get(base + current_original, headers=HEADERS)).content == revised_raw
        historical = await client.get(base + old_preview_path, headers=HEADERS)
        assert historical.json()["body"] == old_preview.json()["body"]
        assert not historical.json()["is_current_revision"]
        assert (await client.get(base + old_original_path, headers=HEADERS)).content == raw
        versions = await client.get(
            base + PREFIX + f"/documents/{first['document_id']}/versions", headers=HEADERS
        )
        assert versions.json()["total"] == 1
        denied = await client.post(
            base + PREFIX + "/documents", headers=denied_headers, files=form(command(), b"denied")
        )
        assert denied.status_code == 403
        assert (await client.get(task_url, headers=HEADERS)).json()["state"] == "RUNNING"

        activation = await client.post(
            base + PREFIX + "/documents",
            headers={**HEADERS, "Idempotency-Key": "kb02-activate"},
            files=form(command(), b" independent TXT evidence\r\n", "KB02验收.txt"),
        )
        assert activation.status_code == 201
        interrupted = (await client.get(task_url, headers=HEADERS)).json()
        assert (
            interrupted["state"] == "INTERRUPTED"
            and interrupted["error_code"] == "PROCESSING_INTERRUPTED"
        )
        assert not interrupted["retry_available"]
        async with harness.database.session() as session:
            operation = await session.get(Operation, second["operation_id"])
            new_task = await session.get(Task, activation.json()["task_id"])
            assert operation is not None and operation.state == "SUCCEEDED"
            assert new_task is not None and new_task.owner_id != old_owner
        corrected = await client.post(
            revisions_url,
            headers={**HEADERS, "Idempotency-Key": "kb02-correct"},
            files=form(command(expected_row_version=2, expected_revision_no=2), revised_raw),
        )
        assert corrected.status_code == 201 and corrected.json()["revision_no"] == 3
        assert (await client.get(task_url, headers=HEADERS)).json()["state"] == "INTERRUPTED"
        new_command = command(expected_row_version=3)
        metadata = new_command["metadata"]
        assert isinstance(metadata, dict)
        metadata["specification_version"] = "2.0"
        new_version = await client.post(
            base + PREFIX + f"/documents/{first['document_id']}/versions",
            headers={**HEADERS, "Idempotency-Key": "kb02-version-2"},
            files=form(new_command, revised_raw),
        )
        assert new_version.status_code == 201
        new_id = new_version.json()["version_id"]
        paths = (
            PREFIX + "/documents",
            PREFIX + f"/documents/{first['document_id']}",
            PREFIX + f"/documents/{first['document_id']}/versions",
            PREFIX + f"/documents/{first['document_id']}/versions/{new_id}",
            PREFIX + f"/documents/{first['document_id']}/tasks",
            PREFIX + "/tasks/" + new_version.json()["task_id"],
            revision_path(first["document_id"], new_id, 1, "preview"),
            revision_path(first["document_id"], new_id, 1, "original"),
        )
        for path in paths:
            allowed = await client.get(base + path, headers=HEADERS)
            assert allowed.status_code == 200
            rejected = await client.get(base + path, headers=denied_headers)
            assert rejected.status_code == 403
        assert (await client.get(base + paths[2], headers=HEADERS)).json()["total"] == 2
        assert (await client.get(base + paths[3], headers=HEADERS)).json()["metadata"][
            "specification_version"
        ] == "2.0"
        assert (await client.get(base + old_original_path, headers=HEADERS)).content == raw
        capabilities = await client.get(base + "/api/agent/capabilities")
        assert not capabilities.json()["model"]["configured"]
        assert not capabilities.json()["knowledge_index"]["ready"]
        assert await legacy_counts(harness.database) == counts
        async with harness.database.session() as session:
            library = await session.get(Library, "DEFAULT")
            assert library is not None and library.source_mode == "LEGACY"
            assert await session.scalar(select(func.count()).select_from(Generation)) == 0
            assert await session.scalar(select(func.count()).select_from(Chunk)) == 0

        diagnosis = await client.post(
            base + "/api/agent/order-diagnosis",
            headers=HEADERS,
            json={
                "order_id": "ORDER-003",
                "user_message": "这个订单为什么还没有交付？",
                "page_context": {
                    "current_system": "production-system",
                    "current_page": "order-detail",
                    "order_id": "ORDER-003",
                    "product_type": "DOM",
                    "user_role": "REVIEWER",
                },
            },
        )
        assert diagnosis.status_code == 200, diagnosis.text
        result = OrderDiagnosisResponse.model_validate_json(diagnosis.content).diagnosis
        assert result.blocking_stage.value == "QUALITY_REVIEW"
        assert {"OPEN_COORDINATE_SYSTEM_ISSUE", "REVIEW_PENDING"} == {
            cause.code for cause in result.root_causes
        }
        assert [item.action_type for item in result.suggestions] == [
            "CREATE_COORDINATE_SYSTEM_REWORK",
            "RESUBMIT_REVIEW",
        ]
        actions = " ".join(item.description for item in result.suggestions)
        assert "返工" in actions and "复核" in actions
        after = await client.get(overview_url)
        assert after.json()["data"] == facts
