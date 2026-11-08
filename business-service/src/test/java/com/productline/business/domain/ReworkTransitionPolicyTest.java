package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.assertj.core.api.Assertions.assertThatIllegalStateException;
import static org.assertj.core.api.Assertions.assertThatNullPointerException;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import com.productline.business.domain.model.ReworkArtifact;
import com.productline.business.domain.model.ReworkInspection;
import com.productline.business.domain.model.ReworkInspectionItem;
import com.productline.business.domain.model.ReworkProcessingEvidence;
import com.productline.business.domain.model.ReworkProcessingSnapshot;
import com.productline.business.domain.model.ReworkRound;
import com.productline.business.domain.model.ReworkTask;
import com.productline.business.domain.validation.ReworkTransitionPolicy;
import com.productline.business.domain.validation.ReworkTransitionPolicy.Action;
import com.productline.business.domain.validation.ReworkTransitionPolicy.Transition;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;

class ReworkTransitionPolicyTest {

    private static final Set<String> LEGAL_SOURCE_STATES = Set.of(
            "START:PENDING:OPEN", "BLOCK:RUNNING:PROCESSING", "FAIL:RUNNING:PROCESSING",
            "RESUME:BLOCKED:PROCESSING", "RESUME:FAILED:PROCESSING",
            "COMPLETE:RUNNING:PROCESSING", "REVIEW:COMPLETED:RESOLVED");

    private final ReworkTransitionPolicy policy = new ReworkTransitionPolicy();

    @ParameterizedTest
    @CsvSource({
            "START,PENDING,OPEN,APPROVED,RUNNING,PROCESSING",
            "BLOCK,RUNNING,PROCESSING,APPROVED,BLOCKED,PROCESSING",
            "FAIL,RUNNING,PROCESSING,APPROVED,FAILED,PROCESSING",
            "RESUME,BLOCKED,PROCESSING,APPROVED,RUNNING,PROCESSING",
            "RESUME,FAILED,PROCESSING,APPROVED,RUNNING,PROCESSING",
            "COMPLETE,RUNNING,PROCESSING,APPROVED,COMPLETED,RESOLVED",
            "REVIEW,COMPLETED,RESOLVED,APPROVED,COMPLETED,CLOSED",
            "REVIEW,COMPLETED,RESOLVED,REJECTED,COMPLETED,OPEN",
            "REVIEW,COMPLETED,RESOLVED,REWORK_REQUIRED,COMPLETED,OPEN"
    })
    void proposesOnlyTheSpecifiedChangesWithoutMutatingJavaFacts(
            Action action, ProductionTaskStatus beforeRework, QualityIssueStatus beforeIssue,
            ReviewStatus conclusion, ProductionTaskStatus afterRework, QualityIssueStatus afterIssue) {
        ReworkTask rework = rework(beforeRework, beforeIssue, ProductionTaskStatus.COMPLETED);
        ReworkRound round = ReworkRound.from(rework, 1);

        Transition transition = execute(action, rework, round, conclusion);

        assertThat(transition.getRound()).isEqualTo(round);
        assertThat(transition.getAction()).isEqualTo(action);
        assertThat(transition.getBefore().reworkStatus()).isEqualTo(beforeRework);
        assertThat(transition.getBefore().issueStatus()).isEqualTo(beforeIssue);
        assertThat(transition.getAfter().reworkStatus()).isEqualTo(afterRework);
        assertThat(transition.getAfter().issueStatus()).isEqualTo(afterIssue);
        assertThat(transition.getReason().isPresent())
                .isEqualTo(action == Action.BLOCK || action == Action.FAIL || action == Action.RESUME || action == Action.REVIEW);
        assertThat(transition.getInspection().isPresent())
                .isEqualTo(action == Action.COMPLETE || action == Action.REVIEW);
        assertThat(transition.getReviewConclusion()).isEqualTo(
                action == Action.REVIEW ? java.util.Optional.of(conclusion) : java.util.Optional.empty());
        assertUnchanged(rework, beforeRework, beforeIssue);
    }

    @ParameterizedTest
    @MethodSource("illegalStates")
    void rejectsAllUnspecifiedStatePairs(Action action, ProductionTaskStatus reworkStatus, QualityIssueStatus issueStatus) {
        ReworkTask rework = rework(reworkStatus, issueStatus, ProductionTaskStatus.COMPLETED);

        assertThatIllegalStateException()
                .isThrownBy(() -> execute(action, rework, ReworkRound.from(rework, 1), ReviewStatus.APPROVED));
        assertUnchanged(rework, reworkStatus, issueStatus);
    }

    @ParameterizedTest
    @MethodSource("unfinishedProduction")
    void rejectsEveryOperationUntilTheOriginalProductionTaskIsCompleted(
            Action action, ProductionTaskStatus productionStatus) {
        ReworkTask rework = validRework(action, productionStatus);

        assertThatIllegalStateException()
                .isThrownBy(() -> execute(action, rework, ReworkRound.from(rework, 1), ReviewStatus.APPROVED))
                .withMessage("rework transition requires a COMPLETED production task");
        assertThat(rework.getTask().getStatus()).isEqualTo(productionStatus);
        assertThat(rework.getTask().getVersion()).isZero();
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = " ")
    void requiresReasonsForInterruptionRecoveryAndReview(String reason) {
        ReworkTask running = validRework(Action.BLOCK, ProductionTaskStatus.COMPLETED);
        ReworkRound runningRound = ReworkRound.from(running, 1);
        ReworkTask blocked = validRework(Action.RESUME, ProductionTaskStatus.COMPLETED);
        ReworkTask completed = validRework(Action.REVIEW, ProductionTaskStatus.COMPLETED);
        ReworkRound completedRound = ReworkRound.from(completed, 1);
        ReworkProcessingSnapshot processing = processing(completed, "v2");
        ReworkInspection inspection = inspection(completed, completedRound, processing, ReworkInspectionResult.PASSED);
        assertThatIllegalArgumentException().isThrownBy(() -> policy.block(running, runningRound, reason));
        assertThatIllegalArgumentException().isThrownBy(() -> policy.fail(running, runningRound, reason));
        assertThatIllegalArgumentException().isThrownBy(() -> policy.resume(blocked, ReworkRound.from(blocked, 1), reason));
        assertThatIllegalArgumentException().isThrownBy(() -> policy.review(
                completed, completedRound, processing, inspection, ReviewStatus.APPROVED, reason));
    }

    @ParameterizedTest
    @EnumSource(value = Action.class, names = {"COMPLETE", "REVIEW"})
    void rejectsFailedOrMissingChecksAndMissingProcessingEvidence(Action action) {
        ReworkTask rework = validRework(action, ProductionTaskStatus.COMPLETED);
        ReworkRound round = ReworkRound.from(rework, 1);
        ReworkProcessingSnapshot processing = processing(rework, "v2");
        ReworkInspection failed = inspection(rework, round, processing, ReworkInspectionResult.FAILED);
        ReworkInspection passed = inspection(rework, round, processing, ReworkInspectionResult.PASSED);
        assertThatIllegalStateException()
                .isThrownBy(() -> checked(action, rework, round, processing, failed))
                .withMessage("completion and review require a passed inspection");
        assertThatNullPointerException().isThrownBy(() -> checked(action, rework, round, processing, null));
        assertThatNullPointerException().isThrownBy(() -> checked(action, rework, round, null, passed));
        assertThatIllegalStateException().isThrownBy(() -> checked(
                action, rework, round, ReworkProcessingSnapshot.unrecorded(rework), passed));
    }

    @ParameterizedTest
    @EnumSource(value = Action.class, names = {"COMPLETE", "REVIEW"})
    void rejectsChecksFromAnotherArtifactVersionOrRound(Action action) {
        ReworkTask rework = validRework(action, ProductionTaskStatus.COMPLETED);
        ReworkRound round = ReworkRound.from(rework, 1);
        ReworkProcessingSnapshot processing = processing(rework, "v2");
        ReworkInspection inspection = inspection(rework, round, processing, ReworkInspectionResult.PASSED);

        assertThatIllegalArgumentException()
                .isThrownBy(() -> checked(action, rework, round, processing(rework, "v3"), inspection));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> checked(action, rework, ReworkRound.from(rework, 2), processing, inspection));
    }

    @ParameterizedTest
    @EnumSource(Action.class)
    void rejectsCrossResourceRounds(Action action) {
        ReworkTask rework = validRework(action, ProductionTaskStatus.COMPLETED);
        ReworkRound wrong = new ReworkRound("REWORK-OTHER", "TASK-A", "ISSUE-A", 1);
        assertThatIllegalArgumentException().isThrownBy(() -> withoutEvidence(action, rework, wrong));
    }

    @ParameterizedTest
    @EnumSource(Action.class)
    void rejectsReworkWithoutATaskOrSourceIssue(Action action) {
        ReworkTask withoutTask = new ReworkTask("REWORK-A", ProductionTaskStatus.PENDING, "待处理");
        ReworkRound round = new ReworkRound("REWORK-A", "TASK-A", "ISSUE-A", 1);
        ReworkTask withoutIssue = new ReworkTask("REWORK-A", ProductionTaskStatus.PENDING, "待处理");
        new ProductionTask("TASK-A", ProductionTaskStatus.COMPLETED).addReworkTask(withoutIssue);
        assertThatIllegalStateException().isThrownBy(() -> withoutEvidence(action, withoutTask, round));
        assertThatIllegalStateException().isThrownBy(() -> withoutEvidence(action, withoutIssue, round));
    }

    @Test
    void refusesPendingReviewConclusions() {
        ReworkTask rework = validRework(Action.REVIEW, ProductionTaskStatus.COMPLETED);
        assertThatIllegalArgumentException()
                .isThrownBy(() -> execute(Action.REVIEW, rework, ReworkRound.from(rework, 1), ReviewStatus.PENDING))
                .withMessage("review conclusion must be final");
    }

    @Test
    void refusesNullReviewConclusionsAndMissingTransitionContext() {
        ReworkTask rework = validRework(Action.REVIEW, ProductionTaskStatus.COMPLETED);
        assertThatNullPointerException()
                .isThrownBy(() -> execute(Action.REVIEW, rework, ReworkRound.from(rework, 1), null));
        assertThatNullPointerException()
                .isThrownBy(() -> policy.start(null, new ReworkRound("REWORK-A", "TASK-A", "ISSUE-A", 1)));
        assertThatNullPointerException()
                .isThrownBy(() -> policy.start(validRework(Action.START, ProductionTaskStatus.COMPLETED), null));
    }

    @Test
    void retainsFailureAndRecoveryReasonsOnSeparateImmutableProposals() {
        ReworkTask running = validRework(Action.FAIL, ProductionTaskStatus.COMPLETED);
        Transition failed = policy.fail(running, ReworkRound.from(running, 1), "处理程序异常");
        ReworkTask restored = rework(failed.getAfter().reworkStatus(), failed.getAfter().issueStatus(), ProductionTaskStatus.COMPLETED);
        Transition resumed = policy.resume(restored, ReworkRound.from(restored, 1), "修复参数后继续人工处理");

        assertThat(failed.getReason()).contains("处理程序异常");
        assertThat(resumed.getReason()).contains("修复参数后继续人工处理");
        assertThat(failed.getAfter().reworkStatus()).isEqualTo(ProductionTaskStatus.FAILED);
        assertThat(resumed.getAfter().reworkStatus()).isEqualTo(ProductionTaskStatus.RUNNING);
    }

    private Transition execute(Action action, ReworkTask rework, ReworkRound round, ReviewStatus conclusion) {
        return switch (action) {
            case START -> policy.start(rework, round);
            case BLOCK -> policy.block(rework, round, "阻塞原因");
            case FAIL -> policy.fail(rework, round, "失败原因");
            case RESUME -> policy.resume(rework, round, "恢复说明");
            case COMPLETE, REVIEW -> {
                ReworkProcessingSnapshot processing = processing(rework, "v2");
                ReworkInspection inspection = inspection(rework, round, processing, ReworkInspectionResult.PASSED);
                yield action == Action.COMPLETE
                        ? policy.complete(rework, round, processing, inspection)
                        : policy.review(rework, round, processing, inspection, conclusion, "复核说明");
            }
        };
    }

    private Transition withoutEvidence(Action action, ReworkTask rework, ReworkRound round) {
        return switch (action) {
            case COMPLETE -> policy.complete(rework, round, null, null);
            case REVIEW -> policy.review(rework, round, null, null, ReviewStatus.APPROVED, "复核说明");
            default -> execute(action, rework, round, ReviewStatus.APPROVED);
        };
    }

    private Transition checked(Action action, ReworkTask rework, ReworkRound round,
            ReworkProcessingSnapshot processing, ReworkInspection inspection) {
        return action == Action.COMPLETE
                ? policy.complete(rework, round, processing, inspection)
                : policy.review(rework, round, processing, inspection, ReviewStatus.APPROVED, "复核说明");
    }

    private void assertUnchanged(ReworkTask rework, ProductionTaskStatus reworkStatus, QualityIssueStatus issueStatus) {
        assertThat(rework.getStatus()).isEqualTo(reworkStatus);
        assertThat(rework.getSourceIssue().getStatus()).isEqualTo(issueStatus);
        assertThat(rework.getTask().getStatus()).isEqualTo(ProductionTaskStatus.COMPLETED);
        assertThat(rework.getTask().getVersion()).isZero();
        assertThat(rework.getSourceIssue().getReviewRecords()).isEmpty();
    }

    private ReworkProcessingSnapshot processing(ReworkTask rework, String version) {
        return ReworkProcessingSnapshot.recorded(rework, new ReworkProcessingEvidence(
                new ReworkArtifact("ARTIFACT-A", version), "处理说明", List.of("REPORT-A")));
    }

    private ReworkInspection inspection(ReworkTask rework, ReworkRound round,
            ReworkProcessingSnapshot processing, ReworkInspectionResult result) {
        return ReworkInspection.recorded("CHECK-A", round, rework, processing, "REVIEWER-TEST",
                Instant.parse("2026-11-08T09:00:00Z"),
                List.of(new ReworkInspectionItem("坐标系", result, "人工检查说明", List.of("CHECK-REPORT-A"))));
    }

    private ReworkTask validRework(Action action, ProductionTaskStatus productionStatus) {
        return switch (action) {
            case START -> rework(ProductionTaskStatus.PENDING, QualityIssueStatus.OPEN, productionStatus);
            case BLOCK, FAIL, COMPLETE -> rework(ProductionTaskStatus.RUNNING, QualityIssueStatus.PROCESSING, productionStatus);
            case RESUME -> rework(ProductionTaskStatus.BLOCKED, QualityIssueStatus.PROCESSING, productionStatus);
            case REVIEW -> rework(ProductionTaskStatus.COMPLETED, QualityIssueStatus.RESOLVED, productionStatus);
        };
    }

    private ReworkTask rework(ProductionTaskStatus reworkStatus, QualityIssueStatus issueStatus, ProductionTaskStatus productionStatus) {
        ProductionTask task = new ProductionTask("TASK-A", productionStatus);
        QualityIssue issue = new QualityIssue("ISSUE-A", "COORDINATE_SYSTEM", issueStatus, "坐标系问题");
        task.addQualityIssue(issue);
        ReworkTask rework = new ReworkTask("REWORK-A", reworkStatus, "修正坐标系");
        rework.setSourceIssue(issue);
        task.addReworkTask(rework);
        return rework;
    }

    private static Stream<Arguments> illegalStates() {
        return Arrays.stream(Action.values()).flatMap(action -> Arrays.stream(ProductionTaskStatus.values())
                .flatMap(rework -> Arrays.stream(QualityIssueStatus.values())
                        .filter(issue -> !LEGAL_SOURCE_STATES.contains(action + ":" + rework + ":" + issue))
                        .map(issue -> Arguments.of(action, rework, issue))));
    }

    private static Stream<Arguments> unfinishedProduction() {
        return Arrays.stream(Action.values()).flatMap(action -> Arrays.stream(ProductionTaskStatus.values())
                .filter(status -> status != ProductionTaskStatus.COMPLETED)
                .map(status -> Arguments.of(action, status)));
    }
}
