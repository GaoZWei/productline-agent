"""保持七个动作名称的诊断专用只读装配，不接入任何M8写动作。"""

from pydantic import ValidationError

from app.clients.business import BusinessHttpClient
from app.clients.rework import ReworkHttpClient
from app.errors import ToolErrorCode, ToolException
from app.schemas.diagnosis_reviews import DiagnosisReviewResult, project_java_reviews
from app.schemas.tools import ReviewResult, TaskIdInput
from app.tools.models import ToolContext
from app.tools.readonly import _BusinessReadTool, create_read_tool_registry
from app.tools.registry import ToolRegistry


class GetDiagnosisReviewResultTool(_BusinessReadTool[TaskIdInput, DiagnosisReviewResult]):
    """同一逻辑复核查询保存旧历史，以Java有效快照输出诊断投影。"""

    def __init__(self, client: BusinessHttpClient) -> None:
        """沿用REVIEW_READ和总预算，不扩大模型动作目录或签发写权限。"""

        super().__init__(
            client,
            name="get_review_result",
            description="读取Java当前有效复核和独立历史记录，历史通过不能代替当前材料复核",
            input_model=TaskIdInput,
            output_model=DiagnosisReviewResult,
            permission="REVIEW_READ",
        )
        self._rework_client = ReworkHttpClient(client)

    async def _execute(
        self, tool_input: TaskIdInput, context: ToolContext
    ) -> DiagnosisReviewResult:
        """两次GET均只读，诊断只消费有效快照，历史不是相同SQL快照的证明。"""

        history = await self._client.get(
            f"/api/tasks/{tool_input.task_id}/review",
            ReviewResult,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        if history.data.task_id != tool_input.task_id or history.trace_id != context.trace_id:
            self._raise_resource_mismatch(context.trace_id)
        snapshot = await self._rework_client.get_effective_reviews(
            tool_input.task_id,
            identity=context.identity,
            trace_id=context.trace_id,
        )
        try:
            return DiagnosisReviewResult(
                task_id=tool_input.task_id,
                reviews=project_java_reviews(snapshot.data),
                effective_reviews=snapshot.data,
                history_reviews=history.data.reviews,
            )
        except ValidationError:
            raise ToolException(
                code=ToolErrorCode.RESPONSE_VALIDATION_ERROR,
                message="diagnosis review projection is invalid",
                retryable=False,
                trace_id=context.trace_id,
            ) from None


def create_diagnosis_read_tool_registry(client: BusinessHttpClient) -> ToolRegistry:
    """只替换诊断装配中的复核读取实现，旧七Tool工厂及动作名称保持兼容。"""

    original = create_read_tool_registry(client)
    result = ToolRegistry()
    for name in original.names:
        result.register(
            GetDiagnosisReviewResultTool(client)
            if name == "get_review_result"
            else original.get(name)
        )
    return result
