"""统一Agent消息Turn的会话、路由、澄清、分发和终态编排。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.clients.model import ChatMessage, ModelClientError, StructuredModelResult
from app.database import Database
from app.eventing import RunEventSink
from app.model_adapters import StructuredIntentRoutingModel
from app.models import AgentMessage, AgentMessageRole, AgentRunStatus, AgentSession, AgentStepType
from app.repositories import AgentMessageRepository, AgentRunRepository, AgentSessionRepository
from app.routing import BusinessSkill, skill_for_intent
from app.routing.decision import (
    InvalidClarificationSelectionError,
    build_routing_decision,
    confirm_routing_intent,
    resume_routing_after_selection,
)
from app.routing.entity_merge import merge_routing_entities
from app.routing.prompt import RoutingPrompt
from app.schemas.agent_messages import (
    AgentMessageRequest,
    AgentMessageResult,
    ApprovalAgentResult,
    ClarificationAgentResult,
    DiagnosisAgentResult,
    OrderStatusResult,
    SpecificationAnswerAgentResult,
)
from app.schemas.business import BusinessIdentity
from app.schemas.events import RunEventType
from app.schemas.routing import EntityExtractionResult, EntitySource, RoutingDecision
from app.schemas.run_observability import RunTokenUsage
from app.schemas.session import SessionContext, context_from_page
from app.schemas.versioning import RunVersionSnapshot
from app.services.intent_router import IntentRouter, InvalidRouterOutputError
from app.services.model_invocation import ObservedModelInvoker, StructuredChatClient
from app.services.run_lifecycle import RunLifecycleService
from app.services.session_context import (
    SessionAccessDeniedError,
    SessionContextError,
    SessionContextService,
)
from app.workflows.recording import DatabaseWorkflowStepRecorder

_LOGGER = logging.getLogger("agent-service.agent-messages")
_RESULT_ADAPTER: TypeAdapter[AgentMessageResult] = TypeAdapter(AgentMessageResult)
OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class AgentSkillRequest:
    """分发给业务Skill的受控请求, 不把页面或Session提示冒充Java事实。"""

    run_id: str
    session_id: str
    trace_id: str
    message: str
    identity: BusinessIdentity
    decision: RoutingDecision


@dataclass(frozen=True, slots=True)
class AgentSkillExecution:
    """Skill结果及其可汇总到Run的最小用量。"""

    result: AgentMessageResult
    token_usage: RunTokenUsage = field(default_factory=RunTokenUsage)
    tool_call_count: int = 0


class AgentSkillDispatcher(Protocol):
    """M7.6-D只定义分发边界, 具体四个Skill由后续批次注入。"""

    def dispatch(
        self,
        skill: BusinessSkill,
        request: AgentSkillRequest,
    ) -> Awaitable[AgentSkillExecution]: ...


class AgentSkillUnavailableError(RuntimeError):
    """目标Skill尚未接入统一生产分发器。"""


class AgentSkillExecutionError(RuntimeError):
    """Skill已接线但执行失败或返回了错误结果类型。"""


class UnavailableAgentSkillDispatcher:
    """默认生产占位分发器, 明确失败而不回退到固定诊断。"""

    async def dispatch(
        self,
        skill: BusinessSkill,
        request: AgentSkillRequest,
    ) -> AgentSkillExecution:
        del skill, request
        raise AgentSkillUnavailableError("routed agent skill is not available")


class ClarificationContinuationError(ValueError):
    """澄清来源Run、归属或选择不满足续接门禁。"""


class AgentMessageExecutionError(Exception):
    """已经转换为统一HTTP安全字段的一轮执行失败。"""

    def __init__(
        self,
        *,
        run_id: str | None,
        code: str,
        message: str,
        retryable: bool,
        error_step: str | None,
    ) -> None:
        self.run_id = run_id
        self.code = code
        self.message = message
        self.retryable = retryable
        self.error_step = error_step
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class AgentMessageExecution:
    """成功Turn返回的标识和统一结果。"""

    run_id: str
    session_id: str
    result: AgentMessageResult


class _BoundObservedStructuredClient:
    """把一次Router尝试绑定到唯一LLM Step并收集成功用量。"""

    def __init__(
        self,
        client: StructuredChatClient,
        recorder: DatabaseWorkflowStepRecorder,
        *,
        run_id: str,
        step_id: str,
        sequence_number: int,
        attempt: int,
        prompt_version: str,
        usage_sink: list[RunTokenUsage],
    ) -> None:
        self._invoker = ObservedModelInvoker(client, recorder)
        self._run_id = run_id
        self._step_id = step_id
        self._sequence_number = sequence_number
        self._attempt = attempt
        self._prompt_version = prompt_version
        self._usage_sink = usage_sink

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        """调用公共观测包装器; 消息正文不会进入Step摘要。"""

        result = await self._invoker.complete_structured(
            messages,
            output_schema,
            step_id=self._step_id,
            run_id=self._run_id,
            sequence_number=self._sequence_number,
            step_name="route_intent",
            input_summary=(f"prompt_version={self._prompt_version};attempt={self._attempt}"),
        )
        self._usage_sink.append(result.token_usage)
        return result


class _ObservedIntentRoutingModel:
    """按Prompt尝试号创建独立LLM Step并复用既有Router适配器。"""

    def __init__(
        self,
        client: StructuredChatClient,
        recorder: DatabaseWorkflowStepRecorder,
        *,
        run_id: str,
        id_suffix: str,
    ) -> None:
        self._client = client
        self._recorder = recorder
        self._run_id = run_id
        self._id_suffix = id_suffix
        self._usages: list[RunTokenUsage] = []
        self.attempt_count = 0

    @property
    def token_usage(self) -> RunTokenUsage:
        """返回全部成功Router尝试的Token合计。"""

        return RunTokenUsage.from_counts(
            input_tokens=sum(item.input_tokens for item in self._usages),
            output_tokens=sum(item.output_tokens for item in self._usages),
        )

    async def generate(self, prompt: RoutingPrompt) -> object:
        """每次纠错尝试使用不同Step序号, 避免覆盖第一次失败证据。"""

        self.attempt_count += 1
        client = _BoundObservedStructuredClient(
            self._client,
            self._recorder,
            run_id=self._run_id,
            step_id=f"step-route-{self._id_suffix}-{prompt.attempt}",
            sequence_number=1 + prompt.attempt,
            attempt=prompt.attempt,
            prompt_version=prompt.version,
            usage_sink=self._usages,
        )
        return await StructuredIntentRoutingModel(client).generate(prompt)

# Agent Turn 编排服务
class AgentMessageService:
    """用唯一生产入口执行一轮上下文、严格路由、澄清或Skill分发。"""

    def __init__(
        self,
        database: Database,
        model_client: StructuredChatClient,
        skill_dispatcher: AgentSkillDispatcher,
        *,
        session_ttl_seconds: int,
        version_snapshot: RunVersionSnapshot,
        event_sink: RunEventSink | None = None,
    ) -> None:
        self._database = database
        self._model_client = model_client
        self._skill_dispatcher = skill_dispatcher
        self._session_ttl = timedelta(seconds=session_ttl_seconds)
        self._version_snapshot = version_snapshot
        self._event_sink = event_sink
    # 建立Run + 加载上下文+ 模型给候选+ 服务端做裁决+ 澄清或分者调用Skill + 统一保存终态
    async def execute(
        self,
        request: AgentMessageRequest,
        *,
        identity: BusinessIdentity,
        trace_id: str,
    ) -> AgentMessageExecution:
        """创建Run并保证模型、路由或Skill路径最终只落入一个终态。"""
        # 1.先生成本轮稳定标识：生成同源的技术标识,方便后续关联
        request_suffix = uuid4().hex
        run_id = f"run-{request_suffix}"
        message_id = f"message-{request_suffix}"
        try:
            # 2.初始化运行环境 Session、Message 和 Run
            session_id, session_context = await self._create_running_run(
                request,
                identity=identity,
                run_id=run_id,
                message_id=message_id,
            )
            # 如果 Session 不存在、过期或不属于当前用户，初始化事务会回滚
        except SessionContextError as error:
            await self._publish(
                RunEventType.RUN_FAILED,
                run_id=None,
                data={"error_code": error.code, "retryable": False},
            )
            raise AgentMessageExecutionError(
                run_id=None,
                code=error.code,
                message=error.message,
                retryable=False,
                error_step=None,
            ) from error
        except Exception as error:
            _LOGGER.exception("agent_message_initialization_failed")
            await self._publish(
                RunEventType.RUN_FAILED,
                run_id=None,
                data={"error_code": "AGENT_INITIALIZATION_ERROR", "retryable": False},
            )
            raise AgentMessageExecutionError(
                run_id=None,
                code="AGENT_INITIALIZATION_ERROR",
                message="agent message initialization failed",
                retryable=False,
                error_step=None,
            ) from error
        # 3.发布 Run 启动事件，通知前端这一轮已经开始
        await self._publish(
            RunEventType.RUN_STARTED,
            run_id=run_id,
            data={"session_id": session_id},
        )
        # 创建 Step Recorder
        recorder = DatabaseWorkflowStepRecorder(self._database)
        try:
            # 4.创建并完成上下文 Step
            await recorder.start_step(
                step_id=f"step-context-{request_suffix}",
                run_id=run_id,
                sequence_number=1,
                step_type=AgentStepType.CONTEXT,
                step_name="load_agent_context",
                input_summary=(
                    f"session_reused={str(request.session_id is not None).lower()};"
                    f"page_context={str(request.page_context is not None).lower()}"
                ),
            )
            await recorder.mark_succeeded(
                f"step-context-{request_suffix}",
                output_summary="session_owner=validated;context_schema=validated",
            )
            # Step 成功后发布 CONTEXT_LOADED 事件
            await self._publish(
                RunEventType.CONTEXT_LOADED,
                run_id=run_id,
                data={
                    "session_reused": request.session_id is not None,
                    "page_context_provided": request.page_context is not None,
                },
            )
            # Step 序号如何安排
            routing_model: _ObservedIntentRoutingModel | None = None
            # 5.判断是不是澄清续接 
            # 如果当前请求不是澄清续接，系统创建路由模型
            if request.clarification is None:
                routing_model = _ObservedIntentRoutingModel(
                    self._model_client,
                    recorder,
                    run_id=run_id,
                    id_suffix=request_suffix,
                )
                # 5.1.普通消息调用模型 Router 进行意图识别
                raw_result = await IntentRouter(
                    routing_model,
                    strict_model_errors=True,
                ).route(
                    user_message=request.message,
                    page_context=request.page_context,
                    session_context=session_context,
                )
                # 5.2.服务端合并实体
                merge_result = merge_routing_entities(
                    extraction=EntityExtractionResult(entities=raw_result.entities),
                    page_context=request.page_context,
                    session_context=session_context,
                )
                # 5.3.生成最终路由决策
                decision = build_routing_decision(
                    raw_result=raw_result,
                    merge_result=merge_result,
                )
                policy_sequence = routing_model.attempt_count + 2
                router_usage = routing_model.token_usage
            # 6.澄清续接分支 如果请求包含 clarification，代码走另一条分支
            else:
                # 6.1.校验来源 Run 是否存在
                pending = await self._load_pending_decision(
                    session_id=session_id,
                    source_run_id=request.clarification.source_run_id,
                )
                try:
                    # 6.2.确认路由意图
                    if request.clarification.confirm_intent:
                        decision = confirm_routing_intent(pending)
                    # 6.3.恢复原路由决策，不再调用模型
                    else:
                        assert request.clarification.selection is not None
                        decision = resume_routing_after_selection(
                            pending,
                            request.clarification.selection,
                        )
                except InvalidClarificationSelectionError as error:
                    raise ClarificationContinuationError(
                        "clarification selection is invalid for the source run"
                    ) from error
                policy_sequence = 2
                router_usage = RunTokenUsage()
            # 6.4.记录确定性 ROUTER Step
            await self._record_routing_decision(
                recorder,
                run_id=run_id,
                request_suffix=request_suffix,
                sequence_number=policy_sequence,
                decision=decision,
            )
            # 6.5.保存决策和更新 Session 上下文信息
            await self._save_decision(run_id, decision)
            await self._update_session_context(
                session_id,
                identity=identity,
                decision=decision,
            )
            # 6.6.发布意图识别事件
            await self._publish(
                RunEventType.INTENT_DETECTED,
                run_id=run_id,
                data={
                    "intent": decision.intent.value,
                    "confidence": decision.confidence,
                    "status": decision.status.value,
                },
            )
            # 6.7.不能分发：返回澄清结果
            if not decision.can_dispatch:
                assert decision.clarification is not None
                # 6.7.1.构造澄清结果对象
                result: AgentMessageResult = ClarificationAgentResult(
                    intent=decision.intent,
                    confidence=decision.confidence,
                    clarification=decision.clarification,
                )
                # 6.7.2.发布澄清结果事件
                await self._publish(
                    RunEventType.CLARIFICATION_REQUIRED,
                    run_id=run_id,
                    data={
                        "reason": decision.clarification.reason.value,
                        "field": (
                            decision.clarification.field.value
                            if decision.clarification.field is not None
                            else None
                        ),
                        "option_count": len(decision.clarification.options),
                    },
                )
                skill_usage = RunTokenUsage()
                tool_call_count = 0
                termination_reason = "CLARIFICATION_REQUIRED"
            # 6.8.可以分发：调用 Skill
            else:
                skill = skill_for_intent(decision.intent)
                assert skill is not None
                dispatch_sequence = policy_sequence + 1
                dispatch_step_id = f"step-dispatch-{request_suffix}"
                # 6.8.1.创建 WORKFLOW Step
                await recorder.start_step(
                    step_id=dispatch_step_id,
                    run_id=run_id,
                    sequence_number=dispatch_sequence,
                    step_type=AgentStepType.WORKFLOW,
                    step_name="dispatch_agent_skill",
                    input_summary=f"skill={skill.value};intent={decision.intent.value}",
                )
                await self._publish(
                    RunEventType.AGENT_ACTION_SELECTED,
                    run_id=run_id,
                    step_id=dispatch_step_id,
                    data={"skill": skill.value, "intent": decision.intent.value},
                )
                try:
                    # 6.8.2.调用skill
                    skill_execution = await self._skill_dispatcher.dispatch(
                        skill,
                        AgentSkillRequest(
                            run_id=run_id,
                            session_id=session_id,
                            trace_id=trace_id,
                            message=request.message,
                            identity=identity,
                            decision=decision,
                        ),
                    )
                    # 6.8.3.校验 Skill 返回类型
                    self._validate_skill_result(skill, skill_execution.result)
                except AgentSkillUnavailableError:
                    await recorder.mark_failed(
                        dispatch_step_id,
                        error_code="SKILL_NOT_AVAILABLE",
                        output_summary="skill_dispatch=failed",
                    )
                    raise
                except Exception as error:
                    await recorder.mark_failed(
                        dispatch_step_id,
                        error_code="SKILL_EXECUTION_ERROR",
                        output_summary="skill_dispatch=failed",
                    )
                    raise AgentSkillExecutionError("routed agent skill execution failed") from error
                await recorder.mark_succeeded(
                    dispatch_step_id,
                    output_summary=f"result_kind={skill_execution.result.kind.value}",
                )
                result = skill_execution.result
                skill_usage = skill_execution.token_usage
                tool_call_count = skill_execution.tool_call_count
                termination_reason = "COMPLETED"
            # 6.8.4.汇总运行指标
            total_usage = RunTokenUsage.from_counts(
                input_tokens=router_usage.input_tokens + skill_usage.input_tokens,
                output_tokens=router_usage.output_tokens + skill_usage.output_tokens,
            )
            # 6.8.5.标记运行成功终态
            await self._mark_succeeded(
                run_id,
                result=result,
                token_usage=total_usage,
                tool_call_count=tool_call_count,
                termination_reason=termination_reason,
            )
            # 6.8.6.发布完成事件并返回结果对象
            await self._publish(
                RunEventType.RUN_COMPLETED,
                run_id=run_id,
                data={
                    "session_id": session_id,
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "result_kind": result.kind.value,
                    "tool_call_count": tool_call_count,
                },
            )
            return AgentMessageExecution(
                run_id=run_id,
                session_id=session_id,
                result=result,
            )
        # 任一步骤异常时统一失败
        except ModelClientError as error:
            await self._fail_and_raise(
                run_id,
                code=error.code.value,
                message=str(error),
                retryable=error.retryable,
                error_step="route_intent",
                token_usage=(
                    routing_model.token_usage if routing_model is not None else RunTokenUsage()
                ),
                cause=error,
            )
        except InvalidRouterOutputError as error:
            await self._fail_and_raise(
                run_id,
                code="MODEL_OUTPUT_VALIDATION_ERROR",
                message="structured router output remained invalid after retry",
                retryable=False,
                error_step="route_intent",
                token_usage=(
                    routing_model.token_usage if routing_model is not None else RunTokenUsage()
                ),
                cause=error,
            )
        except ClarificationContinuationError as error:
            await self._fail_and_raise(
                run_id,
                code="CLARIFICATION_SELECTION_INVALID",
                message=str(error),
                retryable=False,
                error_step="route_policy",
                token_usage=RunTokenUsage(),
                cause=error,
            )
        except AgentSkillUnavailableError as error:
            await self._fail_and_raise(
                run_id,
                code="SKILL_NOT_AVAILABLE",
                message="routed agent skill is not available",
                retryable=False,
                error_step="dispatch_agent_skill",
                token_usage=router_usage,
                cause=error,
            )
        except AgentSkillExecutionError as error:
            await self._fail_and_raise(
                run_id,
                code="SKILL_EXECUTION_ERROR",
                message="routed agent skill execution failed",
                retryable=False,
                error_step="dispatch_agent_skill",
                token_usage=router_usage,
                cause=error,
            )
        except AgentMessageExecutionError:
            raise
        except Exception as error:
            _LOGGER.exception("agent_message_execution_failed", extra={"run_id": run_id})
            await self._fail_and_raise(
                run_id,
                code="AGENT_EXECUTION_ERROR",
                message="agent message execution failed",
                retryable=False,
                error_step="agent_turn",
                token_usage=RunTokenUsage(),
                cause=error,
            )
        raise AssertionError("unreachable")
    # 原子创建运行上下文服务：在事务中创建或锁定session
    async def _create_running_run(
        self,
        request: AgentMessageRequest,
        *,
        identity: BusinessIdentity,
        run_id: str,
        message_id: str,
    ) -> tuple[str, SessionContext]:
        now = datetime.now(UTC)
        # 前端不能通过 page_context.user_role 声称自己拥有另一个角色。可信身份来自请求身份解析，而不是页面参数
        if request.page_context is not None and request.page_context.user_role != identity.role:
            raise SessionAccessDeniedError()
        # 把以下操作放在同一个数据库事务中, 确保原子性
        async with self._database.session() as session, session.begin():
            sessions = AgentSessionRepository(session)
            messages = AgentMessageRepository(session)
            # 如果没有传 session_id, 则创建一个新的 session,绑定user_id和当前时间戳, 并设置过期时间
            if request.session_id is None:
                session_id = f"session-{uuid4().hex}"
                context = (
                    context_from_page(request.page_context)
                    if request.page_context is not None
                    else SessionContext()
                )
                agent_session = AgentSession(
                    session_id=session_id,
                    user_id=identity.user_id,
                    context=context.model_dump(mode="json"),
                    expires_at=now + self._session_ttl,
                )
                await sessions.create(agent_session)
                sequence_number = 1
            # 如果传了 session_id，会通过 get_for_update() 锁定 Session
            else:
                session_id = request.session_id
                existing_session = await sessions.get_for_update(session_id)
                # 对session进行校验
                SessionContextService.ensure_access(
                    existing_session,
                    identity=identity,
                    now=now,
                )
                assert existing_session is not None
                agent_session = existing_session
                context = SessionContextService.context(agent_session)
                if request.page_context is not None:
                    context = context_from_page(request.page_context, base=context)
                sequence_number = await messages.next_sequence_number(session_id)
                agent_session.context = context.model_dump(mode="json")
                agent_session.expires_at = now + self._session_ttl

            await messages.create(
                AgentMessage(
                    message_id=message_id,
                    session_id=session_id,
                    sequence_number=sequence_number,
                    role=AgentMessageRole.USER,
                    content=request.message,
                )
            )
            lifecycle = RunLifecycleService(AgentRunRepository(session))
            await lifecycle.create_run(
                run_id=run_id,
                session_id=session_id,
                request_message_id=message_id,
                version_snapshot=self._version_snapshot,
                page_context_snapshot=request.page_context,
            )
            await lifecycle.mark_running(run_id)
        return session_id, context

    async def _load_pending_decision(
        self,
        *,
        session_id: str,
        source_run_id: str,
    ) -> RoutingDecision:
        """只允许续接同一Session中成功返回CLARIFICATION的来源Run。"""

        async with self._database.session() as session:
            repository = AgentRunRepository(session)
            source = await repository.get(source_run_id)
            latest = await repository.latest_result_by_session(session_id)
        if (
            source is None
            or latest is None
            or latest.run_id != source_run_id
            or source.session_id != session_id
            or source.status is not AgentRunStatus.SUCCEEDED
            or source.router_result is None
            or source.final_result is None
        ):
            raise ClarificationContinuationError(
                "clarification source run was not found in this session"
            )
        try:
            result = _RESULT_ADAPTER.validate_python(source.final_result, strict=False)
            decision = RoutingDecision.model_validate(source.router_result, strict=False)
        except ValidationError as error:
            raise ClarificationContinuationError(
                "clarification source run is incompatible with the current contract"
            ) from error
        if not isinstance(result, ClarificationAgentResult):
            raise ClarificationContinuationError("source run is not waiting for clarification")
        if decision.clarification != result.clarification:
            raise ClarificationContinuationError(
                "clarification source run is internally inconsistent"
            )
        return decision
    # 记录路由决策
    async def _record_routing_decision(
        self,
        recorder: DatabaseWorkflowStepRecorder,
        *,
        run_id: str,
        request_suffix: str,
        sequence_number: int,
        decision: RoutingDecision,
    ) -> None:
        """把模型候选后的确定性参数合并和门禁记录为ROUTER Step。"""

        step_id = f"step-policy-{request_suffix}"
        await recorder.start_step(
            step_id=step_id,
            run_id=run_id,
            sequence_number=sequence_number,
            step_type=AgentStepType.ROUTER,
            step_name="apply_routing_policy",
            input_summary="entity_sources=user,session,page,candidate",
        )
        await recorder.mark_succeeded(
            step_id,
            output_summary=(
                f"intent={decision.intent.value};status={decision.status.value};"
                f"missing_count={len(decision.missing_fields)};"
                f"conflict_count={len(decision.entities.conflicts)}"
            ),
        )

    async def _save_decision(self, run_id: str, decision: RoutingDecision) -> None:
        """保存最终门禁决策, 而不是未合并的模型原始候选。"""

        async with self._database.session() as session, session.begin():
            await RunLifecycleService(AgentRunRepository(session)).record_router_result(
                run_id,
                router_result=decision,
            )
    # SessionContext 更新
    async def _update_session_context(
        self,
        session_id: str,
        *,
        identity: BusinessIdentity,
        decision: RoutingDecision,
    ) -> None:
        """只保存用户明确实体、路由意图和待选候选, 不复制业务事实。"""

        now = datetime.now(UTC)
        async with self._database.session() as session, session.begin():
            stored = await AgentSessionRepository(session).get_for_update(session_id)
            SessionContextService.ensure_access(stored, identity=identity, now=now)
            assert stored is not None
            context = SessionContextService.context(stored)
            confirmed = dict(context.confirmed_entities)
            candidates = {key: list(values) for key, values in context.candidate_entities.items()}
            for field, sourced in decision.entities.entities.items():
                if sourced.source is EntitySource.USER_MESSAGE:
                    confirmed[field.value] = sourced.value
                    candidates.pop(field.value, None)
            clarification = decision.clarification
            if clarification is not None and clarification.options and clarification.field:
                candidates[clarification.field.value] = [
                    option.value for option in clarification.options
                ]

            current_order_id = context.current_order_id
            selected_order = confirmed.get("order_id")
            if isinstance(selected_order, str):
                if current_order_id is not None and current_order_id != selected_order:
                    confirmed.pop("task_id", None)
                    candidates.pop("task_id", None)
                current_order_id = selected_order
            selected_task = confirmed.get("task_id")
            current_task_id = context.current_task_id
            if current_order_id is not None and isinstance(selected_task, str):
                current_task_id = selected_task
            elif current_order_id is None:
                current_task_id = None

            updated = context.model_copy(
                update={
                    "current_order_id": current_order_id,
                    "current_task_id": current_task_id,
                    "previous_intent": decision.intent,
                    "confirmed_entities": confirmed,
                    "candidate_entities": candidates,
                }
            )
            # model_copy不执行完整校验, 重新进入唯一Schema防止保存失配上下文。
            validated = SessionContext.model_validate(updated.model_dump(mode="json"))
            stored.context = validated.model_dump(mode="json")
            stored.expires_at = now + self._session_ttl
            await session.flush()
    # 标记成功
    async def _mark_succeeded(
        self,
        run_id: str,
        *,
        result: AgentMessageResult,
        token_usage: RunTokenUsage,
        tool_call_count: int,
        termination_reason: str,
    ) -> None:
        """把统一结果Envelope和实际用量保存为唯一成功终态。"""
        # 保存最终结果
        async with self._database.session() as session, session.begin():
            await RunLifecycleService(AgentRunRepository(session)).mark_succeeded(
                run_id,
                final_result=result.model_dump(mode="json"),
                token_usage=token_usage,
                tool_call_count=tool_call_count,
                termination_reason=termination_reason,
            )

    async def _fail_and_raise(
        self,
        run_id: str,
        *,
        code: str,
        message: str,
        retryable: bool,
        error_step: str,
        token_usage: RunTokenUsage,
        cause: Exception,
    ) -> None:
        """尽力持久化失败终态并发布不含内部正文的终态事件。"""

        async with self._database.session() as session, session.begin():
            run = await AgentRunRepository(session).get(run_id)
            if run is not None and run.status is AgentRunStatus.RUNNING:
                await RunLifecycleService(AgentRunRepository(session)).mark_failed(
                    run_id,
                    error_code=code,
                    error_step=error_step,
                    token_usage=token_usage,
                    termination_reason="EXECUTION_ERROR",
                )
        await self._publish(
            RunEventType.RUN_FAILED,
            run_id=run_id,
            data={
                "error_code": code,
                "error_step": error_step,
                "retryable": retryable,
            },
        )
        raise AgentMessageExecutionError(
            run_id=run_id,
            code=code,
            message=message,
            retryable=retryable,
            error_step=error_step,
        ) from cause
    # 校验skill结果类型, 防止Skill返回的结果越过kind边界或由Skill伪造澄清。
    @staticmethod
    def _validate_skill_result(
        skill: BusinessSkill,
        result: AgentMessageResult,
    ) -> None:
        """防止错误Skill结果越过kind边界或由Skill伪造澄清。"""

        expected_types: dict[BusinessSkill, type[object]] = {
            BusinessSkill.ORDER_STATUS: OrderStatusResult,
            BusinessSkill.DIAGNOSIS: DiagnosisAgentResult,
            BusinessSkill.SPECIFICATION: SpecificationAnswerAgentResult,
            BusinessSkill.REVIEW: ApprovalAgentResult,
        }
        if not isinstance(result, expected_types[skill]):
            raise ValueError("agent skill returned an incompatible result kind")

    async def _publish(
        self,
        event_type: RunEventType,
        *,
        run_id: str | None,
        step_id: str | None = None,
        data: dict[str, str | int | float | bool | None],
    ) -> None:
        """可选发布受控SSE事件, 不发送消息正文、模型输出或上下文快照。"""

        if self._event_sink is not None:
            await self._event_sink.publish(
                event_type,
                run_id=run_id,
                step_id=step_id,
                data=data,
            )


__all__ = [
    "AgentMessageExecution",
    "AgentMessageExecutionError",
    "AgentMessageService",
    "AgentSkillDispatcher",
    "AgentSkillExecution",
    "AgentSkillExecutionError",
    "AgentSkillRequest",
    "AgentSkillUnavailableError",
    "ClarificationContinuationError",
    "UnavailableAgentSkillDispatcher",
]
