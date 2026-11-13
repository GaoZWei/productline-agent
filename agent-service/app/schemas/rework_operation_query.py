"""T824原回执查询契约，查无回执保留未知结果，不赋予重发或确认权限。"""

import re
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from app.schemas.rework import ReworkSchema, ReworkWriteReceipt
from app.schemas.rework_write_tools import ReworkWriteInput
from app.schemas.write_tools import ApprovalIdentifier, JavaTraceIdentifier


class ReworkOperationQueryRequest(ReworkSchema):
    """查询正文只接受原幂等键，不接受身份、业务正文或新的写授权。"""

    idempotency_key: str = Field(alias="idempotencyKey")

    @field_validator("idempotency_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        """按Java完整匹配保留原键，不能strip或接受尾随换行。"""

        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) is None:
            raise ValueError("idempotency key must contain 1 to 128 safe characters")
        return value


class ReworkOperationQueryResponse(ReworkSchema):
    """首次成功原回执或显式缺失。found=false不能证明Java未提交。"""

    found: bool
    receipt: ReworkWriteReceipt | None

    @model_validator(mode="after")
    def validate_presence(self) -> Self:
        """只承认Java返回的成功回执，禁止缺失字段或矛盾的成功标记。"""

        if self.found != (self.receipt is not None):
            raise ValueError("found must match the presence of an original receipt")
        return self


class ReworkOperationLookupInput(ReworkWriteInput):
    """只接受原确认单及原键，不允许模型覆盖查询任务或材料。"""

    @field_validator("idempotency_key")
    @classmethod
    def validate_original_key(cls, value: str) -> str:
        """在公共指纹和读取Store之前拒绝尾随换行等非法原键。"""

        return ReworkOperationQueryRequest(idempotency_key=value).idempotency_key


class ReworkOperationResolution(ReworkSchema):
    """核对只输出原回执匹配或未知，不代表当前状态或授权业务重发。"""

    approval_id: ApprovalIdentifier
    outcome: Literal["MATCHED_RECEIPT", "UNKNOWN"]
    receipt: ReworkWriteReceipt | None
    java_trace_id: JavaTraceIdentifier

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """未知必须显式无回执，错误不能被伪装成未知或失败事实。"""

        if (self.outcome == "MATCHED_RECEIPT") != (self.receipt is not None):
            raise ValueError("resolution outcome must match receipt presence")
        return self
