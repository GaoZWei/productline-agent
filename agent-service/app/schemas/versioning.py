"""Run 可复现性所需的组件版本快照契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

VersionIdentifier = Annotated[str, Field(min_length=1, max_length=128)]
Sha256Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

# 版本快照状态
class VersionCaptureStatus(StrEnum):
    """区分新 Run 的完整快照与迁移前无法还原的历史记录。"""

    CAPTURED = "CAPTURED"  # 这是新代码创建的 Run，所有版本信息都已完整保存
    UNAVAILABLE_LEGACY = "UNAVAILABLE_LEGACY"  # 这是数据库迁移前已经存在的 Run，无法确定当时真正使用的版本


class VersionSnapshotSchema(BaseModel):
    """所有版本对象使用严格、不可变且禁止额外字段的共同边界。"""

    model_config = ConfigDict(
        extra="forbid",  # 禁止出现未定义字段
        frozen=True,  # 禁止修改已定义字段
        strict=True,  # 不做宽松类型转换
        str_strip_whitespace=True,  # 去除字符串首尾空格
    )

# 模型配置记录
class ModelRuntimeSnapshot(VersionSnapshotSchema):
    """记录决策模型配置, 不保存密钥、地址或完整 Prompt。"""

    configured: bool
    provider: VersionIdentifier | None
    model_name: VersionIdentifier | None
    parameters: dict[str, bool | int | float | str]
    # 校验逻辑：已配置状态必须有供应商和模型名, 未配置状态不得伪留参数
    @model_validator(mode="after")
    def validate_configuration_state(self) -> Self:
        """已配置状态必须有供应商和模型名, 未配置状态不得伪留参数。"""

        if self.configured:
            if self.provider is None or self.model_name is None:
                raise ValueError("configured model requires provider and model_name")
        elif self.provider is not None or self.model_name is not None or self.parameters:
            raise ValueError("unconfigured model must not contain runtime configuration")
        return self


class ToolSchemaSnapshot(VersionSnapshotSchema):
    """用显式目录版本和实际 Schema 摘要共同标识 Tool 契约。"""

    version: VersionIdentifier
    digest: Sha256Digest
    tool_names: tuple[VersionIdentifier, ...]


class RagStrategySnapshot(VersionSnapshotSchema):
    """记录检索策略及其与 Embedding 索引有关的非敏感参数。"""

    version: VersionIdentifier
    embedding_provider: VersionIdentifier
    embedding_model: VersionIdentifier
    embedding_index_version: VersionIdentifier
    parameters: dict[str, bool | int | float | str]

# Run 版本快照
class RunVersionSnapshot(VersionSnapshotSchema):
    """在 Run 创建时一次性冻结的跨组件版本集合。"""

    schema_version: Literal["run-version-snapshot-v1"] = "run-version-snapshot-v1"
    capture_status: VersionCaptureStatus
    router_prompt_version: VersionIdentifier | None
    agent_prompt_version: VersionIdentifier | None
    model: ModelRuntimeSnapshot | None
    tool_schema: ToolSchemaSnapshot | None
    rag_strategy: RagStrategySnapshot | None
    # 校验逻辑：新快照必须字段齐全; 历史占位只能明确表示版本不可恢复
    @model_validator(mode="after")
    def require_complete_captured_snapshot(self) -> Self:
        """新快照必须字段齐全; 历史占位只能明确表示版本不可恢复。"""

        components: tuple[Any, ...] = (
            self.router_prompt_version,
            self.agent_prompt_version,
            self.model,
            self.tool_schema,
            self.rag_strategy,
        )
        if self.capture_status is VersionCaptureStatus.CAPTURED:  # 新快照必须字段齐全，不允许半完整保存
            if any(component is None for component in components):
                raise ValueError("captured version snapshot requires every component")
        elif any(component is not None for component in components):
            raise ValueError("legacy version snapshot must not invent unavailable versions")
        return self


def legacy_run_version_snapshot() -> RunVersionSnapshot:
    """为迁移前 Run 返回诚实的不可恢复占位, 而不是补造历史版本。"""

    return RunVersionSnapshot(
        capture_status=VersionCaptureStatus.UNAVAILABLE_LEGACY,
        router_prompt_version=None,
        agent_prompt_version=None,
        model=None,
        tool_schema=None,
        rag_strategy=None,
    )
