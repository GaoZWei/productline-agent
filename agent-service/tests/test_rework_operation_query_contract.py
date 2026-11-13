"""T824跨语言查询Schema用例。不代表Client、Tool或结果未知恢复已接线。"""

import pytest
from pydantic import ValidationError

from app.schemas.rework_operation_query import (
    ReworkOperationQueryRequest,
    ReworkOperationQueryResponse,
)

pytestmark = pytest.mark.unit


def receipt() -> dict[str, object]:
    """固定首轮原回执，不按当前业务状态生成成功结果。"""

    return {
        "operation": "CREATE_LIFECYCLE_REWORK",
        "operationId": "OPERATION-T824-A",
        "taskId": "TASK-T824-A",
        "reworkTaskId": "REWORK-T824-A",
        "taskVersion": 1,
        "status": "PENDING",
        "issueStatus": "OPEN",
        "roundNumber": 1,
        "previousReworkTaskId": None,
        "processingRevision": None,
        "inspectionId": None,
        "reviewId": None,
    }


@pytest.mark.parametrize("key", ["A", "t824.scope:key-1", "a" * 128])
def test_query_preserves_original_key(key: str) -> None:
    value = ReworkOperationQueryRequest.model_validate({"idempotencyKey": key})
    assert value.idempotency_key == key
    assert value.model_dump(mode="json", by_alias=True) == {"idempotencyKey": key}


@pytest.mark.parametrize(
    "key", [None, 1, True, "", " a", "a ", "a\n", "a/b", "a?b", "中文", "a" * 129]
)
def test_query_rejects_unsafe_or_coerced_key(key: object) -> None:
    with pytest.raises(ValidationError):
        ReworkOperationQueryRequest.model_validate({"idempotencyKey": key})


@pytest.mark.parametrize("field", ["userId", "role", "confirmed", "expectedVersion", "operation"])
def test_query_refuses_caller_authority_or_business_body(field: str) -> None:
    with pytest.raises(ValidationError):
        ReworkOperationQueryRequest.model_validate({"idempotencyKey": "t824-key", field: "x"})


def test_found_result_keeps_fixed_twelve_field_original_receipt() -> None:
    raw = {"found": True, "receipt": receipt()}
    value = ReworkOperationQueryResponse.model_validate(raw)
    assert value.model_dump(mode="json", by_alias=True) == raw
    assert value.receipt is not None and value.receipt.status == "PENDING"


def test_not_found_is_explicit_null_without_invented_failure_or_retry() -> None:
    raw = {"found": False, "receipt": None}
    value = ReworkOperationQueryResponse.model_validate(raw)
    assert value.model_dump(mode="json", by_alias=True) == raw


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"found": False},
        {"receipt": None},
        {"found": "false", "receipt": None},
        {"found": 0, "receipt": None},
        {"found": True, "receipt": None},
        {"found": False, "receipt": receipt()},
        {"found": True, "receipt": {}},
        {"found": False, "receipt": None, "retryable": True},
    ],
)
def test_response_refuses_missing_coerced_or_inconsistent_fact(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReworkOperationQueryResponse.model_validate(raw)
