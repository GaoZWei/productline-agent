"""写响应和结果未知核对共用的确认轮次/材料校验，不产生业务事实。"""

from app.errors import ToolErrorCode, ToolException
from app.schemas.rework import ReworkWriteReceipt
from app.schemas.rework_write_tools import ReworkExecutionSnapshot


def validate_rework_receipt_binding(
    approval: ReworkExecutionSnapshot, receipt: ReworkWriteReceipt, trace_id: str
) -> None:
    """补齐HTTP Client无法获知的确认轮次、前驱及材料指针，不重建Java原结果。"""

    if approval.operation == "CREATE_LIFECYCLE_REWORK":
        return  # Client已经核对首轮1及空材料、空前驱。
    expected_round = approval.round_number
    if approval.operation == "CREATE_NEXT_REWORK":
        valid = expected_round is not None and receipt.round_number == expected_round + 1
    else:
        valid = (
            receipt.round_number == expected_round
            and receipt.previous_rework_task_id == approval.previous_rework_task_id
        )
    if approval.operation == "REGISTER_REWORK_RESULT":
        valid = valid and receipt.processing_revision == (approval.processing_revision or 0) + 1
    elif approval.operation in {"START_REWORK", "BLOCK_REWORK", "FAIL_REWORK", "RESUME_REWORK"}:
        valid = valid and (
            receipt.processing_revision,
            receipt.inspection_id,
            receipt.review_id,
        ) == (approval.processing_revision, approval.inspection_id, approval.review_id)
    elif approval.operation == "REGISTER_REWORK_INSPECTION":
        valid = valid and receipt.inspection_id != approval.inspection_id
    elif approval.operation == "SUBMIT_REWORK_REVIEW":
        valid = valid and receipt.review_id != approval.review_id
    if not valid:
        raise ToolException(
            code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
            message="Java receipt differs from confirmed bindings",
            retryable=False,
            trace_id=trace_id,
        )
