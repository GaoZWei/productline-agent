"""Approval草稿保存、用户修改和确定性状态流转。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from app.models import (
    ApprovalRecord,
    ApprovalStatus,
    OperationType,
    PendingToolName,
)

_APPROVAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_TASK_ID_PATTERN = re.compile(r"^TASK-[A-Z0-9][A-Z0-9-]*$")
# 映射操作类型到待调用的 Tool 名称
_OPERATION_TO_TOOL = {
    OperationType.SUBMIT_REVIEW: PendingToolName.WRITE_REVIEW_RESULT,
    OperationType.CREATE_REWORK: PendingToolName.CREATE_REWORK_TASK,
}
# 核心状态机定义，描述Approval状态之间的合法转换！
_ALLOWED_TRANSITIONS = {
    ApprovalStatus.DRAFT: frozenset(
        {ApprovalStatus.WAITING_CONFIRMATION, ApprovalStatus.CANCELLED}
    ),
    ApprovalStatus.WAITING_CONFIRMATION: frozenset(
        {
            ApprovalStatus.CONFIRMED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.STALE,
        }
    ),
    ApprovalStatus.CONFIRMED: frozenset(
        {ApprovalStatus.EXECUTING, ApprovalStatus.EXPIRED, ApprovalStatus.STALE}
    ),
    ApprovalStatus.EXECUTING: frozenset({ApprovalStatus.SUCCEEDED, ApprovalStatus.FAILED}),
    ApprovalStatus.SUCCEEDED: frozenset(),
    ApprovalStatus.FAILED: frozenset(),
    ApprovalStatus.CANCELLED: frozenset(),
    ApprovalStatus.EXPIRED: frozenset(),
    ApprovalStatus.STALE: frozenset(),
}


class ApprovalRepositoryProtocol(Protocol):
    """生命周期服务依赖的最小Repository接口, 便于隔离测试状态机。"""

    async def create(self, approval: ApprovalRecord) -> ApprovalRecord: ...

    async def get(self, approval_id: str) -> ApprovalRecord | None: ...

    async def transition_status(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        target_status: ApprovalStatus,
        changes: Mapping[str, Any],
    ) -> ApprovalRecord | None: ...

    async def save_user_modified_draft(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        draft: dict[str, Any],
        updated_at: datetime,
    ) -> ApprovalRecord | None: ...


class ApprovalLifecycleError(Exception):
    """Approval生命周期错误基类。"""

# Approval不存在错误
class ApprovalNotFoundError(ApprovalLifecycleError):
    """目标Approval不存在。"""

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(f"approval '{approval_id}' was not found")

# 状态不允许跳转，或者当前状态不允许修改内容
class InvalidApprovalTransitionError(ApprovalLifecycleError):
    """当前状态不允许目标状态或内容修改。"""

    def __init__(
        self,
        *,
        approval_id: str,
        current_status: ApprovalStatus,
        target_status: ApprovalStatus,
    ) -> None:
        self.approval_id = approval_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"approval '{approval_id}' cannot transition from "
            f"{current_status.value} to {target_status.value}"
        )

# ID标识、JSON、目标版本、Tool映射、时间等输入不合法错误
class ApprovalLifecycleValidationError(ApprovalLifecycleError):
    """草稿、标识、目标版本或确认信息不满足持久化边界。"""

    def __init__(self, *, field_name: str, message: str) -> None:
        self.field_name = field_name
        self.message = message
        super().__init__(f"{field_name}: {message}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ApprovalLifecycleService:
    """创建可审查草稿并执行无跳步、可并发校验的Approval状态机。"""

    def __init__(
        self,
        repository: ApprovalRepositoryProtocol,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._now = now
    # 创建草稿 create_draft()
    async def create_draft(
        self,
        *,
        approval_id: str,
        run_id: str,
        operation_type: OperationType,
        original_draft: dict[str, Any],
        pending_tool_name: PendingToolName,
        target_id: str,
        target_version: int,
    ) -> ApprovalRecord:
        """创建DRAFT记录; 这里只保存写操作意图, 不执行待调用Tool。"""
        # 规范化标识符
        normalized_approval_id = self._identifier(approval_id, "approval_id")
        normalized_run_id = self._identifier(run_id, "run_id")
        normalized_target_id = self._identifier(target_id, "target_id")
        # 校验目标任务是否有效
        if _TASK_ID_PATTERN.fullmatch(normalized_target_id) is None:
            raise ApprovalLifecycleValidationError(
                field_name="target_id",
                message="must be a valid production task identifier",
            )
        # 校验目标版本是否有效
        if (
            isinstance(target_version, bool)
            or target_version < 0
            or target_version > 9_223_372_036_854_775_807
        ):
            raise ApprovalLifecycleValidationError(
                field_name="target_version",
                message="must be a nonnegative signed 64-bit integer",
            )
        # 校验操作和Tool映射是否一致
        expected_tool = _OPERATION_TO_TOOL[operation_type]
        if pending_tool_name is not expected_tool:  # 防止确认内容与最终执行Tool不一致
            raise ApprovalLifecycleValidationError(
                field_name="pending_tool_name",
                message=f"must be {expected_tool.value} for {operation_type.value}",
            )
        draft_snapshot = self._json_snapshot(original_draft, "original_draft")
        return await self._repository.create(
            ApprovalRecord(
                approval_id=normalized_approval_id,
                run_id=normalized_run_id,
                status=ApprovalStatus.DRAFT,
                operation_type=operation_type,
                original_draft=draft_snapshot,
                user_modified_draft=None,
                pending_tool_name=pending_tool_name,
                target_id=normalized_target_id,
                target_version=target_version,
                confirmed_by_user_id=None,
                confirmed_at=None,
            )
        )

    async def mark_waiting_confirmation(self, approval_id: str) -> ApprovalRecord:
        """草稿准备完成后进入等待用户确认。"""
        # 只有 WAITING_CONFIRMATION 可以修改状态
        return await self._transition(approval_id, ApprovalStatus.WAITING_CONFIRMATION)
    # 确认后调用保存用户修改副本
    async def save_user_modification(
        self,
        approval_id: str,
        *,
        modified_draft: dict[str, Any],
    ) -> ApprovalRecord:
        """只保存用户修改副本, 原始Agent草稿保持不变。"""

        normalized_id = self._identifier(approval_id, "approval_id")
        snapshot = self._json_snapshot(modified_draft, "modified_draft")
        updated = await self._repository.save_user_modified_draft(
            normalized_id,
            expected_status=ApprovalStatus.WAITING_CONFIRMATION,
            draft=snapshot,
            updated_at=self._timestamp(),
        )
        if updated is not None:
            return updated
        current = await self._require_current(normalized_id)
        raise InvalidApprovalTransitionError(
            approval_id=normalized_id,
            current_status=current.status,
            target_status=ApprovalStatus.WAITING_CONFIRMATION,
        )
    # 记录真实确认人和确认时间，状态变更为 CONFIRMED
    async def confirm(self, approval_id: str, *, confirmed_by_user_id: str) -> ApprovalRecord:
        """记录真实确认人和确认时间, 但尚不执行Java写操作。"""

        normalized_user_id = self._identifier(confirmed_by_user_id, "confirmed_by_user_id")
        confirmed_at = self._timestamp()
        return await self._transition(
            approval_id,
            ApprovalStatus.CONFIRMED,
            changes={
                "confirmed_by_user_id": normalized_user_id,
                "confirmed_at": confirmed_at,
                "updated_at": confirmed_at,
            },
        )

    async def mark_executing(self, approval_id: str) -> ApprovalRecord:
        """确认后、真正调用写Tool前进入执行中。"""

        return await self._transition(approval_id, ApprovalStatus.EXECUTING)

    async def mark_succeeded(self, approval_id: str) -> ApprovalRecord:
        return await self._transition(approval_id, ApprovalStatus.SUCCEEDED)

    async def mark_failed(self, approval_id: str) -> ApprovalRecord:
        return await self._transition(approval_id, ApprovalStatus.FAILED)

    async def cancel(self, approval_id: str) -> ApprovalRecord:
        return await self._transition(approval_id, ApprovalStatus.CANCELLED)

    async def mark_expired(self, approval_id: str) -> ApprovalRecord:
        return await self._transition(approval_id, ApprovalStatus.EXPIRED)

    async def mark_stale(self, approval_id: str) -> ApprovalRecord:
        return await self._transition(approval_id, ApprovalStatus.STALE)
    # 执行阶段优先使用用户修改副本, 否则使用原始Agent草稿
    @staticmethod
    def effective_draft(approval: ApprovalRecord) -> dict[str, Any]:
        """执行阶段优先使用用户修改副本, 否则使用原始Agent草稿。"""

        value = (
            approval.user_modified_draft
            if approval.user_modified_draft is not None
            else approval.original_draft
        )
        return ApprovalLifecycleService._json_snapshot(value, "effective_draft")

    async def _transition(
        self,
        approval_id: str,
        target_status: ApprovalStatus,
        *,
        changes: Mapping[str, Any] | None = None,
    ) -> ApprovalRecord:
        normalized_id = self._identifier(approval_id, "approval_id")
        current = await self._require_current(normalized_id)
        if target_status not in _ALLOWED_TRANSITIONS[current.status]:
            raise InvalidApprovalTransitionError(
                approval_id=normalized_id,
                current_status=current.status,
                target_status=target_status,
            )
        transition_changes = dict(changes or {})
        if "updated_at" not in transition_changes:
            transition_changes["updated_at"] = self._timestamp()
        transitioned = await self._repository.transition_status(
            normalized_id,
            expected_status=current.status,
            target_status=target_status,
            changes=transition_changes,
        )
        if transitioned is not None:
            return transitioned
        latest = await self._require_current(normalized_id)
        raise InvalidApprovalTransitionError(
            approval_id=normalized_id,
            current_status=latest.status,
            target_status=target_status,
        )

    async def _require_current(self, approval_id: str) -> ApprovalRecord:
        current = await self._repository.get(approval_id)
        if current is None:
            raise ApprovalNotFoundError(approval_id)
        return current

    def _timestamp(self) -> datetime:
        timestamp = self._now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ApprovalLifecycleValidationError(
                field_name="timestamp",
                message="must include timezone information",
            )
        return timestamp

    @staticmethod
    def _identifier(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 128:
            raise ApprovalLifecycleValidationError(
                field_name=field_name,
                message="must contain between 1 and 128 characters",
            )
        if (
            field_name in {"approval_id", "run_id"}
            and _APPROVAL_ID_PATTERN.fullmatch(normalized) is None
        ):
            raise ApprovalLifecycleValidationError(
                field_name=field_name,
                message="contains unsupported characters",
            )
        return normalized

    @staticmethod
    def _json_snapshot(value: dict[str, Any], field_name: str) -> dict[str, Any]:
        if not value:
            raise ApprovalLifecycleValidationError(
                field_name=field_name,
                message="must not be empty",
            )
        try:  # 冻结原始原始草稿内容
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
            return cast(dict[str, Any], json.loads(serialized))
        except (TypeError, ValueError) as exception:
            raise ApprovalLifecycleValidationError(
                field_name=field_name,
                message="must contain only standard JSON values",
            ) from exception
