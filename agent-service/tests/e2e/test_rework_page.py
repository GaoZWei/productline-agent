"""T831用独占Java库准备页面事实，随后运行真实前端Client及生产代理验收。"""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def test_rework_page_reads_real_java_through_web_proxy() -> None:
    """只在隔离库造两轮及分页材料，页面查询不得再推进业务状态。"""

    db = os.getenv("AGENT_REWORK_QUERY_TEST_DATABASE_URL")
    url = os.getenv("AGENT_REWORK_QUERY_TEST_BUSINESS_URL")
    if db is None or url is None:
        pytest.skip("通过make test-rework-page启动独占Java/PostgreSQL")
    assert urlparse(db).hostname == "127.0.0.1"
    assert urlparse(db).path == "/business_service_test_rework_query"
    assert urlparse(url).hostname == "127.0.0.1"
    connection = await asyncpg.connect(db)
    try:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO production_orders VALUES ('ORDER-T831-E2E','DOM','QUALITY_CHECKING')"
            )
            await connection.execute(
                "INSERT INTO production_tasks(task_id,order_id,status,version) "
                "VALUES ('TASK-T831-E2E','ORDER-T831-E2E','COMPLETED',0)"
            )
            await connection.execute(
                "INSERT INTO quality_issues VALUES "
                "('ISSUE-T831-E2E','TASK-T831-E2E','COORDINATE_SYSTEM','OPEN','页面只读验收')"
            )
        headers = {"X-User-Id": "reviewer-t831", "X-User-Role": "REVIEWER"}
        version = 0
        actions = 0
        async with httpx.AsyncClient(
            base_url=url, headers=headers, timeout=10, trust_env=False
        ) as client:
            golden = (await client.get("/api/orders/ORDER-003/overview")).json()
            base = "/api/tasks/TASK-T831-E2E/reworks"

            async def write(path: str, body: dict[str, object]) -> dict[str, object]:
                """测试准备显式调用Java，不作为页面可写能力或人工确认验收。"""

                nonlocal version, actions
                actions += 1
                response = await client.post(
                    path,
                    json={"expectedVersion": version, **body},
                    headers={"Idempotency-Key": f"t831-page-fixture-{actions}"},
                )
                assert response.status_code == 200, response.text
                data: dict[str, object] = response.json()["data"]
                assert isinstance(data["taskVersion"], int)
                version = data["taskVersion"]
                return data

            first = await write(base, {"sourceIssueId": "ISSUE-T831-E2E", "reason": "第一轮"})
            first_id = str(first["reworkTaskId"])
            path = f"{base}/{first_id}"
            await write(f"{path}/start", {})
            for revision in range(1, 23):
                await write(
                    f"{path}/results",
                    {
                        "artifact": {"artifactId": "原件-001", "artifactVersion": "001.0"},
                        "processingComment": f"  人工处理修订{revision}  ",
                        "evidenceReferences": ["evidence://原件/001"],
                    },
                )
                if revision == 1:
                    await write(
                        f"{path}/inspections",
                        {
                            "processingRevision": revision,
                            "items": [
                                {
                                    "checkItem": "坐标系",
                                    "result": "FAILED",
                                    "comment": "人工检查未通过",
                                    "evidenceReferences": ["evidence://失败"],
                                }
                            ],
                        },
                    )
            inspected = await write(
                f"{path}/inspections",
                {
                    "processingRevision": 22,
                    "items": [
                        {
                            "checkItem": "坐标系",
                            "result": "PASSED",
                            "comment": "人工检查通过",
                            "evidenceReferences": ["evidence://通过"],
                        }
                    ],
                },
            )
            await write(
                f"{path}/review",
                {
                    "processingRevision": 22,
                    "inspectionId": inspected["inspectionId"],
                    "status": "REWORK_REQUIRED",
                    "reviewComment": "退回再处理",
                },
            )
            second = await write(f"{path}/next-round", {"reason": "第二轮"})
            second_id = str(second["reworkTaskId"])
            path = f"{base}/{second_id}"
            await write(f"{path}/start", {})
            await write(
                f"{path}/results",
                {
                    "artifact": {"artifactId": "原件-001", "artifactVersion": "002.0"},
                    "processingComment": "第二轮已人工修正",
                    "evidenceReferences": ["evidence://原件/002"],
                },
            )
            await write(
                f"{path}/inspections",
                {
                    "processingRevision": 1,
                    "items": [
                        {
                            "checkItem": "坐标系",
                            "result": "PASSED",
                            "comment": "等待再次复核",
                            "evidenceReferences": ["evidence://通过/002"],
                        }
                    ],
                },
            )
            root = Path(__file__).resolve().parents[3]
            process = await asyncio.create_subprocess_exec(
                "npm",
                "test",
                "--",
                "--run",
                "src/api/reworkPage.e2e.spec.mjs",
                cwd=root / "agent-frontend",
                env={**os.environ, "REWORK_PAGE_TEST_IDS": f"{first_id},{second_id}"},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=90)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, output.decode()
            assert "1 passed" in output.decode() and "1 skipped" not in output.decode()
            after = (await client.get(f"/api/tasks/TASK-T831-E2E/reworks/{second_id}")).json()
            assert after["data"]["taskVersion"] == version
            assert (await client.get("/api/orders/ORDER-003/overview")).json()["data"] == golden[
                "data"
            ]
    finally:
        await connection.close()
