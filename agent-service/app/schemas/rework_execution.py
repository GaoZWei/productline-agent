"""T829原回执证据与执行结果，明确区分写入Trace和后续查询Trace。"""

from typing import Literal, Self

from pydantic import model_validator

from app.schemas.rework import ReworkSchema, ReworkWriteReceipt
from app.schemas.write_tools import ApprovalIdentifier, JavaTraceIdentifier
from app.tools.models import ToolError


class ReworkReceiptEvidence(ReworkSchema):
    """Java原成功回执，查询命中不能伪装成知道首次写请求Trace。"""

    approval_id: ApprovalIdentifier
    receipt: ReworkWriteReceipt
    source: Literal["WRITE", "LOOKUP"]
    write_java_trace_id: JavaTraceIdentifier | None
    lookup_java_trace_id: JavaTraceIdentifier | None

    @model_validator(mode="after")
    def trace_source(self) -> Self:
        """每种来源只保留实际观察到的Trace，缺失不能补造。"""

        if self.source == "WRITE":
            valid = self.write_java_trace_id is not None and self.lookup_java_trace_id is None
        else:
            valid = self.lookup_java_trace_id is not None and self.write_java_trace_id is None
        if not valid:
            raise ValueError("receipt trace does not match its observation source")
        return self


class ReworkExecutionInput(ReworkSchema):
    """执行或核对只定位已确认审查，不允许调用方设置键、目标或确认事实。"""

    approval_id: ApprovalIdentifier


class ReworkExecutionReport(ReworkSchema):
    """返回已保存事实或未决状态，没有重发授权或当前业务状态推测。"""

    approval_id: ApprovalIdentifier
    outcome: Literal["SUCCEEDED", "IN_PROGRESS", "UNKNOWN"]
    receipt_evidence: ReworkReceiptEvidence | None
    error: ToolError | None

    @model_validator(mode="after")
    def receipt_presence(self) -> Self:
        """只有可核对的原回执才能报告成功，成功结果不携带旧错误。"""

        if (self.outcome == "SUCCEEDED") != (self.receipt_evidence is not None):
            raise ValueError("execution outcome differs from receipt evidence")
        if self.receipt_evidence is not None and (
            self.receipt_evidence.approval_id != self.approval_id or self.error is not None
        ):
            raise ValueError("execution result identity or error is inconsistent")
        return self
