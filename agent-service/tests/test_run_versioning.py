"""M5.7 Run 版本快照的确定性与安全边界测试。"""

from collections.abc import Mapping

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr

from app.routing.prompt import ROUTER_PROMPT_VERSION
from app.schemas.versioning import (
    RunVersionSnapshot,
    VersionCaptureStatus,
    legacy_run_version_snapshot,
)
from app.settings import Settings
from app.tools import BaseTool, ToolContext, ToolRegistry, ToolRiskLevel
from app.versioning import (
    RAG_STRATEGY_VERSION,
    TOOL_SCHEMA_VERSION,
    build_run_version_snapshot,
)
from app.workflows.action_prompt import ACTION_DECISION_PROMPT_VERSION


class _SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _TextInput(_SchemaModel):
    value: str


class _TextOutput(_SchemaModel):
    result: str


class _NumericInput(_SchemaModel):
    value: int


class _SchemaTool(BaseTool[BaseModel, _TextOutput]):
    def __init__(self, *, name: str, input_model: type[BaseModel]) -> None:
        super().__init__(
            name=name,
            description="用于验证版本摘要的只读Tool",
            input_model=input_model,
            output_model=_TextOutput,
            risk_level=ToolRiskLevel.LOW,
            required_permissions=frozenset({"ORDER_READ"}),
            timeout=1.0,
            max_retries=0,
        )

    async def _execute(
        self,
        tool_input: BaseModel,
        context: ToolContext,
    ) -> _TextOutput | Mapping[str, object]:
        return _TextOutput(result="ok")


def _registry(*tools: _SchemaTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


@pytest.mark.unit
def test_version_snapshot_records_all_components_without_inventing_model() -> None:
    settings = Settings(
        environment="test",
        model_name="",
        embedding_api_key=SecretStr("do-not-persist"),
    )
    snapshot = build_run_version_snapshot(
        settings,
        _registry(_SchemaTool(name="read_order", input_model=_TextInput)),
    )

    assert snapshot.capture_status is VersionCaptureStatus.CAPTURED
    assert snapshot.router_prompt_version == ROUTER_PROMPT_VERSION
    assert snapshot.agent_prompt_version == ACTION_DECISION_PROMPT_VERSION
    assert snapshot.model is not None
    assert snapshot.model.configured is False
    assert snapshot.model.provider is None
    assert snapshot.model.model_name is None
    assert snapshot.model.parameters == {}
    assert snapshot.tool_schema is not None
    assert snapshot.tool_schema.version == TOOL_SCHEMA_VERSION
    assert snapshot.rag_strategy is not None
    assert snapshot.rag_strategy.version == RAG_STRATEGY_VERSION
    assert snapshot.rag_strategy.embedding_index_version == settings.embedding_index_version
    serialized = snapshot.model_dump_json()
    assert "do-not-persist" not in serialized
    assert "api_key" not in serialized
    assert "base_url" not in serialized


@pytest.mark.unit
def test_configured_model_name_and_non_sensitive_parameters_are_frozen() -> None:
    snapshot = build_run_version_snapshot(
        Settings(
            environment="test",
            model_provider="provider-a",
            model_name="decision-model-v2",
            model_temperature=0.2,
            model_max_output_tokens=4096,
        ),
        _registry(),
    )

    assert snapshot.model is not None
    assert snapshot.model.configured is True
    assert snapshot.model.provider == "provider-a"
    assert snapshot.model.model_name == "decision-model-v2"
    assert snapshot.model.parameters == {
        "temperature": 0.2,
        "max_output_tokens": 4096,
    }


@pytest.mark.unit
def test_tool_schema_digest_is_order_independent_and_changes_with_contract() -> None:
    first = _SchemaTool(name="alpha_tool", input_model=_TextInput)
    second = _SchemaTool(name="beta_tool", input_model=_TextInput)
    forward = build_run_version_snapshot(
        Settings(environment="test"),
        _registry(first, second),
    )
    reverse = build_run_version_snapshot(
        Settings(environment="test"),
        _registry(
            _SchemaTool(name="beta_tool", input_model=_TextInput),
            _SchemaTool(name="alpha_tool", input_model=_TextInput),
        ),
    )
    changed = build_run_version_snapshot(
        Settings(environment="test"),
        _registry(
            _SchemaTool(name="alpha_tool", input_model=_NumericInput),
            _SchemaTool(name="beta_tool", input_model=_TextInput),
        ),
    )

    assert forward.tool_schema is not None
    assert reverse.tool_schema is not None
    assert changed.tool_schema is not None
    assert forward.tool_schema.tool_names == ("alpha_tool", "beta_tool")
    assert forward.tool_schema.digest == reverse.tool_schema.digest
    assert forward.tool_schema.digest != changed.tool_schema.digest


@pytest.mark.unit
def test_legacy_snapshot_does_not_fabricate_historical_versions() -> None:
    snapshot = legacy_run_version_snapshot()

    assert snapshot.capture_status is VersionCaptureStatus.UNAVAILABLE_LEGACY
    assert snapshot.router_prompt_version is None
    assert snapshot.agent_prompt_version is None
    assert snapshot.model is None
    assert snapshot.tool_schema is None
    assert snapshot.rag_strategy is None
    assert RunVersionSnapshot.model_validate(snapshot.model_dump()) == snapshot
