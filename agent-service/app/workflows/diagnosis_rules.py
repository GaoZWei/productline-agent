"""基于已加载 Java 事实计算订单阻塞阶段的确定性规则。"""

from app.schemas.tools import QualityIssue, ReviewRecord
from app.schemas.workflow import BlockingStage, OrderDiagnosisState, RuleDecision

_PRODUCTION_FAILED = frozenset({"FAILED", "BLOCKED"})
_PRODUCTION_ACTIVE = frozenset({"PENDING", "RUNNING"})
_QUALITY_UNRESOLVED = frozenset({"OPEN", "PROCESSING"})
_DELIVERY_BLOCKED = frozenset({"NOT_READY", "FAILED", "BLOCKED"})


def evaluate_diagnosis_rules(state: OrderDiagnosisState) -> RuleDecision:
    """按最早业务阶段优先原则返回稳定决策, 不生成根因或建议文案。"""
    # 第一步：数据够不够？
    if not _has_complete_facts(state):
        stage = BlockingStage.INSUFFICIENT_INFORMATION
    else: 
        # 第二步：数据够的情况下卡在哪？
        stage = _evaluate_complete_facts(state)
    return RuleDecision(order_id=state["order_id"], blocking_stage=stage)

# 完整性检查：防止缺数据误报正常
def _has_complete_facts(state: OrderDiagnosisState) -> bool:
    """确认规则依赖的每组 Tool 事实都已加载且归属一致。"""

    order = state["order"]
    tasks = state["tasks"]
    delivery = state["delivery"]
    # 检查关键对象是否存在
    if state["errors"] or order is None or not tasks or delivery is None:
        return False
    # 检查父订单ID是否一致
    if order.order_id != state["order_id"] or delivery.order_id != state["order_id"]:
        return False
    if not delivery.records or any(
        record.order_id != state["order_id"] for record in delivery.records
    ):
        return False
    # 检查任务集合是否完整
    task_ids = {task.task_id for task in tasks}
    if any(task.order_id != state["order_id"] for task in tasks):
        return False
    if set(state["progress"]) != task_ids:
        return False
    if set(state["quality_issues"]) != task_ids:
        return False
    if set(state["reviews"]) != task_ids:
        return False
    # 检查更细的父子归属是否一致
    for task_id in task_ids:
        progress = state["progress"][task_id]
        issues = state["quality_issues"][task_id]
        review_result = state["reviews"][task_id]
        if progress.task_id != task_id or not progress.steps:
            return False
        if any(step.task_id != task_id for step in progress.steps):
            return False
        if any(issue.task_id != task_id for issue in issues):
            return False
        if review_result is None or review_result.task_id != task_id:
            return False
        issue_ids = {issue.issue_id for issue in issues}
        if any(review.issue_id not in issue_ids for review in review_result.reviews):
            return False
    return True

# 正式判断阶段
def _evaluate_complete_facts(state: OrderDiagnosisState) -> BlockingStage:
    """按生产、质检、复核、交付顺序返回最早未满足的阶段。"""
    # 收集生产状态
    task_statuses = {task.status for task in state["tasks"]}
    step_statuses = {
        step.status
        for progress in state["progress"].values()
        for step in progress.steps
    }
    # 生产失败优先处理
    if task_statuses & _PRODUCTION_FAILED or step_statuses & _PRODUCTION_FAILED:
        return BlockingStage.PRODUCTION_BLOCKED
    # 正在生产优先处理
    if task_statuses & _PRODUCTION_ACTIVE or step_statuses & _PRODUCTION_ACTIVE:
        return BlockingStage.PRODUCTION
    # 质检规则
    issues = [
        issue
        for task_issues in state["quality_issues"].values()
        for issue in task_issues
    ]
    if any(issue.status in _QUALITY_UNRESOLVED for issue in issues):
        return BlockingStage.QUALITY_REVIEW
    # 复核规则
    reviews = [
        review
        for result in state["reviews"].values()
        if result is not None
        for review in result.reviews
    ]
    if _requires_review(issues, reviews):
        return BlockingStage.REVIEW
    # 交付和无阻塞规则
    delivery = state["delivery"]
    if delivery is None:
        return BlockingStage.INSUFFICIENT_INFORMATION
    if any(record.status in _DELIVERY_BLOCKED for record in delivery.records):
        return BlockingStage.DELIVERY
    return BlockingStage.NONE

# 复核规则
def _requires_review(
    issues: list[QualityIssue],
    reviews: list[ReviewRecord],
) -> bool:
    """识别未通过的复核, 以及已解决但尚无通过复核的问题。"""
    # 存在未通过复核
    if any(review.status != "APPROVED" for review in reviews):
        return True
    # 问题已解决，但还没有通过复核
    approved_issue_ids = {
        review.issue_id for review in reviews if review.status == "APPROVED"
    }
    return any(
        issue.status == "RESOLVED" and issue.issue_id not in approved_issue_ids
        for issue in issues
    )
