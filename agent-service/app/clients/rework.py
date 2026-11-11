"""M8专用Java HTTP适配器：借用连接池，不管理Approval、不选有效复核、不重试写入。"""

import re
from collections.abc import Callable, Mapping
from typing import NoReturn

from pydantic import TypeAdapter, ValidationError

from app.clients.business import BusinessHttpClient
from app.errors import ToolErrorCode, ToolException
from app.observability import get_trace_id, resolve_trace_id
from app.schemas.business import BusinessIdentity, BusinessResponse
from app.schemas.rework import (
    Actor,
    CreateLifecycleReworkRequest,
    EffectiveReworkReviews,
    OrderId,
    RegisterReworkInspectionRequest,
    RegisterReworkResultRequest,
    ReworkDetail,
    ReworkHistoryPage,
    ReworkInspection,
    ReworkOperation,
    ReworkPageQuery,
    ReworkProcessing,
    ReworkReasonRequest,
    ReworkResource,
    ReworkReview,
    ReworkSchema,
    ReworkVersionRequest,
    ReworkWriteReceipt,
    SubmitReworkReviewRequest,
    TaskId,
)
from app.schemas.rework_delivery import DeliveryConditions


class ReworkHttpClient:
    """只暴露已有Java端点的强类型调用，连接池仍由外层lifespan创建和关闭。"""

    def __init__(self, business_client: BusinessHttpClient) -> None:
        """构造不发请求、不启动任务，也不注册或授权任何Tool。"""

        self._business = business_client

    async def get_detail(
        self, task_id: str, rework_task_id: str, *, identity: BusinessIdentity,
        trace_id: str | None = None,
    ) -> BusinessResponse[ReworkDetail]:
        """读取详情并核对父任务及返工身份，不把allowedActions当作确认。"""

        trace = self._context(identity, trace_id)
        resource = self._resource(task_id, rework_task_id, trace)
        response = await self._get(self._base(resource), ReworkDetail, identity, trace)
        self._ensure(response.data.rework_task.task_id == resource.task_id
                     and response.data.rework_task.rework_task_id == resource.rework_task_id, trace)
        return response

    async def get_results(
        self, task_id: str, rework_task_id: str, *, identity: BusinessIdentity,
        page: ReworkPageQuery | None = None, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkHistoryPage[ReworkProcessing]]:
        """只读取一页处理历史，保留空集合及原始修订顺序。"""

        return await self._history(task_id, rework_task_id, "results", ReworkHistoryPage[ReworkProcessing],
                                   lambda row: row.processing_revision, identity, page, trace_id)

    async def get_inspections(
        self, task_id: str, rework_task_id: str, *, identity: BusinessIdentity,
        page: ReworkPageQuery | None = None, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkHistoryPage[ReworkInspection]]:
        """读取真实检查历史，失败结论保留，不自动翻页或选取通过。"""

        return await self._history(task_id, rework_task_id, "inspections", ReworkHistoryPage[ReworkInspection],
                                   lambda row: row.inspection_sequence, identity, page, trace_id)

    async def get_reviews(
        self, task_id: str, rework_task_id: str, *, identity: BusinessIdentity,
        page: ReworkPageQuery | None = None, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkHistoryPage[ReworkReview]]:
        """读取完整复核历史，不将历史数组重新计算为有效结论。"""

        return await self._history(task_id, rework_task_id, "reviews", ReworkHistoryPage[ReworkReview],
                                   lambda row: row.review_sequence, identity, page, trace_id)

    async def get_effective_reviews(
        self, task_id: str, *, identity: BusinessIdentity, trace_id: str | None = None,
    ) -> BusinessResponse[EffectiveReworkReviews]:
        """读取Java已经裁决的当前绑定；不接受任意过滤器。"""

        trace = self._context(identity, trace_id)
        try:
            task = TypeAdapter[str](TaskId).validate_python(task_id, strict=True)
        except ValidationError:
            self._invalid(trace)
        response = await self._get(f"/api/tasks/{task}/effective-reviews", EffectiveReworkReviews,
                                   identity, trace)
        self._ensure(response.data.task_id == task, trace)
        return response

    async def get_delivery_conditions(
        self, order_id: str, *, identity: BusinessIdentity, trace_id: str | None = None,
    ) -> BusinessResponse[DeliveryConditions]:
        """保留同一订单快照和Java阻塞代码，不生成交付资格或改变状态。"""

        trace = self._context(identity, trace_id)
        try:
            order = TypeAdapter[str](OrderId).validate_python(order_id, strict=True)
        except ValidationError:
            self._invalid(trace)
        response = await self._get(f"/api/orders/{order}/delivery-conditions", DeliveryConditions,
                                   identity, trace)
        self._ensure(response.data.order.order_id == order, trace)
        return response

    async def create_first(
        self, task_id: str, request: CreateLifecycleReworkRequest, *, identity: BusinessIdentity,
        idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """调用受控首轮新路径，不改变旧CREATE_REWORK的行为。"""

        return await self._write(task_id, None, "CREATE_LIFECYCLE_REWORK", request,
                                 CreateLifecycleReworkRequest, identity, idempotency_key, trace_id)

    async def start(
        self, task_id: str, rework_task_id: str, request: ReworkVersionRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """调用开始端点，身份和幂等不是人工确认凭证。"""

        return await self._write(task_id, rework_task_id, "START_REWORK", request,
                                 ReworkVersionRequest, identity, idempotency_key, trace_id)

    async def block(
        self, task_id: str, rework_task_id: str, request: ReworkReasonRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """提交本次阻塞原因，既有创建原因不在请求中覆盖。"""

        return await self._write(task_id, rework_task_id, "BLOCK_REWORK", request,
                                 ReworkReasonRequest, identity, idempotency_key, trace_id)

    async def fail(
        self, task_id: str, rework_task_id: str, request: ReworkReasonRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """提交本次失败原因，不启动生产重跑或下一轮。"""

        return await self._write(task_id, rework_task_id, "FAIL_REWORK", request,
                                 ReworkReasonRequest, identity, idempotency_key, trace_id)

    async def resume(
        self, task_id: str, rework_task_id: str, request: ReworkReasonRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """只调用人工恢复端点，保留原样说明。"""

        return await self._write(task_id, rework_task_id, "RESUME_REWORK", request,
                                 ReworkReasonRequest, identity, idempotency_key, trace_id)

    async def register_result(
        self, task_id: str, rework_task_id: str, request: RegisterReworkResultRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """登记新处理修订，不由Python补造修订或通过结论。"""

        return await self._write(task_id, rework_task_id, "REGISTER_REWORK_RESULT", request,
                                 RegisterReworkResultRequest, identity, idempotency_key, trace_id)

    async def register_inspection(
        self, task_id: str, rework_task_id: str, request: RegisterReworkInspectionRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """传递已审查的人工项，校验Java回执包含通过后的原子完成副作用。"""

        return await self._write(task_id, rework_task_id, "REGISTER_REWORK_INSPECTION", request,
                                 RegisterReworkInspectionRequest, identity, idempotency_key, trace_id)

    async def submit_review(
        self, task_id: str, rework_task_id: str, request: SubmitReworkReviewRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """调用绑定当前成果/检查的新复核路径，不调用旧review端点。"""

        return await self._write(task_id, rework_task_id, "SUBMIT_REWORK_REVIEW", request,
                                 SubmitReworkReviewRequest, identity, idempotency_key, trace_id)

    async def create_next(
        self, task_id: str, rework_task_id: str, request: ReworkReasonRequest, *,
        identity: BusinessIdentity, idempotency_key: str, trace_id: str | None = None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """独立调用后继创建，只核对Java分配的前驱/新身份，不代替确认流程。"""

        return await self._write(task_id, rework_task_id, "CREATE_NEXT_REWORK", request,
                                 ReworkReasonRequest, identity, idempotency_key, trace_id)

    async def _history[RecordT: ReworkProcessing | ReworkInspection | ReworkReview](
        self, task_id: str, rework_id: str, suffix: str,
        page_type: type[ReworkHistoryPage[RecordT]],
        sequence: Callable[[RecordT], int], identity: BusinessIdentity,
        page: ReworkPageQuery | None, trace_id: str | None,
    ) -> BusinessResponse[ReworkHistoryPage[RecordT]]:
        """共用一页调用和归属校验，不自动重试、翻页或合并不同快照。"""

        trace = self._context(identity, trace_id)
        resource = self._resource(task_id, rework_id, trace)
        query = self._parse(ReworkPageQuery, {} if page is None else page, trace)
        params = {"limit": str(query.limit)}
        if query.cursor is not None:
            params["cursor"] = query.cursor
        response = await self._get(f"{self._base(resource)}/{suffix}",
                                   page_type, identity, trace, params)
        data = response.data
        sequences = [sequence(row) for row in data.records]
        self._ensure(data.task_id == resource.task_id and data.rework_task_id == resource.rework_task_id
                     and len(data.records) <= query.limit
                     and all(a < b for a, b in zip(sequences, sequences[1:], strict=False))
                     and (data.next_cursor is None or data.next_cursor != query.cursor), trace)
        rounds: set[int] = set()
        record_ids: list[str] = []
        for row in data.records:
            if isinstance(row, ReworkInspection):
                rounds.add(row.round_number)
                record_ids.append(row.inspection_id)
            elif isinstance(row, ReworkReview):
                rounds.add(row.round_number)
                record_ids.append(row.review_id)
        self._ensure(len(rounds) <= 1, trace)
        self._ensure(len(record_ids) == len(set(record_ids)), trace)
        return response

    async def _get[DataT](
        self, path: str, response_type: type[DataT], identity: BusinessIdentity, trace: str,
        params: Mapping[str, str] | None = None,
    ) -> BusinessResponse[DataT]:
        """只发送一次请求，并要求Java信封Trace绑定本次请求。"""

        response = await self._business.get(path, response_type, identity=identity,
                                            trace_id=trace, params=params)
        self._ensure(response.trace_id == trace, trace)
        return response

    async def _write[RequestT: ReworkVersionRequest](
        self, task_id: str, rework_id: str | None, operation: ReworkOperation,
        request: RequestT, request_type: type[RequestT], identity: BusinessIdentity,
        key: str, trace_id: str | None,
    ) -> BusinessResponse[ReworkWriteReceipt]:
        """固定操作映射只发送一次；任何不确定写结果禁止共享重试策略重发。"""

        trace = self._context(identity, trace_id)
        try:
            task = TypeAdapter[str](TaskId).validate_python(task_id, strict=True)
            validated = self._parse(request_type, request, trace)
            if not isinstance(key, str) or not _valid_key(key):
                self._invalid(trace)
        except ValidationError:
            self._invalid(trace)
        path = f"/api/tasks/{task}/reworks"
        if operation != "CREATE_LIFECYCLE_REWORK":
            resource = self._resource(task, rework_id, trace)
            suffix = {
                "START_REWORK": "start", "BLOCK_REWORK": "block", "FAIL_REWORK": "fail",
                "RESUME_REWORK": "resume", "REGISTER_REWORK_RESULT": "results",
                "REGISTER_REWORK_INSPECTION": "inspections", "SUBMIT_REWORK_REVIEW": "review",
                "CREATE_NEXT_REWORK": "next-round",
            }[operation]
            path = f"{self._base(resource)}/{suffix}"
        try:
            response = await self._business.post(path, ReworkWriteReceipt,
                json_body=validated.model_dump(mode="json", by_alias=True), identity=identity,
                trace_id=trace, idempotency_key=key)
            data = response.data
            self._ensure(response.trace_id == trace and data.operation == operation
                         and data.task_id == task and data.task_version == validated.expected_version + 1, trace)
            if operation == "CREATE_NEXT_REWORK":
                self._ensure(data.previous_rework_task_id == rework_id and data.rework_task_id != rework_id, trace)
            elif operation != "CREATE_LIFECYCLE_REWORK":
                self._ensure(data.rework_task_id == rework_id, trace)
            self._write_binding(operation, validated, data, trace)
            return response
        except ToolException as exc:
            if exc.retryable:
                raise ToolException(code=exc.code, message="rework write did not return a confirmed receipt",
                    retryable=False, trace_id=exc.trace_id, status_code=exc.status_code) from None
            raise

    def _write_binding(
        self, operation: ReworkOperation, request: ReworkVersionRequest,
        receipt: ReworkWriteReceipt, trace: str,
    ) -> None:
        """只核对本操作已定义的回执副作用，不按后来GET重建原成功回执。"""

        states = {
            "START_REWORK": ("RUNNING", "PROCESSING"), "BLOCK_REWORK": ("BLOCKED", "PROCESSING"),
            "FAIL_REWORK": ("FAILED", "PROCESSING"), "RESUME_REWORK": ("RUNNING", "PROCESSING"),
            "REGISTER_REWORK_RESULT": ("RUNNING", "PROCESSING"),
            "CREATE_LIFECYCLE_REWORK": ("PENDING", "OPEN"), "CREATE_NEXT_REWORK": ("PENDING", "OPEN"),
        }
        if operation in states:
            self._ensure((receipt.status, receipt.issue_status) == states[operation], trace)
        if operation in ("CREATE_LIFECYCLE_REWORK", "CREATE_NEXT_REWORK"):
            self._ensure(receipt.processing_revision is None and receipt.inspection_id is None
                         and receipt.review_id is None, trace)
            if operation == "CREATE_LIFECYCLE_REWORK":
                self._ensure(receipt.round_number == 1, trace)
        elif isinstance(request, RegisterReworkResultRequest):
            self._ensure(receipt.processing_revision is not None and receipt.inspection_id is None
                         and receipt.review_id is None, trace)
        elif isinstance(request, RegisterReworkInspectionRequest):
            passed = all(item.result == "PASSED" for item in request.items)
            self._ensure((receipt.status, receipt.issue_status) == (
                ("COMPLETED", "RESOLVED") if passed else ("RUNNING", "PROCESSING")
            ) and receipt.processing_revision == request.processing_revision
                and receipt.inspection_id is not None and receipt.review_id is None, trace)
        elif isinstance(request, SubmitReworkReviewRequest):
            self._ensure(receipt.status == "COMPLETED" and receipt.issue_status == (
                "CLOSED" if request.status == "APPROVED" else "OPEN"
            ) and receipt.processing_revision == request.processing_revision
                and receipt.inspection_id == request.inspection_id and receipt.review_id is not None, trace)

    @staticmethod
    def _context(identity: BusinessIdentity, trace_id: str | None) -> str:
        """固定一次调用Trace，身份仍由Java最终判断，不在此签发权限。"""

        candidate = trace_id or get_trace_id()
        trace = resolve_trace_id(None if candidate == "-" else candidate)
        if not isinstance(identity, BusinessIdentity):
            ReworkHttpClient._invalid(trace)
        try:
            TypeAdapter[str](Actor).validate_python(identity.user_id)
            TypeAdapter[str](Actor).validate_python(identity.role)
        except ValidationError:
            ReworkHttpClient._invalid(trace)
        return trace

    @staticmethod
    def _resource(task: str, rework: str | None, trace: str) -> ReworkResource:
        """完整校验路径资源，拒绝外部URL、路径和小写ID。"""

        return ReworkHttpClient._parse(ReworkResource, {"taskId": task, "reworkTaskId": rework}, trace)

    @staticmethod
    def _base(resource: ReworkResource) -> str:
        """只从已校验ID构造固定Java路径。"""

        return f"/api/tasks/{resource.task_id}/reworks/{resource.rework_task_id}"

    @staticmethod
    def _parse[ModelT: ReworkSchema](kind: type[ModelT], value: object, trace: str) -> ModelT:
        """把Schema失败统一转换为不回显材料的参数错误。"""

        try:
            raw = value.model_dump(mode="python", by_alias=True) if isinstance(value, ReworkSchema) else value
            return kind.model_validate(raw)
        except ValidationError:
            ReworkHttpClient._invalid(trace)

    @staticmethod
    def _invalid(trace: str) -> NoReturn:
        """参数无效时不访问Java，也不把证据写入错误文案。"""

        raise ToolException(code=ToolErrorCode.PARAM_VALIDATION_ERROR,
                            message="rework request input is invalid", retryable=False, trace_id=trace)

    @staticmethod
    def _ensure(condition: bool, trace: str) -> None:
        """格式合法但归属、Trace或动作不匹配同样不能作为业务事实返回。"""

        if not condition:
            raise ToolException(code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                message="rework response binding is invalid", retryable=False, trace_id=trace,
                status_code=200)


def _valid_key(key: str) -> bool:
    """严格匹配幂等键，末尾换行也不能进入Header。"""

    return re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key) is not None
