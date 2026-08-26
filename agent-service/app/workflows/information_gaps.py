"""按已加载业务状态计算动态订单诊断仍缺少的确定性信息。"""

from __future__ import annotations

from app.schemas.specification import SpecificationQaResult
from app.schemas.workflow import InformationGap, OrderDiagnosisState

_PRODUCTION_ORDER_STATUSES = frozenset({"PRODUCING"})
_QUALITY_ORDER_STATUSES = frozenset({"QUALITY_CHECKING"})
_REVIEW_ORDER_STATUSES = frozenset({"REVIEWING"})


class InformationGapDetector:
    """根据订单阶段和已加载事实返回稳定、可执行的信息缺口。"""

    def detect(
        self,
        # 已经通过Tool Schema校验的订单、任务、进度、质检、复核和交付事实
        state: OrderDiagnosisState,
        *,
        specification_result: SpecificationQaResult | None = None,  # 独立保存的规范问答结果
    ) -> list[InformationGap]:
        """先检查基础事实, 再按生产、质检、复核和规范场景追加要求。"""
        # 不仅要求order存在, 还要求Tool返回的订单ID与当前诊断订单一致
        gaps: list[InformationGap] = []
        order = state["order"]
        order_is_valid = order is not None and order.order_id == state["order_id"]
        if not order_is_valid:
            gaps.append(
                InformationGap(
                    code="ORDER_REQUIRED",
                    description="需要读取与目标订单一致的订单状态。",
                )
            )

        # 检查三件事  1. 至少有一个任务 2. 任务ID唯一 3. 任务属于当前订单
        tasks = state["tasks"]
        task_ids = [task.task_id for task in tasks]
        tasks_are_valid = (
            bool(tasks)
            and len(task_ids) == len(set(task_ids))
            and all(task.order_id == state["order_id"] for task in tasks)
        )
        if not tasks_are_valid:
            gaps.append(
                InformationGap(
                    code="RELATED_TASKS_REQUIRED",
                    description="需要读取至少一个属于目标订单的关联任务及其关键状态。",
                )
            )
        # 交付状态检查
        if not self._has_valid_delivery(state):
            gaps.append(
                InformationGap(
                    code="DELIVERY_STATUS_REQUIRED",
                    description="需要读取与目标订单一致且包含交付记录的交付状态。",
                )
            )
        # 基础事实不完整时立即返回信息缺口
        if not order_is_valid or not tasks_are_valid:
            return gaps
        assert order is not None
        # 生产场景规则
        # 首先找出没有完成的任务
        production_task_ids = [task.task_id for task in tasks if task.status != "COMPLETED"]
        # 如果订单状态仍是PRODUCING, 但任务都显示COMPLETED, 也会要求查询进度
        if order.status in _PRODUCTION_ORDER_STATUSES and not production_task_ids:
            production_task_ids = task_ids
        missing_progress = [
            task_id
            for task_id in production_task_ids
            if not self._has_valid_progress(state, task_id)
        ]
        if missing_progress:
            gaps.append(
                InformationGap(
                    code="PRODUCTION_PROGRESS_REQUIRED",
                    description=self._task_gap_description(
                        "需要读取生产场景任务的有效进度",
                        missing_progress,
                    ),
                )
            )
        # 质检场景规则
        quality_task_ids = task_ids if order.status in _QUALITY_ORDER_STATUSES else []
        missing_quality = [
            task_id
            for task_id in quality_task_ids
            if not self._has_valid_quality_issues(state, task_id)
        ]
        if missing_quality:
            gaps.append(
                InformationGap(
                    code="QUALITY_ISSUES_REQUIRED",
                    description=self._task_gap_description(
                        "需要读取质检场景任务的质检问题",
                        missing_quality,
                    ),
                )
            )
        # 复核场景规则
        issue_task_ids = [
            task_id
            for task_id in task_ids
            if self._has_valid_quality_issues(state, task_id) and state["quality_issues"][task_id]
        ]
        review_task_ids = list(
            # dict.fromkeys会去重, 同时保留原来的任务顺序
            dict.fromkeys(
                [
                    *(task_ids if order.status in _REVIEW_ORDER_STATUSES else []),
                    *issue_task_ids,
                ]
            )
        )
        missing_reviews = [
            task_id for task_id in review_task_ids if not self._has_valid_review(state, task_id)
        ]
        if missing_reviews:
            gaps.append(
                InformationGap(
                    code="REVIEW_RESULT_REQUIRED",
                    description=self._task_gap_description(
                        "需要读取复核场景任务的复核结果",
                        missing_reviews,
                    ),
                )
            )
        # 规范检索缺口规则
        requires_specification = any(
            issue.issue_type == "COORDINATE_SYSTEM"  #  当前规则只在发现坐标系问题时要求规范检索
            for task_id in issue_task_ids
            for issue in state["quality_issues"][task_id]
        )
        # 如果还没有执行规范问答, 要求规范检索结果
        if requires_specification and specification_result is None:
            gaps.append(
                InformationGap(
                    code="SPECIFICATION_RESULT_REQUIRED",
                    description="坐标系问题需要一次带显式日期和权限范围的规范检索结果。",
                )
            )
        return gaps

    # 生产进度怎样才算有效进度
    @staticmethod
    def _has_valid_progress(state: OrderDiagnosisState, task_id: str) -> bool:
        progress = state["progress"].get(task_id)
        return (
            progress is not None  # 已经查询到该任务的进度
            and progress.task_id == task_id  # ProgressResult.task_id正确
            and bool(progress.steps)  #  至少有一个生产步骤
            # 每个生产步骤都属于当前任务
            and all(step.task_id == task_id for step in progress.steps)
        )

    @staticmethod
    def _has_valid_quality_issues(state: OrderDiagnosisState, task_id: str) -> bool:
        if task_id not in state["quality_issues"]:
            return False
        return all(issue.task_id == task_id for issue in state["quality_issues"][task_id])

    # 复核结果有效性判断
    @staticmethod
    def _has_valid_review(state: OrderDiagnosisState, task_id: str) -> bool:
        review = state["reviews"].get(task_id)
        if review is None or review.task_id != task_id:
            return False
        if task_id not in state["quality_issues"]:
            return True
        issue_ids = {issue.issue_id for issue in state["quality_issues"][task_id]}
        return all(record.issue_id in issue_ids for record in review.reviews)

    @staticmethod
    def _has_valid_delivery(state: OrderDiagnosisState) -> bool:
        delivery = state["delivery"]
        return (
            delivery is not None  #  查询过交付状态
            and delivery.order_id == state["order_id"]  # 交付结果属于当前订单
            and bool(delivery.records)  # 至少有一条交付记录
            # 每条交付记录都属于当前订单
            and all(record.order_id == state["order_id"] for record in delivery.records)
        )

    @staticmethod
    def _task_gap_description(prefix: str, task_ids: list[str]) -> str:
        return f"{prefix}: {', '.join(sorted(task_ids))}。"
