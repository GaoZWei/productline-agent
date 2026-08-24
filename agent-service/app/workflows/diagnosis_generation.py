"""根据确定性业务裁决生成诊断文案, 并安全应用可选模型改写。"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from pydantic import ValidationError

from app.schemas.tools import QualityIssue, ReviewRecord
from app.schemas.workflow import (
    BlockingStage,
    DiagnosisNarrative,
    DiagnosisResult,
    Evidence,
    OrderDiagnosisState,
    RootCause,
    Suggestion,
)

_PRODUCTION_FAILED = frozenset({"FAILED", "BLOCKED"})
_PRODUCTION_ACTIVE = frozenset({"PENDING", "RUNNING"})
_QUALITY_UNRESOLVED = frozenset({"OPEN", "PROCESSING"})
_DELIVERY_BLOCKED = frozenset({"NOT_READY", "FAILED", "BLOCKED"})


class DiagnosisNarrativeModel(Protocol):
    """模型适配器契约; 实现方必须返回可由严格 Schema 校验的结构化对象。"""

    def generate(self, diagnosis: DiagnosisResult) -> Awaitable[object]:
        """只改写阶段、根因和建议说明, 不接收修改业务事实的入口。"""


class InvalidDiagnosisNarrativeError(ValueError):
    """模型文案没有通过 Schema 或稳定代码一致性校验。"""

# 规则诊断结果生成, 只负责生成文案
def generate_rule_diagnosis(state: OrderDiagnosisState) -> DiagnosisResult:
    """根据规则裁决和已加载 Tool 事实装配可追溯的完整诊断结果。"""
    # 前一个节点已经生成规则裁决, 且已加载 Tool 事实
    decision = state["rule_decision"]
    if decision is None:
        raise ValueError("rule decision is required before diagnosis generation")

    stage = decision.blocking_stage
    # 根据 blocking_stage 选择对应生成函数, 生成函数返回统一的五部分诊断结果
    builders = {
        BlockingStage.PRODUCTION: _production_diagnosis,
        BlockingStage.PRODUCTION_BLOCKED: _production_blocked_diagnosis,
        BlockingStage.QUALITY_REVIEW: _quality_review_diagnosis,
        BlockingStage.REVIEW: _review_diagnosis,
        BlockingStage.DELIVERY: _delivery_diagnosis,
        BlockingStage.NONE: _no_blocker_diagnosis,
        BlockingStage.INSUFFICIENT_INFORMATION: _insufficient_diagnosis,
    }
    summary, root_causes, evidence, suggestions, confidence = builders[stage](state)
    # 统一装配成 DiagnosisResult 格式返回
    return DiagnosisResult(
        order_id=decision.order_id,
        blocking_stage=stage,
        summary=summary,
        root_causes=root_causes,
        evidence=evidence,
        suggestions=suggestions,
        confidence=confidence,
    )

# 仅保护模型输出中的自然语言字段, 不修改业务事实
def apply_model_narrative(
    rule_result: DiagnosisResult,
    raw_output: object,
) -> DiagnosisResult:
    """校验模型结构及稳定代码后, 仅覆盖规则结果中的自然语言字段。"""
    # 第一层层是 Pydantic Schema 校验   
    try:  
        narrative = DiagnosisNarrative.model_validate(raw_output)
    except ValidationError as exc:
        raise InvalidDiagnosisNarrativeError("model narrative schema validation failed") from exc

    expected_root_codes = [cause.code for cause in rule_result.root_causes]
    actual_root_codes = [cause.code for cause in narrative.root_causes]
    expected_action_types = [item.action_type for item in rule_result.suggestions]
    actual_action_types = [item.action_type for item in narrative.suggestions]
    # 第二层是稳定代码一致性检查
    if actual_root_codes != expected_root_codes:
        raise InvalidDiagnosisNarrativeError("model narrative changed root cause codes")
    if actual_action_types != expected_action_types:
        raise InvalidDiagnosisNarrativeError("model narrative changed suggestion action types")

    return rule_result.model_copy(
        update={
            "summary": narrative.summary,
            "root_causes": [
                RootCause(code=item.code, description=item.description)
                for item in narrative.root_causes
            ],
            "suggestions": [
                Suggestion(
                    action_type=item.action_type,
                    description=item.description,
                )
                for item in narrative.suggestions
            ],
        }
    )


type DiagnosisParts = tuple[
    str,
    list[RootCause],
    list[Evidence],
    list[Suggestion],
    float,
]


def _production_diagnosis(state: OrderDiagnosisState) -> DiagnosisParts:
    active_task = next(
        (
            (index, task)
            for index, task in enumerate(state["tasks"])
            if task.status in _PRODUCTION_ACTIVE
        ),
        None,
    )
    if active_task is not None:
        task_index, task = active_task
        evidence = Evidence(
            source_type="TOOL",
            tool_name="get_related_tasks",
            field_path=f"tasks[{task_index}].status",
            value=task.status,
            description=f"{task.task_id}生产状态为{task.status}",
        )
    else:
        for task in state["tasks"]:
            progress = state["progress"][task.task_id]
            for step_index, step in enumerate(progress.steps):
                if step.status in _PRODUCTION_ACTIVE:
                    evidence = Evidence(
                        source_type="TOOL",
                        tool_name="get_production_progress",
                        field_path=f"steps[{step_index}].status",
                        value=step.status,
                        description=f"{step.step_id}生产步骤状态为{step.status}",
                    )
                    break
            else:
                continue
            break
        else:
            raise ValueError("production decision has no matching fact")
    return (
        "订单当前处于正常生产环节。尚未发现异常阻塞。",
        [RootCause(code="PRODUCTION_IN_PROGRESS", description="关联生产任务尚未完成")],
        [evidence],
        [
            Suggestion(
                action_type="WAIT_FOR_PRODUCTION",
                description="等待生产任务完成后再检查质检状态",
            )
        ],
        1.0,
    )


def _production_blocked_diagnosis(state: OrderDiagnosisState) -> DiagnosisParts:
    for task_index, task in enumerate(state["tasks"]):
        if task.status in _PRODUCTION_FAILED:
            evidence = Evidence(
                source_type="TOOL",
                tool_name="get_related_tasks",
                field_path=f"tasks[{task_index}].status",
                value=task.status,
                description=f"{task.task_id}生产状态为{task.status}",
            )
            description = "关联生产任务失败或被阻塞"
            break
        progress = state["progress"][task.task_id]
        for step_index, step in enumerate(progress.steps):
            if step.status in _PRODUCTION_FAILED:
                evidence = Evidence(
                    source_type="TOOL",
                    tool_name="get_production_progress",
                    field_path=f"steps[{step_index}].status",
                    value=step.status,
                    description=f"{step.step_id}生产步骤状态为{step.status}",
                )
                description = "关联生产步骤失败或被阻塞"
                break
        else:
            continue
        break
    else:
        raise ValueError("production blocked decision has no matching fact")
    return (
        "订单阻塞在生产环节。",
        [RootCause(code="PRODUCTION_EXECUTION_BLOCKED", description=description)],
        [evidence],
        [Suggestion(action_type="RETRY_PRODUCTION", description="排查失败原因后重新执行生产任务")],
        1.0,
    )

# 生成诊断(四条字段级证据)
def _quality_review_diagnosis(state: OrderDiagnosisState) -> DiagnosisParts:
    issues = _indexed_issues(state, statuses=_QUALITY_UNRESOLVED)
    root_causes: list[RootCause] = []
    evidence: list[Evidence] = []
    suggestions: list[Suggestion] = []
    affected_task_ids = {task_id for task_id, _, _ in issues}
    for task_index, task in enumerate(state["tasks"]):
        if task.task_id in affected_task_ids:
            # 生产任务状态
            evidence.append(
                Evidence(
                    source_type="TOOL",
                    tool_name="get_related_tasks",
                    field_path=f"tasks[{task_index}].status",
                    value=task.status,
                    description=f"{task.task_id}生产状态为{task.status}",
                )
            )
    for _, issue_index, issue in issues:
        code = (
            "OPEN_COORDINATE_SYSTEM_ISSUE"
            if issue.issue_type == "COORDINATE_SYSTEM"
            else "UNRESOLVED_QUALITY_ISSUE"
        )
        description = (
            "关联任务存在未关闭的坐标系质量问题"
            if issue.issue_type == "COORDINATE_SYSTEM"
            else "关联任务存在未处理完的质量问题"
        )
        _append_unique_root_cause(root_causes, code, description)
        # 质检问题状态
        evidence.append(
            Evidence(
                source_type="TOOL",
                tool_name="get_quality_issues",
                field_path=f"issues[{issue_index}].status",
                value=issue.status,
                description=f"{issue.issue_id}问题状态为{issue.status}",
            )
        )
    pending_review = _first_review_for_issues(state, {item[2].issue_id for item in issues})
    if pending_review is not None and pending_review[2].status != "APPROVED":
        _, review_index, review = pending_review
        _append_unique_root_cause(root_causes, "REVIEW_PENDING", "质检复核尚未完成")
        # 复核记录状态
        evidence.append(
            Evidence(
                source_type="TOOL",
                tool_name="get_review_result",
                field_path=f"reviews[{review_index}].status",
                value=review.status,
                description=f"{review.review_id}复核状态为{review.status}",
            )
        )
    delivery = state["delivery"]
    if delivery is not None:
        for record_index, record in enumerate(delivery.records):
            if record.status in _DELIVERY_BLOCKED:
                # 交付记录状态
                evidence.append(
                    Evidence(
                        source_type="TOOL",
                        tool_name="get_delivery_status",
                        field_path=f"records[{record_index}].status",
                        value=record.status,
                        description=f"{record.delivery_id}交付状态为{record.status}",
                    )
                )
    if any(issue.issue_type == "COORDINATE_SYSTEM" for _, _, issue in issues):
        suggestions.append(
            Suggestion(
                action_type="CREATE_COORDINATE_SYSTEM_REWORK",
                description="创建坐标系处理返工任务",
            )
        )
    else:
        suggestions.append(
            Suggestion(action_type="CREATE_QUALITY_REWORK", description="创建质量问题返工任务")
        )
    suggestions.append(
        Suggestion(action_type="RESUBMIT_REVIEW", description="问题处理完成后重新提交复核")
    )
    return ("订单阻塞在质量复核环节。", root_causes, evidence, suggestions, 1.0)


def _review_diagnosis(state: OrderDiagnosisState) -> DiagnosisParts:
    reviews = _indexed_reviews(state)
    for _, review_index, review in reviews:
        if review.status != "APPROVED":
            return (
                "订单阻塞在复核环节。",
                [RootCause(code="REVIEW_NOT_APPROVED", description="质量问题复核尚未通过")],
                [
                    Evidence(
                        source_type="TOOL",
                        tool_name="get_review_result",
                        field_path=f"reviews[{review_index}].status",
                        value=review.status,
                        description=f"{review.review_id}复核状态为{review.status}",
                    )
                ],
                [
                    Suggestion(
                        action_type="COMPLETE_REVIEW",
                        description="完成问题处理并重新提交复核",
                    )
                ],
                1.0,
            )
    for _, issue_index, issue in _indexed_issues(state, statuses=frozenset({"RESOLVED"})):
        return (
            "订单阻塞在复核环节。",
            [RootCause(code="REVIEW_MISSING", description="已处理的质量问题尚无通过复核记录")],
            [
                Evidence(
                    source_type="TOOL",
                    tool_name="get_quality_issues",
                    field_path=f"issues[{issue_index}].status",
                    value=issue.status,
                    description=f"{issue.issue_id}问题状态为{issue.status}但尚未通过复核",
                )
            ],
            [Suggestion(action_type="SUBMIT_REVIEW", description="为已处理问题提交复核")],
            1.0,
        )
    raise ValueError("review decision has no matching fact")


def _delivery_diagnosis(state: OrderDiagnosisState) -> DiagnosisParts:
    delivery = state["delivery"]
    if delivery is None:
        raise ValueError("delivery decision requires delivery facts")
    record_index, record = next(
        (index, record)
        for index, record in enumerate(delivery.records)
        if record.status in _DELIVERY_BLOCKED
    )
    return (
        "订单阻塞在交付环节。",
        [RootCause(code="DELIVERY_NOT_READY", description="交付记录尚未就绪或已被阻塞")],
        [
            Evidence(
                source_type="TOOL",
                tool_name="get_delivery_status",
                field_path=f"records[{record_index}].status",
                value=record.status,
                description=f"{record.delivery_id}交付状态为{record.status}",
            )
        ],
        [
            Suggestion(
                action_type="RESOLVE_DELIVERY_BLOCKER",
                description="处理交付阻塞后重新发起交付",
            )
        ],
        1.0,
    )


def _no_blocker_diagnosis(state: OrderDiagnosisState) -> DiagnosisParts:
    delivery = state["delivery"]
    if delivery is None or not delivery.records:
        raise ValueError("no blocker decision requires delivery facts")
    record = delivery.records[0]
    return (
        "当前未发现生产、质检、复核或交付阻塞。",
        [],
        [
            Evidence(
                source_type="TOOL",
                tool_name="get_delivery_status",
                field_path="records[0].status",
                value=record.status,
                description=f"{record.delivery_id}交付状态为{record.status}",
            )
        ],
        [Suggestion(action_type="CONTINUE_DELIVERY", description="按当前业务流程继续交付")],
        1.0,
    )


def _insufficient_diagnosis(state: OrderDiagnosisState) -> DiagnosisParts:
    order = state["order"]
    evidence = (
        []
        if order is None
        else [
            Evidence(
                source_type="TOOL",
                tool_name="get_order_detail",
                field_path="status",
                value=order.status,
                description=f"仅能确认{order.order_id}订单状态为{order.status}",
            )
        ]
    )
    return (
        "当前业务事实不完整。无法可靠判断订单阻塞环节。",
        [
            RootCause(
                code="INSUFFICIENT_BUSINESS_FACTS",
                description="诊断所需业务事实缺失或归属不一致",
            )
        ],
        evidence,
        [
            Suggestion(
                action_type="RELOAD_BUSINESS_FACTS",
                description="补齐并重新校验业务事实后再次诊断",
            )
        ],
        0.0,
    )


def _indexed_issues(
    state: OrderDiagnosisState,
    *,
    statuses: frozenset[str],
) -> list[tuple[str, int, QualityIssue]]:
    """按任务和响应顺序返回指定状态的质量问题。"""

    return [
        (task.task_id, issue_index, issue)
        for task in state["tasks"]
        for issue_index, issue in enumerate(state["quality_issues"][task.task_id])
        if issue.status in statuses
    ]


def _indexed_reviews(
    state: OrderDiagnosisState,
) -> list[tuple[str, int, ReviewRecord]]:
    """按任务和响应顺序返回全部复核记录。"""

    return [
        (task.task_id, review_index, review)
        for task in state["tasks"]
        if state["reviews"][task.task_id] is not None
        for review_index, review in enumerate(state["reviews"][task.task_id].reviews)  # type: ignore[union-attr]
    ]


def _first_review_for_issues(
    state: OrderDiagnosisState,
    issue_ids: set[str],
) -> tuple[str, int, ReviewRecord] | None:
    return next(
        (item for item in _indexed_reviews(state) if item[2].issue_id in issue_ids),
        None,
    )


def _append_unique_root_cause(
    causes: list[RootCause],
    code: str,
    description: str,
) -> None:
    if all(cause.code != code for cause in causes):
        causes.append(RootCause(code=code, description=description))
