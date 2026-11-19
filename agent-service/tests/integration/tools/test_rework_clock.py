"""返工写入及原键查询使用同一受信时钟，不通过修改期限或跳过校验适配测试。"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode
from app.schemas.rework_write_tools import ReworkExecutionSnapshot
from app.tools.rework_operation_query import QueryReworkOperationTool
from app.tools.rework_write import create_rework_write_tool_registry
from tests.integration.tools.test_rework_write_tools import (
    INPUT,
    START,
    FakeStore,
    context,
    receipt,
    response,
    shared,
    snapshot,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
NOW = datetime(2050, 6, 1, tzinfo=UTC)


def approval(
    *, confirmed: datetime | None = None, expires: datetime | None = None
) -> ReworkExecutionSnapshot:
    """固定远期时钟证明读取的不是宿主机时间，业务ID/材料保持既有确定性夹具。"""

    raw = snapshot().model_dump(mode="python")
    raw.update(
        confirmed_at=confirmed or NOW - timedelta(seconds=1),
        expires_at=expires or NOW + timedelta(minutes=10),
    )
    return ReworkExecutionSnapshot.model_validate(raw)


@pytest.mark.parametrize("query", [False, True])
@pytest.mark.parametrize("state", ["valid", "future", "naive", "expired"])
async def test_rework_tool_clock_preserves_permission_and_time_boundaries(
    query: bool, state: str
) -> None:
    calls: list[httpx.Request] = []
    value = approval(
        confirmed=NOW + timedelta(seconds=1) if state == "future" else None,
        expires=NOW if state == "expired" else None,
    )
    clock = NOW.replace(tzinfo=None) if state == "naive" else NOW
    store = FakeStore(value)

    def handler(request: httpx.Request) -> httpx.Response:
        """只有通过时间门禁才能到达HTTP，查询不能消费写许可。"""

        calls.append(request)
        return response({"found": True, "receipt": receipt()} if query else receipt())

    client = shared(httpx.MockTransport(handler))
    try:
        adapter = ReworkHttpClient(client)
        tool = (
            QueryReworkOperationTool(adapter, store, now=lambda: clock)
            if query
            else create_rework_write_tool_registry(adapter, store, now=lambda: clock).get(
                START.name
            )
        )
        result = await tool.execute(INPUT, context("REWORK_READ" if query else "REWORK_WRITE"))
        allowed = state == "valid" or (query and state == "expired")
        if allowed:
            assert result.success and len(calls) == 1
        else:
            assert result.error is not None and not calls
            assert result.error.code == (
                ToolErrorCode.RESPONSE_VALIDATION_ERROR
                if state == "naive"
                else ToolErrorCode.BUSINESS_CONFLICT
            )
        assert bool(getattr(store, "submitted", False)) == (allowed and not query)
    finally:
        await client.aclose()


@pytest.mark.parametrize("query", [False, True])
async def test_default_rework_clock_still_rejects_future_confirmation(query: bool) -> None:
    """未显式注入时保留真实UTC门禁，不因可测试时钟而默认信任未来确认。"""

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response(receipt())

    client = shared(httpx.MockTransport(handler))
    try:
        adapter, store = ReworkHttpClient(client), FakeStore(approval())
        tool = (
            QueryReworkOperationTool(adapter, store)
            if query
            else create_rework_write_tool_registry(adapter, store).get(START.name)
        )
        result = await tool.execute(INPUT, context("REWORK_READ" if query else "REWORK_WRITE"))
        assert result.error is not None and result.error.code == ToolErrorCode.BUSINESS_CONFLICT
        assert not calls and not getattr(store, "submitted", False)
    finally:
        await client.aclose()
