"""M3.1 页面上下文Schema与页面资源层级约束测试。"""

import pytest
from pydantic import ValidationError

from app.schemas import PageContext, PageType


def test_order_detail_page_context_is_strict() -> None:
    context = PageContext.model_validate(
        {
            "current_system": "production-system",
            "current_page": PageType.ORDER_DETAIL,
            "order_id": "ORDER-003",
            "task_id": None,
            "issue_id": None,
            "batch_id": None,
            "product_type": "DOM",
            "satellite_type": None,
            "user_role": "REVIEWER",
        }
    )

    assert context.current_page is PageType.ORDER_DETAIL
    assert context.order_id == "ORDER-003"
    with pytest.raises(ValidationError):
        PageContext.model_validate(
            {**context.model_dump(), "unsupported": "client-only"}
        )


@pytest.mark.parametrize(
    "invalid_context",
    [
        {
            "current_system": "production-system",
            "current_page": PageType.ORDER_DETAIL,
            "order_id": "ORDER-003",
            "task_id": "TASK-003",
            "user_role": "REVIEWER",
        },
        {
            "current_system": "production-system",
            "current_page": PageType.TASK_DETAIL,
            "order_id": "ORDER-003",
            "user_role": "REVIEWER",
        },
        {
            "current_system": "production-system",
            "current_page": PageType.QUALITY_ISSUE,
            "order_id": "ORDER-003",
            "task_id": "TASK-003",
            "user_role": "REVIEWER",
        },
    ],
)
def test_page_type_requires_matching_resource_depth(
    invalid_context: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PageContext.model_validate(invalid_context)
