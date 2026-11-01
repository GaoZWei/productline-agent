"""知识管理授权查询的严格输入、Java响应与确认策略。"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.business import SafeHeaderValue
from app.schemas.knowledge import PermissionScopeValue


class KnowledgeManagementAction(StrEnum):
    """与Java一致的知识动作白名单，不表示对应写入已经执行。"""

    READ = "READ"
    UPLOAD = "UPLOAD"
    PUBLISH = "PUBLISH"
    DISABLE = "DISABLE"
    RETRY_INDEX = "RETRY_INDEX"


KnowledgeActionValue = Annotated[KnowledgeManagementAction, Field(strict=False)]


class KnowledgeAuthorizationRequest(BaseModel):
    """仅向Java提交动作，拒绝自报权限、确认和知识状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action: KnowledgeActionValue


class KnowledgeAuthorizationResponse(BaseModel):
    """保留Java字段别名并拒绝隐式布尔转换或确认策略不一致。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: SafeHeaderValue = Field(alias="userId")
    action: KnowledgeActionValue
    permission_scope: PermissionScopeValue = Field(alias="permissionScope")
    confirmation_required: bool = Field(alias="confirmationRequired")

    @model_validator(mode="after")
    def validate_confirmation_policy(self) -> Self:
        """任何写入动作都必须保持Java约定的人工确认要求。"""

        if self.confirmation_required is not (self.action is not KnowledgeManagementAction.READ):
            raise ValueError("knowledge confirmation policy does not match action")
        return self
