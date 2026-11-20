"""隔离验收夹具的连接门禁、固定命名空间和材料边界，不连接数据库。"""

from pathlib import Path

import pytest

from app.schemas.rework_draft import parse_rework_draft_command
from tests.e2e.rework_acceptance_fixtures import (
    AcceptanceIds,
    inspection_materials,
    isolated_rework,
    result_materials,
    validate_isolated_endpoints,
)

_DB = "postgresql://test:test-only@127.0.0.1:54321/business_service_test_rework_query"
_JAVA = "http://127.0.0.1:54322"


@pytest.mark.parametrize(
    "db,java",
    [
        (_DB.replace("127.0.0.1", "production.example"), _JAVA),
        (_DB.replace("business_service_test_rework_query", "remote_sensing_agent"), _JAVA),
        (_DB.replace("postgresql:", "postgres:"), _JAVA),
        (_DB.replace("test:test-only", "admin:secret"), _JAVA),
        (_DB + "?target_session_attrs=read-write", _JAVA),
        (_DB + "#fragment", _JAVA),
        (_DB.replace(":54321", ":bad"), _JAVA),
        (_DB.replace(":54321", ":0"), _JAVA),
        (_DB, "https://127.0.0.1:54322"),
        (_DB, "http://production.example:54322"),
        (_DB, _JAVA + "/api"),
        (_DB, _JAVA + "?other=1"),
        (_DB, _JAVA + "#other"),
        (_DB, "http://user:secret@127.0.0.1:54322"),
        (_DB, "http://127.0.0.1:70000"),
    ],
)
@pytest.mark.asyncio
async def test_rework_acceptance_rejects_endpoints_before_connecting(
    db: str,
    java: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """误配置时在任何数据库调用前拒绝，错误不回显口令或地址。"""

    def forbidden_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not connect")

    monkeypatch.setattr("tests.e2e.rework_acceptance_fixtures.asyncpg.connect", forbidden_connect)
    with pytest.raises(ValueError, match=r"^isolated acceptance endpoints required$"):
        async with isolated_rework(db, java, case="T836-UNIT", storage_root=tmp_path):
            pytest.fail("invalid endpoints must not enter fixture")


@pytest.mark.parametrize(
    "case", ["T835-OLD", "T841-FUTURE", "t836-lower", "T836-X;DROP", "T836-A\n", "T836-" + "A" * 33]
)
def test_rework_acceptance_rejects_unsafe_case(case: str) -> None:
    """DDL和业务资源均不能接受未经校验的场景名。"""

    with pytest.raises(ValueError, match=r"^invalid acceptance case$"):
        AcceptanceIds(case)


def test_rework_acceptance_materials_are_independent_and_match_real_command_schema() -> None:
    """固定夹具重复产生同值新材料，修改上一份不污染下一场景。"""

    validate_isolated_endpoints(_DB, _JAVA)
    first, second = AcceptanceIds("T836-ONE"), AcceptanceIds("T836-TWO")
    assert first == AcceptanceIds("T836-ONE")
    assert first.order != second.order and first.agent_database != second.agent_database
    assert len(first.agent_database) < 63 and len(first.issue) < 64
    result = result_materials()
    expected = result_materials()
    assert result == expected and result is not expected
    artifact = result["artifact"]
    assert isinstance(artifact, dict)
    artifact["artifactVersion"] = "changed"
    assert result_materials() == expected
    for operation, materials in [
        ("REGISTER_REWORK_RESULT", result_materials()),
        ("REGISTER_REWORK_INSPECTION", inspection_materials("PASSED")),
        ("REGISTER_REWORK_INSPECTION", inspection_materials("FAILED")),
    ]:
        command = parse_rework_draft_command(
            {
                "operation": operation,
                "task_id": first.task,
                "rework_task_id": "REWORK-ACCEPT",
                **materials,
            }
        )
        assert command.model_dump(mode="json")["operation"] == operation
