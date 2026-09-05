"""三个只读业务 Skill 的生产分发、模型观测和 RAG 装配。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from app.clients.model import ChatMessage, ModelClientError, StructuredModelResult
from app.database import Database
from app.eventing import RunEventSink
from app.knowledge import (
    EmbeddingProviderError,
    KeywordSearchHit,
    KnowledgeRetrievalPipeline,
    QueryEmbedding,
    QueryEmbeddingGenerator,
    VectorSearchHit,
)
from app.model_adapters import (
    StructuredActionDecisionModel,
    StructuredReranker,
    StructuredSpecificationAnswerModel,
)
from app.models import AgentStepType
from app.repositories import KnowledgeIndexRepository, KnowledgeSearchRepository
from app.routing import BusinessSkill, Intent
from app.schemas.action import ActionDecision
from app.schemas.agent_messages import (
    DiagnosisAgentResult,
    SpecificationAnswerAgentResult,
)
from app.schemas.context import PageContext
from app.schemas.knowledge import KnowledgeSearchFilter, PermissionScope
from app.schemas.run_observability import LLMStepObservation, RunTokenUsage
from app.schemas.specification import SpecificationQaResult
from app.schemas.workflow import AgentTerminationReason, OrderDiagnosisState
from app.services.agent_messages import (
    AgentSkillExecution,
    AgentSkillExecutionError,
    AgentSkillRequest,
    AgentSkillUnavailableError,
)
from app.services.knowledge_index_capabilities import KnowledgeIndexCapabilityService
from app.services.model_invocation import ObservedModelInvoker, StructuredChatClient
from app.tools import BaseTool, ToolContext, ToolRegistry, ToolRiskLevel
from app.tools.models import ToolResult
from app.workflows import (
    ActionDecider,
    AgentExecutionLimits,
    DynamicDiagnosisWorkflow,
    SpecificationQaWorkflow,
    SpecificationSkill,
)
from app.workflows.order_status import OrderStatusWorkflow, OrderStatusWorkflowError
from app.workflows.recording import ObservedWorkflowStepRecorder, WorkflowStepRecorder

OutputT = TypeVar("OutputT", bound=BaseModel)
_DateProvider = Callable[[], date]

_STATUS_PERMISSIONS = {
    Intent.ORDER_QUERY: frozenset({"ORDER_READ"}),
    Intent.TASK_TRACKING: frozenset({"TASK_READ"}),
}
_DIAGNOSIS_PERMISSIONS = frozenset(
    {
        "ORDER_READ",
        "TASK_READ",
        "QUALITY_ISSUE_READ",
        "REVIEW_READ",
        "DELIVERY_READ",
    }
)
_PERMISSION_SCOPE_BY_ROLE = {"REVIEWER": PermissionScope.INTERNAL_REVIEWER}


@dataclass(slots=True)
class _StepSequence:
    """为一个 Skill 内的嵌套 AGENT、LLM、TOOL 和 RAG Step 分配序号。"""

    next_value: int

    def take(self) -> int:
        value = self.next_value
        self.next_value += 1
        return value


@dataclass(slots=True)
class _TokenCollector:
    """收集 Skill 内成功结构化模型调用的 Token 用量。"""

    usages: list[RunTokenUsage] = field(default_factory=list)

    @property
    def total(self) -> RunTokenUsage:
        return RunTokenUsage.from_counts(
            input_tokens=sum(item.input_tokens for item in self.usages),
            output_tokens=sum(item.output_tokens for item in self.usages),
        )


class _SequencedObservedModelClient:
    """把一个模型协议适配器的每次调用记录为当前 Run 的独立 LLM Step。"""

    def __init__(
        self,
        client: StructuredChatClient,
        recorder: ObservedWorkflowStepRecorder,
        sequence: _StepSequence,
        collector: _TokenCollector,
        *,
        run_id: str,
        step_name: str,
    ) -> None:
        self._client = client
        self._recorder = recorder
        self._sequence = sequence
        self._collector = collector
        self._run_id = run_id
        self._step_name = step_name
        self._last_model_error: ModelClientError | None = None

    @property
    def model_name(self) -> str | None:
        return self._client.model_name

    @property
    def last_model_error(self) -> ModelClientError | None:
        """返回本包装器最近一次稳定模型失败, 供上层避免冒充成功。"""

        return self._last_model_error

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        """调用公共观测包装器, Prompt 和模型正文不进入 Step 摘要。"""

        sequence_number = self._sequence.take()
        step_id = _step_id(self._run_id, sequence_number)
        invoker = ObservedModelInvoker(self._client, self._recorder)
        try:
            result = await invoker.complete_structured(
                messages,
                output_schema,
                step_id=step_id,
                run_id=self._run_id,
                sequence_number=sequence_number,
                step_name=self._step_name,
                input_summary=f"output_schema={output_schema.__name__}",
            )
        except ModelClientError as error:
            self._last_model_error = error
            raise
        except asyncio.CancelledError:
            await asyncio.shield(
                self._recorder.mark_llm_failed(
                    step_id,
                    error_code="MODEL_INVOCATION_INTERRUPTED",
                    output_summary="model_invocation=interrupted",
                    observation=(
                        LLMStepObservation(model_name=self.model_name)
                        if self.model_name is not None
                        else None
                    ),
                )
            )
            raise
        self._collector.usages.append(result.token_usage)
        return result


class _ObservedTool:
    """在既有 BaseTool 门禁外增加统一 Run 的 TOOL Step。"""

    def __init__(
        self,
        delegate: BaseTool[Any, Any],
        recorder: WorkflowStepRecorder,
        sequence: _StepSequence,
        *,
        run_id: str,
    ) -> None:
        self._delegate = delegate
        self._recorder = recorder
        self._sequence = sequence
        self._run_id = run_id

    @property
    def name(self) -> str:
        return self._delegate.name

    @property
    def input_model(self) -> type[BaseModel]:
        return cast(type[BaseModel], self._delegate.input_model)

    @property
    def description(self) -> str:
        return self._delegate.description

    @property
    def risk_level(self) -> ToolRiskLevel:
        return self._delegate.risk_level

    @property
    def required_permissions(self) -> frozenset[str]:
        return self._delegate.required_permissions

    async def execute(
        self,
        raw_input: BaseModel | Mapping[str, object],
        context: ToolContext,
        *,
        force_refresh: bool = False,
    ) -> ToolResult[Any]:
        """先保存 TOOL Step, 再执行原 Tool 并按结构化结果结束 Step。"""

        sequence_number = self._sequence.take()
        step_id = _step_id(self._run_id, sequence_number)
        await self._recorder.start_step(
            step_id=step_id,
            run_id=self._run_id,
            sequence_number=sequence_number,
            step_type=AgentStepType.TOOL,
            step_name=self.name,
            input_summary=f"tool={self.name}",
        )
        try:
            result = await self._delegate.execute(
                raw_input,
                context,
                force_refresh=force_refresh,
            )
        except Exception:
            await self._recorder.mark_failed(
                step_id,
                error_code="UNKNOWN_TOOL_ERROR",
                output_summary="tool_execution=failed",
            )
            raise
        if result.success:
            await self._recorder.mark_succeeded(
                step_id,
                output_summary="tool_execution=succeeded",
            )
        else:
            error_code = (
                result.error.code.value if result.error is not None else "UNKNOWN_TOOL_ERROR"
            )
            await self._recorder.mark_failed(
                step_id,
                error_code=error_code,
                output_summary="tool_execution=failed",
            )
        return result


class _ObservedToolRegistry:
    """按需为生产只读 Tool 返回带 Step 观测的代理。"""

    def __init__(
        self,
        delegate: ToolRegistry,
        recorder: WorkflowStepRecorder,
        sequence: _StepSequence,
        *,
        run_id: str,
    ) -> None:
        self._delegate = delegate
        self._recorder = recorder
        self._sequence = sequence
        self._run_id = run_id

    def get(self, name: str) -> _ObservedTool:
        return _ObservedTool(
            self._delegate.get(name),
            self._recorder,
            self._sequence,
            run_id=self._run_id,
        )

    @property
    def names(self) -> tuple[str, ...]:
        return self._delegate.names

    def __contains__(self, name: object) -> bool:
        return name in self._delegate

    def __len__(self) -> int:
        return len(self._delegate)


class _RecordedActionDecider:
    """把一次确定性校验后的 Action 决策记录为 AGENT Step。"""

    def __init__(
        self,
        delegate: ActionDecider,
        recorder: WorkflowStepRecorder,
        sequence: _StepSequence,
        *,
        run_id: str,
    ) -> None:
        self._delegate = delegate
        self._recorder = recorder
        self._sequence = sequence
        self._run_id = run_id

    async def decide(self, state: OrderDiagnosisState) -> ActionDecision:
        """记录动作选择, 不保存模型理由或业务事实正文。"""

        sequence_number = self._sequence.take()
        step_id = _step_id(self._run_id, sequence_number)
        await self._recorder.start_step(
            step_id=step_id,
            run_id=self._run_id,
            sequence_number=sequence_number,
            step_type=AgentStepType.AGENT,
            step_name="choose_diagnosis_action",
            input_summary=f"decision_round={state['iteration_count'] + 1}",
        )
        try:
            decision = await self._delegate.decide(state)
        except Exception:
            await self._recorder.mark_failed(
                step_id,
                error_code="ACTION_DECISION_ERROR",
                output_summary="action_decision=failed",
            )
            raise
        await self._recorder.mark_succeeded(
            step_id,
            output_summary=f"action={decision.action.value};tool={decision.tool_name or 'none'}",
        )
        return decision

# 关键词查询和向量查询
class _DatabaseKnowledgeSearchChannels:
    """每条知识查询使用独立短 Session, 避免在 Embedding 网络调用期间持有事务。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def search_keywords(
        self,
        query: str,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
    ) -> tuple[KeywordSearchHit, ...]:
        async with self._database.session() as session:
            return await KnowledgeSearchRepository(session).search_keywords(
                query,
                filters=filters,
                top_k=top_k,
            )

    async def search_vectors(
        self,
        query_embedding: QueryEmbedding,
        *,
        filters: KnowledgeSearchFilter,
        top_k: int = 10,
        min_similarity: float = -1.0,
    ) -> tuple[VectorSearchHit, ...]:
        async with self._database.session() as session:
            return await KnowledgeSearchRepository(session).search_vectors(
                query_embedding,
                filters=filters,
                top_k=top_k,
                min_similarity=min_similarity,
            )


class _ProductionSpecificationWorkflow:
    """在索引就绪、权限和日期门禁后运行带观测的规范问答。"""

    def __init__(
        self,
        *,
        database: Database,
        capability_service: KnowledgeIndexCapabilityService,
        embedding_generator: QueryEmbeddingGenerator | None,
        model_client: StructuredChatClient,
        recorder: ObservedWorkflowStepRecorder,
        sequence: _StepSequence,
        collector: _TokenCollector,
        run_id: str,
        event_sink: RunEventSink | None,
    ) -> None:
        self._database = database
        self._capability_service = capability_service
        self._embedding_generator = embedding_generator
        self._model_client = model_client
        self._recorder = recorder
        self._sequence = sequence
        self._collector = collector
        self._run_id = run_id
        self._event_sink = event_sink

    async def ainvoke(
        self,
        question: str,
        *,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
    ) -> SpecificationQaResult:
        """执行一次 RAG Step, 内部重排和回答模型各自再记录 LLM Step。"""
        # 首先创建RAG Step记录
        sequence_number = self._sequence.take()
        step_id = _step_id(self._run_id, sequence_number)
        await self._recorder.start_step(
            step_id=step_id,
            run_id=self._run_id,
            sequence_number=sequence_number,
            step_type=AgentStepType.RAG,
            step_name="answer_specification",
            input_summary=(
                f"permission_scope={permission_scope.value};effective_at={effective_at.isoformat()}"
            ),
        )
        # 检查Query Embedding是否配置、知识库是否入库、catalog是否就绪、chunk是否存在、provider是否可用
        try:
            if self._embedding_generator is None:
                raise AgentSkillExecutionError(
                    code="EMBEDDING_NOT_CONFIGURED",
                    message="query embedding provider is not configured",
                    retryable=False,
                    error_step="answer_specification",
                    token_usage=self._collector.total,
                )
            await self._ensure_ready()
            workflow = SpecificationQaWorkflow(
                retriever=KnowledgeRetrievalPipeline(
                    repository=_DatabaseKnowledgeSearchChannels(self._database),
                    embedding_generator=self._embedding_generator,
                ),
                reranker=StructuredReranker(
                    _SequencedObservedModelClient(
                        self._model_client,
                        self._recorder,
                        self._sequence,
                        self._collector,
                        run_id=self._run_id,
                        step_name="rerank_specification",
                    )
                ),
                answer_model=StructuredSpecificationAnswerModel(
                    _SequencedObservedModelClient(
                        self._model_client,
                        self._recorder,
                        self._sequence,
                        self._collector,
                        run_id=self._run_id,
                        step_name="generate_specification_answer",
                    )
                ),
                event_sink=self._event_sink,
                run_id=self._run_id,
            )
            result = await workflow.ainvoke(
                question,
                effective_at=effective_at,
                permission_scope=permission_scope,
                page_context=page_context,
            )
        except AgentSkillExecutionError as error:
            await self._recorder.mark_failed(
                step_id,
                error_code=error.code,
                output_summary="specification_execution=failed",
            )
            raise
        except EmbeddingProviderError as error:
            await self._recorder.mark_failed(
                step_id,
                error_code=error.code.value,
                output_summary="specification_execution=failed",
            )
            raise AgentSkillExecutionError(
                code=error.code.value,
                message=str(error),
                retryable=error.retryable,
                error_step="answer_specification",
                token_usage=self._collector.total,
            ) from error
        except Exception as error:
            await self._recorder.mark_failed(
                step_id,
                error_code="SPECIFICATION_EXECUTION_ERROR",
                output_summary="specification_execution=failed",
            )
            raise AgentSkillExecutionError(
                code="SPECIFICATION_EXECUTION_ERROR",
                message="specification workflow execution failed",
                retryable=False,
                error_step="answer_specification",
                token_usage=self._collector.total,
            ) from error
        await self._recorder.mark_succeeded(
            step_id,
            output_summary=(f"status={result.status.value};citation_count={len(result.citations)}"),
        )
        return result

    async def _ensure_ready(self) -> None:
        async with self._database.session() as session:
            capability = await self._capability_service.get(KnowledgeIndexRepository(session))
        if not capability.ready:
            raise AgentSkillExecutionError(
                code="KNOWLEDGE_INDEX_NOT_READY",
                message=f"knowledge index is not ready: {capability.status.value}",
                retryable=False,
                error_step="answer_specification",
                token_usage=self._collector.total,
            )


class ProductionAgentSkillDispatcher:
    """将三个只读 BusinessSkill 装配到统一 Agent Run, Review 保持未接线。"""

    def __init__(
        self,
        *,
        database: Database,
        tool_registry: ToolRegistry,
        model_client: StructuredChatClient,
        knowledge_capability_service: KnowledgeIndexCapabilityService,
        embedding_generator: QueryEmbeddingGenerator | None,
        limits: AgentExecutionLimits | None = None,
        today: _DateProvider | None = None,
    ) -> None:
        self._database = database
        self._tool_registry = tool_registry
        self._model_client = model_client
        self._knowledge_capability_service = knowledge_capability_service
        self._embedding_generator = embedding_generator
        self._limits = limits or AgentExecutionLimits()
        self._today = today or (lambda: datetime.now(UTC).date())
    # 生产环境Skill分发器
    async def dispatch(
        self,
        skill: BusinessSkill,
        request: AgentSkillRequest,
    ) -> AgentSkillExecution:
        """按确定性 Skill 名称分发, 并返回统一结果、用量和 Tool 次数。"""

        if skill is BusinessSkill.REVIEW:
            raise AgentSkillUnavailableError("review skill is not available before M7.6-F")

        sequence = _StepSequence(request.first_step_sequence)
        collector = _TokenCollector()
        observed_registry = cast(
            ToolRegistry,
            _ObservedToolRegistry(
                self._tool_registry,
                request.step_recorder,
                sequence,
                run_id=request.run_id,
            ),
        )
        # 确定性分发器（静态确定的skill）
        if skill is BusinessSkill.ORDER_STATUS:
            return await self._dispatch_order_status(request, observed_registry)
        if skill is BusinessSkill.DIAGNOSIS:
            return await self._dispatch_diagnosis(
                request,
                observed_registry,
                sequence,
                collector,
            )
        if skill is BusinessSkill.SPECIFICATION:
            return await self._dispatch_specification(request, sequence, collector)
        raise AgentSkillUnavailableError("routed agent skill is not available")

    async def _dispatch_order_status(
        self,
        request: AgentSkillRequest,
        registry: ToolRegistry,
    ) -> AgentSkillExecution:
        permissions = _STATUS_PERMISSIONS.get(request.decision.intent)
        if permissions is None:
            raise AgentSkillExecutionError(
                code="SKILL_DISPATCH_INVALID",
                message="intent does not belong to OrderStatusSkill",
            )
        context = ToolContext(
            identity=request.identity,
            permissions=permissions,
            trace_id=request.trace_id,
            run_id=request.run_id,
        )
        try:
            result = await OrderStatusWorkflow(
                tool_registry=registry,
                tool_context=context,
            ).execute(request.decision)
        except OrderStatusWorkflowError as error:
            raise AgentSkillExecutionError(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                error_step=error.error_step,
                tool_call_count=context.tool_call_ledger.recorded_call_count,
            ) from error
        return AgentSkillExecution(
            result=result,
            tool_call_count=context.tool_call_ledger.recorded_call_count,
        )
    # 动态诊断核心代码 模型只选择下一步，不直接生成事实
    async def _dispatch_diagnosis(
        self,
        request: AgentSkillRequest,
        registry: ToolRegistry,
        sequence: _StepSequence,
        collector: _TokenCollector,
    ) -> AgentSkillExecution:
        entities = request.decision.entities.to_router_entities()
        # 首先验证意图必须是ORDER_DIAGNOSIS，而且必须存在order_id
        if request.decision.intent is not Intent.ORDER_DIAGNOSIS or entities.order_id is None:
            raise AgentSkillExecutionError(
                code="SKILL_DISPATCH_INVALID",
                message="diagnosis routing decision is missing order_id",
            )
        # 创建ToolContext，用于后续的Tool调用
        context = ToolContext(
            identity=request.identity,
            permissions=_DIAGNOSIS_PERMISSIONS,
            trace_id=request.trace_id,
            run_id=request.run_id,
        )
        observed_action_client = _SequencedObservedModelClient(
            self._model_client,
            request.step_recorder,
            sequence,
            collector,
            run_id=request.run_id,
            step_name="choose_diagnosis_action_model",
        )
        # 公共模型Client先经过StructuredActionDecisionModel适配
        model = StructuredActionDecisionModel(observed_action_client)
        decider = cast(
            ActionDecider, # 执行确定性校验
            _RecordedActionDecider(
                ActionDecider(model=model, registry=registry),
                request.step_recorder,
                sequence,
                run_id=request.run_id,
            ),
        )
        # 注入RAG和执行预算限制
        specification = self._specification_workflow(request, sequence, collector)
        workflow = DynamicDiagnosisWorkflow(
            action_decider=decider,
            tool_registry=registry,
            tool_context=context,
            specification_workflow=specification,
            effective_at=self._today(),
            permission_scope=self._permission_scope(request),
            limits=self._limits,
            event_sink=request.event_sink,
        )
        state = await workflow.ainvoke(
            entities.order_id,
            page_context=request.page_context,
        )
        # 观测模型Client会保存最近一次稳定模型错误
        model_error = observed_action_client.last_model_error
        if model_error is not None:
            raise AgentSkillExecutionError(
                code=model_error.code.value,
                message=str(model_error),
                retryable=model_error.retryable,
                error_step="choose_diagnosis_action_model",
                token_usage=collector.total,
                tool_call_count=context.tool_call_ledger.recorded_call_count,
            ) from model_error
        if state["errors"]:
            error = state["errors"][0]
            raise AgentSkillExecutionError(
                code=error.code.value,
                message=error.message,
                retryable=error.retryable,
                error_step=error.step_name,
                token_usage=collector.total,
                tool_call_count=context.tool_call_ledger.recorded_call_count,
            )
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            raise AgentSkillExecutionError(
                code="DIAGNOSIS_RESULT_MISSING",
                message="dynamic diagnosis produced no result",
                retryable=False,
                error_step="generate_diagnosis",
                token_usage=collector.total,
                tool_call_count=context.tool_call_ledger.recorded_call_count,
            )
        termination = state["termination_reason"] or AgentTerminationReason.SUFFICIENT_INFORMATION
        return AgentSkillExecution(
            result=DiagnosisAgentResult(diagnosis=diagnosis),
            token_usage=collector.total,
            tool_call_count=context.tool_call_ledger.recorded_call_count,
            termination_reason=termination.value,
        )
    # 规范结论必须有引用
    async def _dispatch_specification(
        self,
        request: AgentSkillRequest,
        sequence: _StepSequence,
        collector: _TokenCollector,
    ) -> AgentSkillExecution:
        workflow = self._specification_workflow(request, sequence, collector)
        result = await SpecificationSkill(cast(SpecificationQaWorkflow, workflow)).execute(
            request.decision,
            question=request.message,
            effective_at=self._today(),
            permission_scope=self._permission_scope(request),
            page_context=request.page_context,
        )
        return AgentSkillExecution(
            result=SpecificationAnswerAgentResult(specification_answer=result),
            token_usage=collector.total,
        )

    def _specification_workflow(
        self,
        request: AgentSkillRequest,
        sequence: _StepSequence,
        collector: _TokenCollector,
    ) -> _ProductionSpecificationWorkflow:
        return _ProductionSpecificationWorkflow(
            database=self._database,
            capability_service=self._knowledge_capability_service,
            embedding_generator=self._embedding_generator,
            model_client=self._model_client,
            recorder=request.step_recorder,
            sequence=sequence,
            collector=collector,
            run_id=request.run_id,
            event_sink=request.event_sink,
        )

    @staticmethod
    def _permission_scope(request: AgentSkillRequest) -> PermissionScope:
        try:
            return _PERMISSION_SCOPE_BY_ROLE[request.identity.role]
        except KeyError as error:
            raise AgentSkillExecutionError(
                code="PERMISSION_DENIED",
                message="knowledge permission scope is unavailable for this role",
                retryable=False,
                error_step="resolve_knowledge_permission",
            ) from error


def _step_id(run_id: str, sequence_number: int) -> str:
    """使用 Run 身份和序号生成不依赖模型内容的稳定 Step ID。"""

    suffix = run_id.removeprefix("run-")
    return f"step-skill-{suffix}-{sequence_number}"


__all__ = ["ProductionAgentSkillDispatcher"]
