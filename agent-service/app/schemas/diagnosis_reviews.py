"""诊断专用复核视图，Java当前绑定与仅用于展示的旧历史分开保存。"""

from typing import Self

from pydantic import ValidationError, model_validator

from app.schemas.rework import EffectiveReworkReviews
from app.schemas.tools import QualityIssue, ReviewRecord, ReviewResult, TaskDetail


def project_java_reviews(snapshot: EffectiveReworkReviews) -> list[ReviewRecord]:
    """只投影Java已经选择的当前复核及未纳管记录，不在Python挑历史最新通过。"""

    records: list[ReviewRecord] = []
    for issue in snapshot.issues:
        if issue.round_number is None:
            records.extend(
                ReviewRecord.model_validate(row.model_dump()) for row in issue.legacy_reviews
            )
        elif issue.review is not None:
            records.append(
                ReviewRecord(
                    review_id=issue.review.review_id,
                    issue_id=issue.issue_id,
                    status=issue.review.status,
                    review_comment=issue.review.review_comment,
                )
            )
    return records


class DiagnosisReviewResult(ReviewResult):
    """兼容诊断的标量复核投影，原始M8材料和旧历史另有明确字段。"""

    effective_reviews: EffectiveReworkReviews
    history_reviews: list[ReviewRecord]

    @model_validator(mode="after")
    def validate_java_projection(self) -> Self:
        """禁止调用者用历史记录替换当前投影或混入其他任务/问题的历史。"""

        if self.task_id != self.effective_reviews.task_id:
            raise ValueError("effective reviews belong to a different task")
        if self.reviews != project_java_reviews(self.effective_reviews):
            raise ValueError("diagnosis reviews differ from Java current facts")
        issue_ids = {issue.issue_id for issue in self.effective_reviews.issues}
        if any(row.issue_id not in issue_ids for row in self.history_reviews):
            raise ValueError("historical review belongs to an unknown issue")
        return self


def review_snapshot_matches(
    task: TaskDetail, issues: list[QualityIssue] | None, review: ReviewResult
) -> bool:
    """新视图必须与本次任务版本及问题集合一致，旧离线/历史契约保持原规则。"""

    if not isinstance(review, DiagnosisReviewResult):
        return True
    try:
        review = DiagnosisReviewResult.model_validate(review.model_dump(mode="python"))
    except ValidationError:
        return False
    snapshot = review.effective_reviews
    if snapshot.task_id != task.task_id or snapshot.task_version != task.version:
        return False
    return (
        (not snapshot.issues)
        if issues is None
        else (
            len({issue.issue_id for issue in issues}) == len(issues)
            and {issue.issue_id for issue in snapshot.issues}
            == {issue.issue_id for issue in issues}
        )
    )
