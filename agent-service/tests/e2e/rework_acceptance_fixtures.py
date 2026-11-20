"""M8.8专用隔离夹具，只在验收脚本独占的Java库及分离Agent库中使用。"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import asyncpg  # type: ignore[import-untyped]
import httpx
from pydantic import AnyHttpUrl
from sqlalchemy.engine import make_url

from app import main
from app.api.rework_actions import (
    CancelOutput,
    ConfirmOutput,
    NextRoundPreviewOutput,
    PreviewOutput,
    QualityPreviewOutput,
)
from app.database import Base, Database
from app.schemas.rework import ReworkAction, ReworkDetail, ReworkWriteReceipt
from app.schemas.rework_delivery import DeliveryConditions
from app.settings import Settings

_DATABASE = "business_service_test_rework_query"
_PATH = "/api/agent/rework-actions"
_TABLES = (
    "agent_sessions",
    "agent_messages",
    "agent_runs",
    "agent_steps",
    "rework_confirmation_records",
    "rework_operation_logs",
)
type AcceptancePreview = PreviewOutput | QualityPreviewOutput | NextRoundPreviewOutput


def validate_isolated_endpoints(database_url: str, java_url: str) -> None:
    """连接前拒绝非环回地址、非脚本库或附加参数，不在异常中回显连接串。"""

    try:
        db, java = urlparse(database_url), urlparse(java_url)
        valid = (
            db.scheme == "postgresql"
            and db.hostname == "127.0.0.1"
            and db.path == f"/{_DATABASE}"
            and db.username == "test"
            and db.port is not None
            and 0 < db.port < 65536
            and not db.query
            and not db.fragment
            and java.scheme == "http"
            and java.hostname == "127.0.0.1"
            and java.port is not None
            and 0 < java.port < 65536
            and java.path in {"", "/"}
            and java.username is None
            and java.password is None
            and not java.query
            and not java.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("isolated acceptance endpoints required")


@dataclass(frozen=True, slots=True)
class AcceptanceIds:
    """场景编号决定固定命名空间，不随机化业务事实，也不覆盖已有场景。"""

    case: str

    def __post_init__(self) -> None:
        """只接受M8.8任务范围内的短ASCII场景键，保证SQL标识符与业务ID安全。"""

        if (
            len(self.case) > 32
            or re.fullmatch(r"T8(?:3[6-9]|40)-[A-Z0-9]+(?:-[A-Z0-9]+)*", self.case) is None
        ):
            raise ValueError("invalid acceptance case")

    @property
    def order(self) -> str:
        """返回本场景专属订单。"""

        return f"ORDER-ACCEPT-{self.case}"

    @property
    def task(self) -> str:
        """返回已完成的原生产任务。"""

        return f"TASK-ACCEPT-{self.case}"

    @property
    def issue(self) -> str:
        """返回本场景坐标系问题。"""

        return f"ISSUE-ACCEPT-{self.case}"

    @property
    def agent_database(self) -> str:
        """每个场景使用单独Agent库，结束时只清理本次成功创建的库。"""

        return "agent_rework_accept_" + self.case.lower().replace("-", "_")


def result_materials(version: str = "001.0") -> dict[str, object]:
    """每次返回新的人工成果样例，版本与证据保留字符串，不代表真实影像处理。"""

    return {
        "artifact": {"artifactId": "acceptance-artifact", "artifactVersion": version},
        "processing_comment": "  人工修正样例，仅用于隔离验收  ",
        "evidence_references": ["fixture://rework/processing-001"],
    }


def inspection_materials(result: Literal["PASSED", "FAILED"] = "PASSED") -> dict[str, object]:
    """人工检查样例每次独立创建，结论仍需独立确认并由Java保存。"""

    return {
        "items": [
            {
                "checkItem": "坐标系统一",
                "result": result,
                "comment": "人工检查样例，仅用于隔离验收",
                "evidenceReferences": ["fixture://rework/inspection-001"],
            }
        ]
    }


@dataclass(frozen=True, slots=True)
class ReworkAcceptance:
    """组合生产页面HTTP与真实Java查询，夹具不绕过业务动作的人工确认链。"""

    ids: AcceptanceIds
    rework_id: str
    java: httpx.AsyncClient
    page: httpx.AsyncClient
    database: Database

    async def detail(self) -> ReworkDetail:
        """从Java读取本场景当前事实，不用夹具自报状态。"""

        response = await self.java.get(f"/api/tasks/{self.ids.task}/reworks/{self.rework_id}")
        assert response.status_code == 200, response.text
        value = ReworkDetail.model_validate(response.json()["data"])
        assert value.rework_task.task_id == self.ids.task
        assert value.rework_task.rework_task_id == self.rework_id
        return value

    async def preview(self, operation: ReworkAction, **materials: object) -> AcceptancePreview:
        """每个动作独立预览，版本、轮次及证据绑定全部来自服务端。"""

        response = await self.page.post(
            f"{_PATH}/preview",
            json={
                "order_id": self.ids.order,
                "command": {
                    "operation": operation,
                    "task_id": self.ids.task,
                    "rework_task_id": self.rework_id,
                    **materials,
                },
            },
        )
        assert response.status_code == 200, response.text
        model: type[AcceptancePreview] = PreviewOutput
        if operation in {"REGISTER_REWORK_INSPECTION", "SUBMIT_REWORK_REVIEW"}:
            model = QualityPreviewOutput
        elif operation == "CREATE_NEXT_REWORK":
            model = NextRoundPreviewOutput
        preview = model.model_validate_json(response.content)
        assert preview.order_id == self.ids.order
        assert preview.review.draft.operation == operation
        assert preview.review.draft.target.task_id == self.ids.task
        assert preview.review.draft.target.rework_task_id == self.rework_id
        return preview

    @staticmethod
    def approval_path(preview: AcceptancePreview) -> str:
        """保留原审批和Run地址，失败后不能通过创建新地址重发原操作。"""

        return f"{_PATH}/{preview.run_id}/{preview.approval_id}"

    async def confirm(self, preview: AcceptancePreview) -> ConfirmOutput:
        """测试显式确认原审批，不能用预览替代确认或直接调用Java写入。"""

        response = await self.page.post(
            f"{self.approval_path(preview)}/confirm",
            json={"decision": "CONFIRM"},
        )
        assert response.status_code == 200, response.text
        result = ConfirmOutput.model_validate_json(response.content)
        assert result.approval_id == preview.approval_id and result.outcome == "SUCCEEDED"
        assert result.operation_id is not None
        return result

    async def cancel(self, preview: AcceptancePreview) -> None:
        """取消仅终结原待确认审批，不推进Java业务。"""

        response = await self.page.post(f"{_PATH}/{preview.run_id}/{preview.approval_id}/cancel")
        assert response.status_code == 200, response.text
        assert CancelOutput.model_validate_json(response.content).approval_id == preview.approval_id

    async def apply(self, operation: ReworkAction, **materials: object) -> ReworkDetail:
        """核对预览零写入，再逐动作确认并读取Java事实。"""

        before = await self.detail()
        preview = await self.preview(operation, **materials)
        assert await self.detail() == before
        await self.confirm(preview)
        return await self.detail()

    async def history(
        self, kind: Literal["results", "inspections", "reviews"]
    ) -> list[dict[str, Any]]:
        """读取本场景完整的小规模历史，不从旧记录重新挑选有效结论。"""

        response = await self.java.get(
            f"/api/tasks/{self.ids.task}/reworks/{self.rework_id}/{kind}", params={"limit": 100}
        )
        assert response.status_code == 200, response.text
        page = response.json()["data"]
        assert page["taskId"] == self.ids.task and page["reworkTaskId"] == self.rework_id
        assert page["nextCursor"] is None
        records: list[dict[str, Any]] = page["records"]
        return records

    async def conditions(self) -> DeliveryConditions:
        """有效复核和交付阻塞只取Java当前快照。"""

        response = await self.java.get(f"/api/orders/{self.ids.order}/delivery-conditions")
        assert response.status_code == 200, response.text
        result = DeliveryConditions.model_validate(response.json()["data"])
        assert result.order.order_id == self.ids.order
        return result


async def _golden(java: httpx.AsyncClient) -> object:
    """保存并核对原始黄金事实，不能从测试场景回填或重置演示数据。"""

    response = await java.get("/api/orders/ORDER-003/overview")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    task = next(item for item in data["tasks"] if item["task"]["taskId"] == "TASK-003")
    assert task["task"]["status"] == "COMPLETED"
    issue = next(item for item in task["qualityIssues"] if item["issue"]["issueId"] == "ISSUE-001")
    assert issue["issue"]["issueType"] == "COORDINATE_SYSTEM"
    assert issue["issue"]["status"] == "OPEN"
    assert any(row["status"] == "PENDING" for row in issue["reviews"])
    assert any(row["status"] == "BLOCKED" for row in data["deliveryRecords"])
    return data


async def _seed(admin: asyncpg.Connection, java: httpx.AsyncClient, ids: AcceptanceIds) -> str:
    """仅插入专属订单初始事实，返工生命周期借Java真实创建，不直填新业务表。"""

    async with admin.transaction():
        await admin.execute(
            "INSERT INTO production_orders VALUES ($1,'DOM','QUALITY_CHECKING')", ids.order
        )
        await admin.execute(
            "INSERT INTO production_tasks(task_id,order_id,status,version) "
            "VALUES ($1,$2,'COMPLETED',0)",
            ids.task,
            ids.order,
        )
        await admin.execute(
            "INSERT INTO production_steps VALUES ($1,$2,'已完成生产',1,'COMPLETED')",
            f"STEP-ACCEPT-{ids.case}",
            ids.task,
        )
        await admin.execute(
            "INSERT INTO quality_issues VALUES ($1,$2,'COORDINATE_SYSTEM','OPEN','隔离验收问题')",
            ids.issue,
            ids.task,
        )
        await admin.execute(
            "INSERT INTO delivery_records VALUES ($1,$2,'BLOCKED')",
            f"DELIVERY-ACCEPT-{ids.case}",
            ids.order,
        )
    response = await java.post(
        f"/api/tasks/{ids.task}/reworks",
        json={
            "sourceIssueId": ids.issue,
            "expectedVersion": 0,
            "reason": "隔离验收首轮准备",
        },
        headers={"Idempotency-Key": f"acceptance-seed-{ids.case}"},
    )
    assert response.status_code == 200, response.text
    receipt = ReworkWriteReceipt.model_validate(response.json()["data"])
    assert receipt.task_id == ids.task and receipt.task_version == 1
    return receipt.rework_task_id


@asynccontextmanager
async def isolated_rework(
    database_url: str,
    java_url: str,
    *,
    case: str,
    storage_root: Path,
) -> AsyncIterator[ReworkAcceptance]:
    """每场景独立Agent库、固定业务命名空间，退出先关连接再删除本次Agent库。"""

    validate_isolated_endpoints(database_url, java_url)
    ids = AcceptanceIds(case)
    admin = await asyncpg.connect(database_url)
    created = False
    try:
        assert await admin.fetchval("SELECT current_database()") == _DATABASE
        # 只有通过固定字符校验的夹具名可用于DDL，不回收或覆盖已存在的库。
        await admin.execute(f'CREATE DATABASE "{ids.agent_database}"')
        created = True
        agent_url = (
            make_url(database_url)
            .set(database=ids.agent_database)
            .render_as_string(hide_password=False)
        )
        app = main.create_app(
            Settings(
                _env_file=None,
                environment="test",
                database_url=agent_url,
                business_service_url=AnyHttpUrl(java_url),
                knowledge_storage_root=storage_root,
                model_name=None,
                model_base_url=None,
                model_api_key=None,
                embedding_api_key=None,
            )
        )
        headers = {"X-User-Id": "reviewer-acceptance", "X-User-Role": "REVIEWER"}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                base_url=java_url, headers=headers, timeout=10, trust_env=False
            ) as java,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://acceptance.test",
                headers=headers,
                trust_env=False,
            ) as page,
        ):
            database: Database = app.state.database
            async with database.engine.begin() as connection:
                await connection.run_sync(
                    lambda sync: Base.metadata.create_all(
                        sync,
                        tables=[Base.metadata.tables[name] for name in _TABLES],
                    )
                )
            golden = await _golden(java)
            try:
                rework_id = await _seed(admin, java, ids)
                yield ReworkAcceptance(ids, rework_id, java, page, database)
            finally:
                assert await _golden(java) == golden
    finally:
        try:
            if created:
                await admin.execute(f'DROP DATABASE "{ids.agent_database}"')
        finally:
            await admin.close()
