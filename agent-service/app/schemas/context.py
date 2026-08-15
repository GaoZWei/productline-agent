"""页面提示上下文及页面类型的严格传输契约。"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.business import SafeHeaderValue
from app.schemas.tools import (
    BusinessIdentifier,
    NonBlankText,
    OrderIdentifier,
    TaskIdentifier,
)

# 定义了三个页面类型
class PageType(StrEnum):
    """当前支持采集业务对象的三类页面。"""

    ORDER_DETAIL = "order-detail"
    TASK_DETAIL = "task-detail"
    QUALITY_ISSUE = "quality-issue"


class PageContext(BaseModel):
    """客户端采集的页面提示; 资源归属和权限仍必须由服务端重校验。"""

    model_config = ConfigDict(
        extra="forbid",  # 不接受未声明字段
        frozen=True,  # 不允许字段被修改
        strict=True,  # 严格校验字段值
        str_strip_whitespace=True,
    )

    current_system: Literal["production-system"]
    # HTTP JSON 会把枚举传成字符串, 此字段允许按枚举值解析后再进入严格校验。
    current_page: PageType = Field(strict=False)
    order_id: OrderIdentifier
    task_id: TaskIdentifier | None = None
    issue_id: BusinessIdentifier | None = None
    batch_id: BusinessIdentifier | None = None
    product_type: NonBlankText | None = None
    satellite_type: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    user_role: SafeHeaderValue

    # 校验对应的上下文是否符合要求
    @model_validator(mode="after")
    def validate_page_resources(self) -> Self:
        """页面类型只接受其能够明确提供的最小资源层级。"""

        if self.current_page is PageType.ORDER_DETAIL:
            if self.task_id is not None or self.issue_id is not None:
                raise ValueError("order detail context must not contain task_id or issue_id")
        elif self.current_page is PageType.TASK_DETAIL:
            if self.task_id is None or self.issue_id is not None:
                raise ValueError("task detail context requires task_id and forbids issue_id")
        elif self.task_id is None or self.issue_id is None:
            raise ValueError("quality issue context requires task_id and issue_id")
        return self
