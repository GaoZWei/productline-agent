"""Agent 服务负责管理的Pydantic与Workflow状态契约。"""

from app.routing import BusinessSkill, Intent, RoutingParameter
from app.schemas.agent import (
    OrderDiagnosisErrorResponse,
    OrderDiagnosisRequest,
    OrderDiagnosisResponse,
)
from app.schemas.context import PageContext, PageType
from app.schemas.routing import RouterEntities, RouterResult
from app.schemas.session import (
    PendingActionContext,
    SessionContext,
    SessionCreateRequest,
    SessionErrorResponse,
    SessionResponse,
)
from app.schemas.workflow import (
    BlockingStage,
    DiagnosisNarrative,
    DiagnosisResult,
    Evidence,
    OrderDiagnosisState,
    ReadToolName,
    RootCause,
    RuleDecision,
    StepError,
    Suggestion,
)

__all__ = [
    "BlockingStage",
    "BusinessSkill",
    "DiagnosisNarrative",
    "DiagnosisResult",
    "Evidence",
    "Intent",
    "OrderDiagnosisErrorResponse",
    "OrderDiagnosisRequest",
    "OrderDiagnosisResponse",
    "OrderDiagnosisState",
    "PageContext",
    "PageType",
    "PendingActionContext",
    "ReadToolName",
    "RootCause",
    "RouterEntities",
    "RouterResult",
    "RoutingParameter",
    "RuleDecision",
    "SessionContext",
    "SessionCreateRequest",
    "SessionErrorResponse",
    "SessionResponse",
    "StepError",
    "Suggestion",
]
