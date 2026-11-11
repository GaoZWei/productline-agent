"""M8只读Tool输入，资源来自调用参数，身份与权限只从服务端上下文传递。"""

from typing import Annotated

from pydantic import AfterValidator, Field

from app.schemas.rework import OrderId, ReworkResource, ReworkSchema, TaskId


def _safe_cursor(value: str) -> str:
    """保留不透明游标原值，拒绝不能安全参与调用指纹或查询的字符。"""

    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("cursor must be losslessly representable in UTF-8") from None
    if any(char in value for char in ("\0", "\r", "\n")):
        raise ValueError("cursor must not contain NUL or line breaks")
    return value


class ReworkHistoryInput(ReworkResource):
    """一次只读一页历史；没有轮次、权限、自报状态或任意过滤参数。"""

    limit: Annotated[int, Field(ge=1, le=100)] = 20
    cursor: Annotated[str, Field(min_length=1), AfterValidator(_safe_cursor)] | None = None


class ReworkTaskInput(ReworkSchema):
    """任务级有效复核查询，只接受安全任务ID。"""

    task_id: TaskId = Field(alias="taskId")


class ReworkOrderInput(ReworkSchema):
    """订单级交付条件查询，不接受页面自报状态或权限。"""

    order_id: OrderId = Field(alias="orderId")
