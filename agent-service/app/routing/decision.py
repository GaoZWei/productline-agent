"""M3.6 置信度分级、确定性澄清和补参恢复。"""

from __future__ import annotations

from typing import Final

from pydantic import ValidationError

from app.routing.intent_catalog import (
    Intent,
    RoutingParameter,
    required_parameters_for,
)
from app.schemas.routing import (
    ClarificationReason,
    ClarificationRequest,
    ConfidenceLevel,
    EntityConflict,
    EntityMergeResult,
    EntitySelection,
    EntitySource,
    RouterEntities,
    RouterResult,
    RoutingDecision,
    RoutingDecisionStatus,
    RoutingEntityName,
    SourcedEntity,
)

HIGH_CONFIDENCE_THRESHOLD: Final = 0.85
MEDIUM_CONFIDENCE_THRESHOLD: Final = 0.60

_INTENT_LABELS: Final[dict[Intent, str]] = {
    Intent.ORDER_QUERY: "订单查询",
    Intent.ORDER_DIAGNOSIS: "订单诊断",
    Intent.TASK_TRACKING: "任务跟踪",
    Intent.SPEC_QA: "规范问答",
    Intent.REVIEW_GENERATION: "复核草稿生成",
    Intent.UNKNOWN: "未知意图",
}

_FIELD_LABELS: Final[dict[RoutingEntityName, str]] = {
    RoutingEntityName.ORDER_ID: "订单",
    RoutingEntityName.TASK_ID: "任务",
    RoutingEntityName.ISSUE_ID: "质检问题",
    RoutingEntityName.BATCH_ID: "批次",
    RoutingEntityName.PRODUCT_TYPE: "产品类型",
    RoutingEntityName.SATELLITE_TYPE: "卫星类型",
}

_PARAMETER_FIELDS: Final[dict[RoutingParameter, RoutingEntityName]] = {
    RoutingParameter.ORDER_ID: RoutingEntityName.ORDER_ID,
    RoutingParameter.TASK_ID: RoutingEntityName.TASK_ID,
}

_MISSING_QUESTIONS: Final[dict[RoutingParameter, str]] = {
    RoutingParameter.ORDER_ID: "请提供要处理的订单编号。",
    RoutingParameter.TASK_ID: "请提供要处理的任务编号。",
}


class InvalidClarificationSelectionError(ValueError):
    """用户选择与当前待澄清字段或候选集合不一致。"""

# 置信度等级计算函数
def confidence_level_for(confidence: float) -> ConfidenceLevel:
    """按照M3.6固定边界把0到1置信度分为高、中、低三级。"""

    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:  # 大于0.85 则高置信度等级
        return ConfidenceLevel.HIGH
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:  # 大于0.60 则中置信度等级
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW  # 其他情况低置信度等级

# 模型没有返回实体, 需要根据合并后的实体重新计算缺失字段
def _missing_fields(
    intent: Intent,
    merge_result: EntityMergeResult,
) -> tuple[RoutingParameter, ...]:
    """只根据服务端合并后的实体重新计算必填参数。"""

    entities = merge_result.to_router_entities()
    return tuple(
        parameter
        for parameter in required_parameters_for(intent)
        if not entities.contains(parameter)
    )


def _conflict_for(
    merge_result: EntityMergeResult,
    field: RoutingEntityName,
) -> EntityConflict:
    """返回未解析字段对应冲突; 缺失表示内部合并结果不自洽。"""

    for conflict in merge_result.conflicts:
        if conflict.field is field:
            return conflict
    raise ValueError("unresolved entity field must have a conflict")

# 决策原因的优先顺序 (一次路由同时存在多个问题时应先澄清哪一个?)
# 判断顺序:
# 1. UNKNOWN
# 2. 未解决实体冲突
# 3. 必填参数缺失
# 4. 低置信度
# 5. 中置信度未确认
# 6. 模型主动请求澄清
# 7. READY
def _compose_decision(
    *,
    intent: Intent,
    confidence: float,
    entities: EntityMergeResult,
    model_requested_clarification: bool,
    intent_confirmed: bool,
) -> RoutingDecision:
    """按稳定原因优先级构造唯一的路由决策。"""

    confidence_level = confidence_level_for(confidence)
    missing_fields = _missing_fields(intent, entities)
    clarification: ClarificationRequest | None = None
    # 保证每次只处理一个主要问题
    if intent is Intent.UNKNOWN:
        clarification = ClarificationRequest(
            reason=ClarificationReason.UNKNOWN_INTENT,
            question=(
                "我暂时无法识别这个请求。请说明要查询订单、跟踪任务、"
                "咨询规范还是生成复核草稿。"
            ),
        )
    elif entities.unresolved_fields:
        field = entities.unresolved_fields[0]
        conflict = _conflict_for(entities, field)
        label = _FIELD_LABELS[field]
        clarification = ClarificationRequest(
            reason=ClarificationReason.ENTITY_CONFLICT,
            question=f"检测到多个{label}候选, 请选择一个{label}。",
            field=field,
            options=conflict.candidates,
        )
    elif missing_fields:
        parameter = missing_fields[0]
        clarification = ClarificationRequest(
            reason=ClarificationReason.MISSING_PARAMETER,
            question=_MISSING_QUESTIONS[parameter],
            field=_PARAMETER_FIELDS[parameter],
        )
    elif confidence_level is ConfidenceLevel.LOW:
        clarification = ClarificationRequest(
            reason=ClarificationReason.LOW_CONFIDENCE,
            question="我还不能确定你的意图。请补充要处理的业务对象和目标。",
        )
    elif confidence_level is ConfidenceLevel.MEDIUM and not intent_confirmed:
        clarification = ClarificationRequest(
            reason=ClarificationReason.CONFIRM_INTENT,
            question=f"当前识别意图为“{_INTENT_LABELS[intent]}”, 请确认是否继续。",
        )
    elif model_requested_clarification:
        clarification = ClarificationRequest(
            reason=ClarificationReason.MODEL_REQUEST,
            question="当前请求仍有歧义。请补充更明确的业务目标。",
        )

    status = (
        RoutingDecisionStatus.READY
        if clarification is None
        else RoutingDecisionStatus.NEEDS_CLARIFICATION
    )
    return RoutingDecision(
        intent=intent,
        confidence=confidence,
        confidence_level=confidence_level,
        entities=entities,
        missing_fields=missing_fields,
        status=status,
        clarification=clarification,
        intent_confirmed=intent_confirmed,
        model_requested_clarification=model_requested_clarification,
    )

# 它组合路由决策 
def build_routing_decision(
    *,
    raw_result: RouterResult,  # 模型负责的意图和置信度
    merge_result: EntityMergeResult,  # 从服务端负责的最终实体、来源和冲突
) -> RoutingDecision:
    """组合模型结果和可信实体; 模型缺参可由上下文合并结果补齐。"""

    model_requested = (
        raw_result.need_clarification and not raw_result.missing_fields
    )
    return _compose_decision(
        intent=raw_result.intent,
        confidence=raw_result.confidence,
        entities=merge_result,
        model_requested_clarification=model_requested,
        intent_confirmed=False,
    )


def _validated_selection(selection: EntitySelection) -> SourcedEntity:
    """按照用户选择的目标字段重新校验值, 不在异常中包含原值。"""

    try:
        validated = RouterEntities.model_validate(
            {selection.field.value: selection.value}
        )
    except ValidationError as exc:
        raise InvalidClarificationSelectionError(
            f"invalid selection for {selection.field.value}"
        ) from exc
    value = getattr(validated, selection.field.value)
    if value is None:  # pragma: no cover - 防御未来Schema变化。
        raise InvalidClarificationSelectionError(
            f"invalid selection for {selection.field.value}"
        )
    return SourcedEntity(value=value, source=EntitySource.USER_MESSAGE)

# 用户选择后恢复实体
def _apply_selection(
    merge_result: EntityMergeResult,
    selection: EntitySelection,
) -> EntityMergeResult:
    """把用户补参升级为最高来源并更新对应冲突。"""

    selected = _validated_selection(selection)
    entities = dict(merge_result.entities)
    entities[selection.field] = selected
    conflicts: list[EntityConflict] = []
    found_conflict = False

    for conflict in merge_result.conflicts:
        if conflict.field is not selection.field:
            conflicts.append(conflict)
            continue
        found_conflict = True
        other_candidates = tuple(
            candidate
            for candidate in conflict.candidates
            if candidate.value != selected.value
        )
        candidates = (selected, *other_candidates)
        if len(candidates) > 1:
            conflicts.append(
                conflict.model_copy(
                    update={
                        "selected": selected,
                        "candidates": candidates,
                        "resolved_by_priority": True,
                    }
                )
            )

    if not found_conflict:
        previous = merge_result.entities.get(selection.field)
        if previous is not None and previous.value != selected.value:
            conflicts.append(
                EntityConflict(
                    field=selection.field,
                    selected=selected,
                    candidates=(selected, previous),
                    resolved_by_priority=True,
                )
            )

    unresolved = tuple(
        field
        for field in merge_result.unresolved_fields
        if field is not selection.field
    )
    return EntityMergeResult(
        entities=entities,
        conflicts=tuple(conflicts),
        unresolved_fields=unresolved,
    )

# 恢复模型, 检查用户提交字段是否匹配当前意图
def resume_routing_after_selection(
    pending: RoutingDecision,
    selection: EntitySelection,
) -> RoutingDecision:
    """应用用户明确选择并恢复原意图, 不重新调用模型。"""

    clarification = pending.clarification
    if (
        pending.status is not RoutingDecisionStatus.NEEDS_CLARIFICATION
        or clarification is None
        or clarification.reason
        not in {
            ClarificationReason.ENTITY_CONFLICT,
            ClarificationReason.MISSING_PARAMETER,
        }
        or clarification.field is not selection.field
    ):
        raise InvalidClarificationSelectionError(
            "selection does not match pending clarification"
        )
    if clarification.options and all(
        option.value != selection.value for option in clarification.options
    ):
        raise InvalidClarificationSelectionError(
            "selection is not one of the offered candidates"
        )
    return _compose_decision(
        intent=pending.intent,
        confidence=pending.confidence,
        entities=_apply_selection(pending.entities, selection),
        model_requested_clarification=pending.model_requested_clarification,
        intent_confirmed=pending.intent_confirmed,
    )

# 用户确认中置信度候选意图
def confirm_routing_intent(pending: RoutingDecision) -> RoutingDecision:
    """确认中置信度候选意图并恢复同一决策。"""

    if (
        pending.clarification is None
        or pending.clarification.reason is not ClarificationReason.CONFIRM_INTENT
    ):
        raise InvalidClarificationSelectionError(
            "decision is not waiting for intent confirmation"
        )
    return _compose_decision(
        intent=pending.intent,
        confidence=pending.confidence,
        entities=pending.entities,
        model_requested_clarification=pending.model_requested_clarification,
        intent_confirmed=True,
    )
