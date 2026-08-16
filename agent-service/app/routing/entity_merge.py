"""M3.5 路由实体来源标记、固定优先级合并和冲突检测。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, cast

from pydantic import ValidationError

from app.schemas.context import PageContext
from app.schemas.routing import (
    EntityConflict,
    EntityExtractionResult,
    EntityMergeResult,
    EntitySource,
    RouterEntities,
    RoutingEntityName,
    SourcedEntity,
)
from app.schemas.session import SessionContext
# 来源到合并优先级, 4 是用户消息, 3 是会话确认, 2 是页面上下文, 1 是会话候选值
_SOURCE_PRIORITY: Final[dict[EntitySource, int]] = {
    EntitySource.USER_MESSAGE: 4,
    EntitySource.CONFIRMED_SESSION: 3,
    EntitySource.PAGE_CONTEXT: 2,
    EntitySource.SESSION_CANDIDATE: 1,
}

# 异常类型 记录 字段名 + 来源
class InvalidEntityCandidateError(ValueError):
    """表示某个受支持字段的上下文候选值不符合路由实体契约。"""

    def __init__(self, *, field: RoutingEntityName, source: EntitySource) -> None:
        self.field = field
        self.source = source
        super().__init__(
            f"invalid candidate for {field.value} from source {source.value}"
        )

# 所有参数都要重新校验, 不能直接使用提取的实体
def _validated_value(
    *,
    field: RoutingEntityName,
    value: object,
    source: EntitySource,
) -> str:
    """按目标字段复用 RouterEntities 校验, 错误中不包含原始候选值。"""
    # 校验对应的字段, 如果校验失败, 则抛出异常, 否则返回校验后的值
    try:
        validated = RouterEntities.model_validate({field.value: value})
    except ValidationError as exc:
        raise InvalidEntityCandidateError(field=field, source=source) from exc
    result = getattr(validated, field.value)
    if result is None:  # pragma: no cover - 字段模型变化时的防御性检查。
        raise InvalidEntityCandidateError(field=field, source=source)
    return cast(str, result)

# 同来源、同值先去重
def _append_candidate(
    candidates: dict[RoutingEntityName, list[SourcedEntity]],
    *,
    field: RoutingEntityName,
    value: object,
    source: EntitySource,
) -> None:
    """校验并加入候选集合, 同来源同值只保留一次。"""

    sourced = SourcedEntity(
        value=_validated_value(field=field, value=value, source=source),
        source=source,
    )
    field_candidates = candidates.setdefault(field, [])
    if sourced not in field_candidates:
        field_candidates.append(sourced)


def _append_router_entities(
    candidates: dict[RoutingEntityName, list[SourcedEntity]],
    entities: RouterEntities,
    *,
    source: EntitySource,
) -> None:
    """把非空 RouterEntities 字段加入指定来源。"""

    for field in RoutingEntityName:
        value = getattr(entities, field.value)
        if value is not None:
            _append_candidate(candidates, field=field, value=value, source=source)

# 已确认会话参数优先级第二
def _append_confirmed_session(
    candidates: dict[RoutingEntityName, list[SourcedEntity]],
    context: SessionContext,
) -> None:
    """加入用户已确认会话实体及当前会话主对象。"""

    if context.current_order_id is not None:
        _append_candidate(
            candidates,
            field=RoutingEntityName.ORDER_ID,
            value=context.current_order_id,
            source=EntitySource.CONFIRMED_SESSION,
        )
    if context.current_task_id is not None:
        _append_candidate(
            candidates,
            field=RoutingEntityName.TASK_ID,
            value=context.current_task_id,
            source=EntitySource.CONFIRMED_SESSION,
        )
    for field in RoutingEntityName:
        if field.value in context.confirmed_entities:
            _append_candidate(
                candidates,
                field=field,
                value=context.confirmed_entities[field.value],
                source=EntitySource.CONFIRMED_SESSION,
            )


# 页面上下文参数优先级第三
def _append_page_context(
    candidates: dict[RoutingEntityName, list[SourcedEntity]],
    context: PageContext,
) -> None:
    """加入当前页面明确提供的业务对象提示。"""

    for field in RoutingEntityName:
        value = getattr(context, field.value)
        if value is not None:
            _append_candidate(
                candidates,
                field=field,
                value=value,
                source=EntitySource.PAGE_CONTEXT,
            )

# 会话候选值参数优先级第四
def _append_session_candidates(
    candidates: dict[RoutingEntityName, list[SourcedEntity]],
    context: SessionContext,
) -> None:
    """加入上一轮尚未确认的临时候选实体。"""

    for field in RoutingEntityName:
        for value in context.candidate_entities.get(field.value, ()):
            _append_candidate(
                candidates,
                field=field,
                value=value,
                source=EntitySource.SESSION_CANDIDATE,
            )


def _highest_source_for_value(candidates: Iterable[SourcedEntity]) -> SourcedEntity:
    """同一值来自多个位置时保留最高优先级来源。"""

    return max(candidates, key=lambda item: _SOURCE_PRIORITY[item.source])

# 核心合并算法
def merge_routing_entities(
    *,
    extraction: EntityExtractionResult,  # 模型从用户本轮消息明确提取的实体
    page_context: PageContext | None = None,  # 当前页面提示
    session_context: SessionContext | None = None,  # 已确认实体和上一轮临时候选实体
) -> EntityMergeResult:
    """按固定优先级合并实体并保留不同值冲突, 不修改任何输入。"""
    # 第一步：收集所有候选值 （只是建立候选池）
    candidates: dict[RoutingEntityName, list[SourcedEntity]] = {}
    # 收集用户本轮实体 extraction.entities 中所有非空字段都标记为 USER_MESSAGE
    _append_router_entities(
        candidates,
        extraction.entities,
        source=EntitySource.USER_MESSAGE,
    )
    # 收集已确认会话实体 session_context 中所有非空字段都标记为 CONFIRMED_SESSION
    if session_context is not None:
        _append_confirmed_session(candidates, session_context)
    # 收集页面上下文实体 page_context 中所有非空字段都标记为 PAGE_CONTEXT
    if page_context is not None:
        _append_page_context(candidates, page_context)
    # 收集会话候选值实体 session_context 中所有非空字段都标记为 SESSION_CANDIDATE
    if session_context is not None:
        _append_session_candidates(candidates, session_context)

    selected_entities: dict[RoutingEntityName, SourcedEntity] = {}
    conflicts: list[EntityConflict] = []
    unresolved_fields: list[RoutingEntityName] = []
    # 按字段独立处理候选值
    for field in RoutingEntityName:
        field_candidates = candidates.get(field, [])
        if not field_candidates:
            continue
        # 第一次分组：按照“值”分组  
        by_value: dict[str, list[SourcedEntity]] = {}
        for candidate in field_candidates:
            by_value.setdefault(candidate.value, []).append(candidate)
        distinct_candidates = tuple(
            sorted(
                (
                    _highest_source_for_value(same_value)  # 同一个值只保留最高来源的
                    for same_value in by_value.values()
                ),
                key=lambda item: (-_SOURCE_PRIORITY[item.source], item.value),
            )
        )
        # 找出最高优先级的候选值
        highest_priority = max(
            _SOURCE_PRIORITY[candidate.source] for candidate in distinct_candidates
        )
        # 取出全部最高优先级候选值
        highest_candidates = tuple(
            candidate
            for candidate in distinct_candidates
            if _SOURCE_PRIORITY[candidate.source] == highest_priority
        )
        # 最高优先级只有一个候选值，直接选择
        selected = highest_candidates[0] if len(highest_candidates) == 1 else None
        # 有多个最高优先级候选值，保留所有
        if selected is None:
            unresolved_fields.append(field)
        else:
            selected_entities[field] = selected
        # 记录冲突 存在多个不同值时 (同一优先级，不同值)
        if len(distinct_candidates) > 1:
            conflicts.append(
                EntityConflict(
                    field=field,
                    selected=selected,
                    candidates=distinct_candidates,
                    resolved_by_priority=selected is not None,
                )
            )
    # 最终返回合并结果
    return EntityMergeResult(
        entities=selected_entities,
        conflicts=tuple(conflicts),
        unresolved_fields=tuple(unresolved_fields),
    )
