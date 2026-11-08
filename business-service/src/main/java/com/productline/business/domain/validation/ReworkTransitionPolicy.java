package com.productline.business.domain.validation;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.model.ReworkInspection;
import com.productline.business.domain.model.ReworkProcessingSnapshot;
import com.productline.business.domain.model.ReworkRound;
import com.productline.business.domain.model.ReworkTask;
import java.util.Objects;
import java.util.Optional;

/**
 * 根据Java实体和已选择的当前检查计算受约束的状态变更提议，不修改实体或执行写入。
 * 后续应用须重新读取事实、选择有效检查并校验权限、确认、版本和幂等，再原子落库。
 */
public final class ReworkTransitionPolicy {

    public enum Action {
        START, BLOCK, FAIL, RESUME, COMPLETE, REVIEW
    }

    public record State(ProductionTaskStatus reworkStatus, QualityIssueStatus issueStatus) {
        public State {
            Objects.requireNonNull(reworkStatus, "reworkStatus");
            Objects.requireNonNull(issueStatus, "issueStatus");
        }
    }

    public Transition start(ReworkTask rework, ReworkRound round) {
        State before = requireContext(rework, round);
        requireState(before, Action.START);
        return new Transition(round, Action.START, before,
                new State(ProductionTaskStatus.RUNNING, QualityIssueStatus.PROCESSING), null, null, null);
    }

    public Transition block(ReworkTask rework, ReworkRound round, String reason) {
        return interrupt(rework, round, reason, Action.BLOCK, ProductionTaskStatus.BLOCKED);
    }

    public Transition fail(ReworkTask rework, ReworkRound round, String reason) {
        return interrupt(rework, round, reason, Action.FAIL, ProductionTaskStatus.FAILED);
    }

    private Transition interrupt(ReworkTask rework, ReworkRound round, String reason,
            Action action, ProductionTaskStatus target) {
        State before = requireContext(rework, round);
        requireState(before, action);
        requireText(reason, "reason");
        return new Transition(round, action, before,
                new State(target, QualityIssueStatus.PROCESSING), reason, null, null);
    }

    public Transition resume(ReworkTask rework, ReworkRound round, String reason) {
        State before = requireContext(rework, round);
        requireState(before, Action.RESUME);
        requireText(reason, "reason");
        return new Transition(round, Action.RESUME, before,
                new State(ProductionTaskStatus.RUNNING, QualityIssueStatus.PROCESSING), reason, null, null);
    }

    public Transition complete(ReworkTask rework, ReworkRound round,
            ReworkProcessingSnapshot processing, ReworkInspection inspection) {
        State before = requireContext(rework, round);
        requireState(before, Action.COMPLETE);
        requirePassedInspection(rework, round, processing, inspection);
        return new Transition(round, Action.COMPLETE, before,
                new State(ProductionTaskStatus.COMPLETED, QualityIssueStatus.RESOLVED), null, inspection, null);
    }

    public Transition review(ReworkTask rework, ReworkRound round,
            ReworkProcessingSnapshot processing, ReworkInspection inspection,
            ReviewStatus conclusion, String reviewComment) {
        State before = requireContext(rework, round);
        requireState(before, Action.REVIEW);
        Objects.requireNonNull(conclusion, "conclusion");
        if (conclusion == ReviewStatus.PENDING) {
            throw new IllegalArgumentException("review conclusion must be final");
        }
        requireText(reviewComment, "reviewComment");
        requirePassedInspection(rework, round, processing, inspection);
        QualityIssueStatus target = conclusion == ReviewStatus.APPROVED
                ? QualityIssueStatus.CLOSED : QualityIssueStatus.OPEN;
        // 退回保留本轮完成事实；下一轮创建和交付条件检查由后续应用独立处理。
        return new Transition(round, Action.REVIEW, before,
                new State(ProductionTaskStatus.COMPLETED, target), reviewComment, inspection, conclusion);
    }

    private State requireContext(ReworkTask rework, ReworkRound round) {
        Objects.requireNonNull(rework, "rework");
        Objects.requireNonNull(round, "round");
        if (rework.getTask() == null) {
            throw new IllegalStateException("rework transition requires a production task");
        }
        if (rework.getTask().getStatus() != ProductionTaskStatus.COMPLETED) {
            throw new IllegalStateException("rework transition requires a COMPLETED production task");
        }
        if (rework.getSourceIssue() == null) {
            throw new IllegalStateException("rework transition requires a source issue");
        }
        round.requireBelongsTo(rework);
        return new State(rework.getStatus(), rework.getSourceIssue().getStatus());
    }

    private void requireState(State before, Action action) {
        boolean allowed = switch (action) {
            case START -> before.reworkStatus() == ProductionTaskStatus.PENDING
                    && before.issueStatus() == QualityIssueStatus.OPEN;
            case BLOCK, FAIL, COMPLETE -> before.reworkStatus() == ProductionTaskStatus.RUNNING
                    && before.issueStatus() == QualityIssueStatus.PROCESSING;
            case RESUME -> (before.reworkStatus() == ProductionTaskStatus.BLOCKED
                    || before.reworkStatus() == ProductionTaskStatus.FAILED)
                    && before.issueStatus() == QualityIssueStatus.PROCESSING;
            case REVIEW -> before.reworkStatus() == ProductionTaskStatus.COMPLETED
                    && before.issueStatus() == QualityIssueStatus.RESOLVED;
        };
        if (!allowed) {
            throw new IllegalStateException("illegal rework state for " + action);
        }
    }

    private void requirePassedInspection(ReworkTask rework, ReworkRound round,
            ReworkProcessingSnapshot processing, ReworkInspection inspection) {
        Objects.requireNonNull(inspection, "inspection").requireAppliesTo(round, rework, processing);
        if (inspection.getResult() != ReworkInspectionResult.PASSED) {
            throw new IllegalStateException("completion and review require a passed inspection");
        }
    }

    private void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
    }

    /** 不可变的变更提议，携带操作、前后状态及原因/检查/复核材料，不是已执行或已授权的凭证。 */
    public static final class Transition {
        private final ReworkRound round;
        private final Action action;
        private final State before;
        private final State after;
        private final Optional<String> reason;
        private final Optional<ReworkInspection> inspection;
        private final Optional<ReviewStatus> reviewConclusion;

        private Transition(ReworkRound round, Action action, State before, State after,
                String reason, ReworkInspection inspection, ReviewStatus reviewConclusion) {
            this.round = round;
            this.action = action;
            this.before = before;
            this.after = after;
            this.reason = Optional.ofNullable(reason);
            this.inspection = Optional.ofNullable(inspection);
            this.reviewConclusion = Optional.ofNullable(reviewConclusion);
        }

        public ReworkRound getRound() {
            return round;
        }

        public Action getAction() {
            return action;
        }

        public State getBefore() {
            return before;
        }

        public State getAfter() {
            return after;
        }

        public Optional<String> getReason() {
            return reason;
        }

        public Optional<ReworkInspection> getInspection() {
            return inspection;
        }

        public Optional<ReviewStatus> getReviewConclusion() {
            return reviewConclusion;
        }
    }
}
