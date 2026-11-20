"""现有返工轮次的页面操作入口，独立于旧审批和模型路由。"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import AwareDatetime, model_validator

from app.api.identity import resolve_business_identity
from app.database import Database
from app.errors import ToolErrorCode, ToolException
from app.models import AgentRun, AgentRunStatus, AgentSession
from app.observability import get_trace_id
from app.schemas.business import BusinessIdentity
from app.schemas.context import PageContext, PageType
from app.schemas.rework import (
    BusinessId, OrderId, ReworkInspection, ReworkProcessing, ReworkReview, ReworkSchema, TaskId,
)
from app.schemas.rework_approval import ReworkDraftReview
from app.schemas.rework_confirmation import ReworkConfirmationRequest
from app.schemas.rework_draft import ReworkDraftCommand
from app.schemas.rework_execution import ReworkExecutionReport
from app.schemas.write_tools import ApprovalIdentifier
from app.services.observed_rework import ObservedReworkService
from app.services.rework_confirmation import ReworkConfirmationError
from app.tools.models import ContextIdentifier, ToolContext

router = APIRouter(prefix="/api/agent/rework-actions", tags=["rework-actions"])

_PAGE_OPERATIONS = frozenset(
    {
        "START_REWORK",
        "BLOCK_REWORK",
        "FAIL_REWORK",
        "RESUME_REWORK",
        "REGISTER_REWORK_RESULT",
        "REGISTER_REWORK_INSPECTION",
        "SUBMIT_REWORK_REVIEW",
        "CREATE_NEXT_REWORK",
    }
)
_PERMISSIONS = frozenset({"TASK_READ", "REWORK_READ", "REWORK_WRITE", "REVIEW_WRITE"})


class PreviewInput(ReworkSchema):
    """页面仅提供定位和本次人工材料，实际订单、版本和轮次由Java核对。"""

    order_id: OrderId
    command: ReworkDraftCommand

    @model_validator(mode="after")
    def page_operation(self) -> Self:
        """仅开放当前页面支持的操作。"""

        if self.command.operation not in _PAGE_OPERATIONS:
            raise ValueError("operation is outside the rework page scope")
        return self


class PreviewOutput(ReworkSchema):
    """只返回供人审查的草稿和有效期。"""

    run_id: ContextIdentifier
    approval_id: ApprovalIdentifier
    order_id: OrderId
    expires_at: AwareDatetime
    review: ReworkDraftReview


class BoundQualityMaterials(ReworkSchema):
    """预览所保存的Java证据。再次复核同时展示同修订检查。"""

    processing: ReworkProcessing
    inspection: ReworkInspection | None


class QualityPreviewOutput(PreviewOutput):
    """人工检查及复核额外返回本审批绑定的成果和检查证据。"""

    bound_materials: BoundQualityMaterials


class NextRoundPreviewOutput(PreviewOutput):
    """新一轮独立审批展示上一轮绑定的复核原文。"""

    previous_review: ReworkReview


class ConfirmInput(ReworkSchema):
    """显式人工决定，只确认服务端保存的原草稿。"""

    decision: Literal["CONFIRM"]


class ConfirmOutput(ReworkSchema):
    """仅返回执行判定和已保存回执的操作编号。"""

    approval_id: ApprovalIdentifier
    outcome: Literal["SUCCEEDED", "IN_PROGRESS", "UNKNOWN"]
    operation_id: BusinessId | None
    next_rework_task_id: BusinessId | None = None
    error_code: ToolErrorCode | None = None


class ReconcileInput(ReworkSchema):
    """恢复结果时核对当前页面与原审批的资源绑定。"""

    order_id: OrderId
    task_id: TaskId
    rework_task_id: BusinessId


class NotSubmittedOutput(ReworkSchema):
    """区分尚待确认和已经结束且未领取执行权的审批。"""

    approval_id: ApprovalIdentifier
    outcome: Literal["WAITING_CONFIRMATION", "NOT_SUBMITTED"]
    operation_id: None = None


class CancelOutput(ReworkSchema):
    """返回已取消审批的定位信息。"""

    approval_id: ApprovalIdentifier
    status: Literal["CANCELLED"] = "CANCELLED"


def _error(code: str, status: int) -> HTTPException:
    """响应只包含机器码和请求Trace，材料、异常正文与执行键不出边界。"""

    return HTTPException(status_code=status, detail={"code": code, "trace_id": get_trace_id()})


def _tool_error(error: ToolException) -> HTTPException:
    """本地返工状态冲突沿用409，Java已提供的HTTP状态直接保留。"""

    status = error.status_code or (409 if error.code is ToolErrorCode.BUSINESS_CONFLICT else 502)
    return _error(error.code.value, status)


def _reviewer(request: Request) -> BusinessIdentity:
    """复用现有网关身份约定，明确限制在复核角色。"""

    identity = resolve_business_identity(
        user_id=request.headers.get("X-User-Id"),
        user_role=request.headers.get("X-User-Role"),
        authorization=request.headers.get("Authorization"),
    )
    if identity is None:
        raise _error("PERMISSION_DENIED", 401)
    if identity.role != "REVIEWER":
        raise _error("PERMISSION_DENIED", 403)
    return identity


_Reviewer = Annotated[BusinessIdentity, Depends(_reviewer)]


def _service(request: Request, identity: BusinessIdentity, run_id: str) -> ObservedReworkService:
    """使用应用共享Client及服务端权限，页面无法自报执行上下文。"""

    return ObservedReworkService(
        request.app.state.database,
        request.app.state.business_client,
        context=ToolContext(
            identity=identity, permissions=_PERMISSIONS, trace_id=get_trace_id(), run_id=run_id
        ),
        approval_ttl_seconds=request.app.state.settings.approval_ttl_seconds,
    )


@router.post("/preview", response_model=QualityPreviewOutput | NextRoundPreviewOutput | PreviewOutput)
async def preview_rework_action(
    request: Request, identity: _Reviewer, body: Annotated[object, Body()]
) -> PreviewOutput:
    """创建专属Run并重新读取Java，校验页面订单归属后保存审批。"""

    try:
        command = PreviewInput.model_validate(body)
    except ValueError:
        raise _error("PARAM_VALIDATION_ERROR", 400) from None
    run_id, session_id = f"rework-page-{uuid4().hex}", f"rework-session-{uuid4().hex}"
    now = datetime.now(UTC)
    database: Database = request.app.state.database
    page = PageContext(
        current_system="production-system",
        current_page=PageType.TASK_DETAIL,
        order_id=command.order_id,
        task_id=command.command.task_id,
        user_role=identity.role,
    )
    async with database.session() as session, session.begin():
        session.add(AgentSession(
            session_id=session_id,
            user_id=identity.user_id,
            expires_at=now + timedelta(seconds=request.app.state.settings.session_ttl_seconds),
        ))
        await session.flush()
        session.add(AgentRun(
            run_id=run_id,
            session_id=session_id,
            status=AgentRunStatus.RUNNING,
            started_at=now,
            version_snapshot=request.app.state.run_version_snapshot.model_dump(mode="json"),
            page_context_snapshot=page.model_dump(mode="json"),
        ))
    try:
        snapshot = await _service(request, identity, run_id).create(
            command.command, expected_order_id=command.order_id
        )
    except ReworkConfirmationError as error:
        raise _error(error.code, error.status_code) from None
    except ToolException as error:
        raise _tool_error(error) from None
    preview = PreviewOutput(
        run_id=run_id, approval_id=snapshot.approval_id, order_id=snapshot.prepared.order_id,
        expires_at=snapshot.expires_at, review=snapshot.prepared.review,
    )
    operation = preview.review.draft.operation
    detail = snapshot.prepared.current_rework
    if operation == "CREATE_NEXT_REWORK":
        if detail is None or detail.review is None:
            raise _error("RESPONSE_VALIDATION_ERROR", 500)
        return NextRoundPreviewOutput(
            run_id=preview.run_id,
            approval_id=preview.approval_id,
            order_id=preview.order_id,
            expires_at=preview.expires_at,
            review=preview.review,
            previous_review=detail.review,
        )
    if operation not in {"REGISTER_REWORK_INSPECTION", "SUBMIT_REWORK_REVIEW"}:
        return preview
    if detail is None or detail.processing is None:
        raise _error("RESPONSE_VALIDATION_ERROR", 500)
    inspection = detail.inspection if operation == "SUBMIT_REWORK_REVIEW" else None
    if operation == "SUBMIT_REWORK_REVIEW" and inspection is None:
        raise _error("RESPONSE_VALIDATION_ERROR", 500)
    return QualityPreviewOutput(
        run_id=preview.run_id,
        approval_id=preview.approval_id,
        order_id=preview.order_id,
        expires_at=preview.expires_at,
        review=preview.review,
        bound_materials=BoundQualityMaterials(processing=detail.processing, inspection=inspection),
    )


@router.post("/{run_id}/{approval_id}/confirm", response_model=ConfirmOutput)
async def confirm_rework_action(
    run_id: ContextIdentifier,
    approval_id: ApprovalIdentifier,
    request: Request,
    identity: _Reviewer,
    body: Annotated[object, Body()],
) -> ConfirmOutput:
    """显式确认能且只能执行当前审批，重复确认无法重新发送。"""

    try:
        ConfirmInput.model_validate(body)
    except ValueError:
        raise _error("PARAM_VALIDATION_ERROR", 400) from None
    service = _service(request, identity, run_id)
    try:
        snapshot = await service.get_approval(approval_id)
        draft = snapshot.prepared.review.draft
        if draft.operation not in _PAGE_OPERATIONS:
            raise _error("RESOURCE_NOT_FOUND", 404)
        await service.confirm(ReworkConfirmationRequest(approval_id=approval_id, draft=draft))
        result = await service.execute({"approval_id": approval_id})
    except ReworkConfirmationError as error:
        raise _error(error.code, error.status_code) from None
    except ToolException as error:
        raise _tool_error(error) from None
    return _execution_output(result)


def _execution_output(result: ReworkExecutionReport) -> ConfirmOutput:
    """只从已校验回执读取操作编号和后继返工编号。"""

    receipt = result.receipt_evidence.receipt if result.receipt_evidence else None
    return ConfirmOutput(
        approval_id=result.approval_id,
        outcome=result.outcome,
        operation_id=receipt.operation_id if receipt else None,
        next_rework_task_id=(
            receipt.rework_task_id if receipt and receipt.operation == "CREATE_NEXT_REWORK" else None
        ),
        error_code=result.error.code if result.error else None,
    )


@router.post("/{run_id}/{approval_id}/reconcile", response_model=ConfirmOutput | NotSubmittedOutput)
async def reconcile_rework_action(
    run_id: ContextIdentifier,
    approval_id: ApprovalIdentifier,
    request: Request,
    identity: _Reviewer,
    body: Annotated[object, Body()],
) -> ConfirmOutput | NotSubmittedOutput:
    """用户主动核对原审批。已提交时只查询原键，从不走写入或重发。"""

    try:
        target = ReconcileInput.model_validate(body)
    except ValueError:
        raise _error("PARAM_VALIDATION_ERROR", 400) from None
    service = _service(request, identity, run_id)
    try:
        snapshot = await service.get_approval(approval_id)
        draft = snapshot.prepared.review.draft
        if (
            draft.operation not in _PAGE_OPERATIONS
            or snapshot.prepared.order_id != target.order_id
            or draft.target.task_id != target.task_id
            or draft.target.rework_task_id != target.rework_task_id
        ):
            raise _error("RESOURCE_NOT_FOUND", 404)
        snapshot = await service.expire_unclaimed(snapshot)
        if snapshot.status in {"CANCELLED", "EXPIRED", "STALE"}:
            return NotSubmittedOutput(approval_id=approval_id, outcome="NOT_SUBMITTED")
        if snapshot.status == "WAITING_CONFIRMATION":
            return NotSubmittedOutput(approval_id=approval_id, outcome="WAITING_CONFIRMATION")
        if snapshot.status == "CONFIRMED" or (
            snapshot.status == "EXECUTING" and snapshot.submission_started_at is None
        ):
            return ConfirmOutput(approval_id=approval_id, outcome="IN_PROGRESS", operation_id=None)
        return _execution_output(await service.reconcile({"approval_id": approval_id}))
    except ReworkConfirmationError as error:
        raise _error(error.code, error.status_code) from None
    except ToolException as error:
        raise _tool_error(error) from None


@router.post("/{run_id}/{approval_id}/cancel", response_model=CancelOutput)
async def cancel_rework_action(
    run_id: ContextIdentifier, approval_id: ApprovalIdentifier, request: Request, identity: _Reviewer
) -> CancelOutput:
    """取消尚待确认的原审批，取消路径无业务写入。"""

    service = _service(request, identity, run_id)
    try:
        snapshot = await service.get_approval(approval_id)
        if snapshot.prepared.review.draft.operation not in _PAGE_OPERATIONS:
            raise _error("RESOURCE_NOT_FOUND", 404)
        await service.cancel(approval_id)
    except ReworkConfirmationError as error:
        raise _error(error.code, error.status_code) from None
    except ToolException as error:
        raise _tool_error(error) from None
    return CancelOutput(approval_id=approval_id)
