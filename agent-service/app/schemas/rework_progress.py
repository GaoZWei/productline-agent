"""返工状态审计及SSE共用的固定摘要，禁止把数据库JSON当作可信事件。"""

from typing import Literal, Self

from pydantic import JsonValue, model_validator

from app.errors import ToolErrorCode
from app.schemas.rework import BusinessId, ReworkOperation, ReworkSchema, SafeVersion
from app.schemas.rework_confirmation import ReworkConfirmationStatus
from app.schemas.tools import ProductionStatus
from app.schemas.write_tools import ApprovalIdentifier, JavaTraceIdentifier

type ReworkProgressPhase = Literal[
    "WAITING_CONFIRMATION",
    "CONFIRMED",
    "CANCELLED",
    "EXPIRED",
    "STALE",
    "CLAIMED",
    "SUBMITTING",
    "UNKNOWN",
    "SUCCEEDED",
]

_RECEIPT_FIELDS = frozenset(
    {
        "receipt_source",
        "receipt_operation_id",
        "receipt_status",
        "write_java_trace_id",
        "lookup_java_trace_id",
    }
)


class ReworkProgressSummary(ReworkSchema):
    """约束字段、状态和真实Trace来源，不接受请求材料或任意错误正文。"""

    approval_id: ApprovalIdentifier
    revision: SafeVersion
    operation: ReworkOperation
    status: ReworkConfirmationStatus
    phase: ReworkProgressPhase
    error_code: ToolErrorCode | None
    receipt_source: Literal["WRITE", "LOOKUP"] | None = None
    receipt_operation_id: BusinessId | None = None
    receipt_status: ProductionStatus | None = None
    write_java_trace_id: JavaTraceIdentifier | None = None
    lookup_java_trace_id: JavaTraceIdentifier | None = None

    @model_validator(mode="after")
    def consistent_progress(self) -> Self:
        """未知结果不能伪装成终态，核对Trace不能冒充原写Trace。"""

        if self.status == "EXECUTING":
            valid = self.phase in {"CLAIMED", "SUBMITTING", "UNKNOWN"} and (
                (self.phase == "UNKNOWN") == (self.error_code is not None)
            )
        else:
            valid = self.phase == self.status and self.error_code is None
        if not valid:
            raise ValueError("progress phase does not match its status")
        provided = self.model_fields_set & _RECEIPT_FIELDS
        if self.status != "SUCCEEDED":
            if provided:
                raise ValueError("unfinished progress cannot contain receipt fields")
            return self
        if provided != _RECEIPT_FIELDS or any(
            value is None
            for value in (
                self.receipt_source,
                self.receipt_operation_id,
                self.receipt_status,
            )
        ):
            raise ValueError("successful progress requires receipt metadata")
        if self.receipt_source == "WRITE":
            valid = self.write_java_trace_id is not None and self.lookup_java_trace_id is None
        else:
            valid = self.lookup_java_trace_id is not None and self.write_java_trace_id is None
        if not valid:
            raise ValueError("progress trace does not match its receipt source")
        return self

    def event_data(self) -> dict[str, JsonValue]:
        """重新序列化受控字段，保留旧事件中非成功状态不含回执字段的形状。"""

        return self.model_dump(mode="json", exclude_unset=True)
