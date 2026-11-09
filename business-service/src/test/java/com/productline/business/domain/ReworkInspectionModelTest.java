package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.assertj.core.api.Assertions.assertThatIllegalStateException;
import static org.assertj.core.api.Assertions.assertThatNullPointerException;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
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
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;

class ReworkInspectionModelTest {

    private static final Instant INSPECTED_AT = Instant.parse("2026-11-08T09:00:00Z");

    @Test
    void bindsAHumanInspectionToItsRoundArtifactAndProcessingEvidenceWithoutChangingState() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkProcessingSnapshot processing = processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A");
        ReworkRound round = ReworkRound.from(rework, 2);

        ReworkInspection inspection = inspection("CHECK-A", round, rework, processing,
                List.of(item("坐标系", ReworkInspectionResult.PASSED)));

        assertThat(inspection.getInspectionId()).isEqualTo("CHECK-A");
        assertThat(inspection.getRound()).isEqualTo(round);
        assertThat(inspection.getProcessingEvidence()).isEqualTo(processing.getEvidence().orElseThrow());
        assertThat(inspection.getInspectorId()).isEqualTo("REVIEWER-TEST");
        assertThat(inspection.getInspectedAt()).isEqualTo(INSPECTED_AT);
        assertThat(inspection.getResult()).isEqualTo(ReworkInspectionResult.PASSED);
        assertThat(rework.getStatus()).isEqualTo(ProductionTaskStatus.PENDING);
        assertThat(rework.getTask().getStatus()).isEqualTo(ProductionTaskStatus.COMPLETED);
        assertThat(rework.getTask().getVersion()).isZero();
        assertThat(rework.getSourceIssue().getStatus()).isEqualTo(QualityIssueStatus.OPEN);
        assertThat(rework.getSourceIssue().getReviewRecords()).isEmpty();
    }

    @Test
    void preservesSeparateChecksOfTheSameRoundAndSummarizesAnyFailedItemAsFailed() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkRound round = ReworkRound.from(rework, 1);
        ReworkProcessingSnapshot processing = processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A");
        ReworkInspection failed = inspection("CHECK-A", round, rework, processing, List.of(
                item("坐标系", ReworkInspectionResult.PASSED),
                item("成果范围", ReworkInspectionResult.FAILED)));
        ReworkInspection passed = ReworkInspection.recorded("CHECK-B", round, rework, processing,
                "REVIEWER-OTHER", INSPECTED_AT.plusSeconds(60),
                List.of(item("坐标系", ReworkInspectionResult.PASSED)));

        assertThat(failed.getResult()).isEqualTo(ReworkInspectionResult.FAILED);
        assertThat(failed.getItems()).hasSize(2);
        assertThat(passed.getResult()).isEqualTo(ReworkInspectionResult.PASSED);
        assertThat(passed.getInspectionId()).isNotEqualTo(failed.getInspectionId());
        assertThat(passed.getInspectedAt()).isAfter(failed.getInspectedAt());
        assertThat(failed.getItems().get(1).comment()).isEqualTo("人工检查说明");
    }

    @ParameterizedTest
    @ValueSource(ints = {0, -1, Integer.MIN_VALUE})
    void rejectsNonPositiveRoundNumbers(int roundNumber) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> ReworkRound.from(rework("REWORK-A", "TASK-A", "ISSUE-A"), roundNumber))
                .withMessage("roundNumber must be greater than zero");
    }

    @ParameterizedTest
    @ValueSource(longs = {2147483648L, 9007199254740991L})
    void preservesSafeRoundNumbersBeyondIntRange(long roundNumber) {
        ReworkRound round = ReworkRound.from(rework("REWORK-A", "TASK-A", "ISSUE-A"), roundNumber);
        assertThat(round.roundNumber()).isEqualTo(roundNumber);
    }

    @ParameterizedTest
    @ValueSource(longs = {9007199254740992L, Long.MAX_VALUE})
    void rejectsRoundNumbersBeyondSafeRange(long roundNumber) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> ReworkRound.from(rework("REWORK-A", "TASK-A", "ISSUE-A"), roundNumber))
                .withMessage("roundNumber must be a positive safe integer");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = " ")
    void rejectsMissingRoundResourceIdentities(String value) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkRound(value, "TASK-A", "ISSUE-A", 1));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkRound("REWORK-A", value, "ISSUE-A", 1));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkRound("REWORK-A", "TASK-A", value, 1));
    }

    @Test
    void doesNotInventARoundForLegacyReworkWithoutASourceIssue() {
        ProductionTask task = new ProductionTask("TASK-LEGACY", ProductionTaskStatus.COMPLETED);
        ReworkTask rework = new ReworkTask("REWORK-LEGACY", ProductionTaskStatus.COMPLETED, "历史记录");
        task.addReworkTask(rework);

        assertThat(ReworkProcessingSnapshot.unrecorded(rework).getEvidence()).isEmpty();
        assertThatIllegalStateException()
                .isThrownBy(() -> ReworkRound.from(rework, 1))
                .withMessage("rework round requires a source issue");
        assertThat(rework.getSourceIssue()).isNull();
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = " ")
    void rejectsMissingInspectionIdentityOrInspector(String value) {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkRound round = ReworkRound.from(rework, 1);
        ReworkProcessingSnapshot processing = processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A");
        assertThatIllegalArgumentException()
                .isThrownBy(() -> inspection(value, round, rework, processing,
                        List.of(item("坐标系", ReworkInspectionResult.PASSED))))
                .withMessage("inspectionId must not be blank");
        assertThatIllegalArgumentException()
                .isThrownBy(() -> ReworkInspection.recorded("CHECK-A", round, rework, processing,
                        value, INSPECTED_AT, List.of(item("坐标系", ReworkInspectionResult.PASSED))))
                .withMessage("inspectorId must not be blank");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = " ")
    void rejectsIncompleteCheckItems(String value) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkInspectionItem(value, ReworkInspectionResult.PASSED,
                        "人工检查说明", List.of("CHECK-REPORT-A")));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkInspectionItem("坐标系", ReworkInspectionResult.FAILED,
                        value, List.of("CHECK-REPORT-A")));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkInspectionItem("坐标系", ReworkInspectionResult.PASSED,
                        "人工检查说明", Arrays.asList("CHECK-REPORT-A", value)));
    }

    @Test
    void rejectsAbsentCheckResultsAndEvidence() {
        assertThatNullPointerException()
                .isThrownBy(() -> new ReworkInspectionItem("坐标系", null, "人工检查说明", List.of("REPORT-A")))
                .withMessage("result");
        assertThatNullPointerException()
                .isThrownBy(() -> new ReworkInspectionItem("坐标系", ReworkInspectionResult.PASSED,
                        "人工检查说明", null))
                .withMessage("evidenceReferences");
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkInspectionItem("坐标系", ReworkInspectionResult.PASSED,
                        "人工检查说明", List.of()))
                .withMessage("evidenceReferences must not be empty");
    }

    @Test
    void rejectsEmptyCheckListsRatherThanTreatingThemAsPassing() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        assertThatIllegalArgumentException()
                .isThrownBy(() -> inspection("CHECK-A", ReworkRound.from(rework, 1), rework,
                        processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A"), List.of()))
                .withMessage("items must not be empty");
    }

    @Test
    void rejectsMissingRoundProcessingTimeOrItems() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkRound round = ReworkRound.from(rework, 1);
        ReworkProcessingSnapshot processing = processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A");
        List<ReworkInspectionItem> items = List.of(item("坐标系", ReworkInspectionResult.PASSED));
        assertThatNullPointerException()
                .isThrownBy(() -> inspection("CHECK-A", null, rework, processing, items));
        assertThatNullPointerException()
                .isThrownBy(() -> inspection("CHECK-A", round, rework, null, items));
        assertThatNullPointerException()
                .isThrownBy(() -> ReworkInspection.recorded("CHECK-A", round, rework, processing,
                        "REVIEWER-TEST", null, items));
        assertThatNullPointerException()
                .isThrownBy(() -> inspection("CHECK-A", round, rework, processing, null));
        assertThatNullPointerException()
                .isThrownBy(() -> inspection("CHECK-A", round, rework, processing, Arrays.asList((ReworkInspectionItem) null)));
    }

    @Test
    void rejectsAnInspectionWithoutRecordedProcessingEvidence() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkRound round = ReworkRound.from(rework, 1);
        ReworkInspection inspection = inspection("CHECK-EXISTING", round, rework,
                processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A"),
                List.of(item("坐标系", ReworkInspectionResult.PASSED)));
        assertThatIllegalStateException()
                .isThrownBy(() -> inspection("CHECK-A", round, rework,
                        ReworkProcessingSnapshot.unrecorded(rework), List.of(item("坐标系", ReworkInspectionResult.PASSED))))
                .withMessage("inspection requires recorded processing evidence");
        assertThatIllegalStateException()
                .isThrownBy(() -> inspection.requireAppliesTo(round, rework, ReworkProcessingSnapshot.unrecorded(rework)))
                .withMessage("inspection requires recorded processing evidence");
    }

    @ParameterizedTest
    @CsvSource({"REWORK-B,TASK-A,ISSUE-A", "REWORK-A,TASK-B,ISSUE-A", "REWORK-A,TASK-A,ISSUE-B"})
    void rejectsCrossResourceRoundOrProcessingEvidence(String reworkId, String taskId, String issueId) {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkTask other = rework(reworkId, taskId, issueId);
        ReworkProcessingSnapshot processing = processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A");
        ReworkInspection existing = inspection("CHECK-EXISTING", ReworkRound.from(rework, 1), rework, processing,
                List.of(item("坐标系", ReworkInspectionResult.PASSED)));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> inspection("CHECK-A", ReworkRound.from(other, 1), rework, processing,
                        List.of(item("坐标系", ReworkInspectionResult.PASSED))));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> inspection("CHECK-A", ReworkRound.from(rework, 1), rework,
                        processing(other, "ARTIFACT-A", "v2", "处理说明", "REPORT-A"),
                        List.of(item("坐标系", ReworkInspectionResult.PASSED))));
        assertThatIllegalArgumentException()
                .isThrownBy(() -> existing.requireAppliesTo(ReworkRound.from(other, 1), other,
                        processing(other, "ARTIFACT-A", "v2", "处理说明", "REPORT-A")))
                .withMessage("inspection must belong to the same rework round");
    }

    @ParameterizedTest
    @CsvSource({"ARTIFACT-B,v2,处理说明,REPORT-A", "ARTIFACT-A,v3,处理说明,REPORT-A",
            "ARTIFACT-A,v2,新的处理说明,REPORT-A", "ARTIFACT-A,v2,处理说明,REPORT-B"})
    void rejectsReuseWhenTheArtifactOrProcessingMaterialsChange(
            String artifactId, String version, String comment, String reference) {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkRound round = ReworkRound.from(rework, 1);
        ReworkInspection inspection = inspection("CHECK-A", round, rework,
                processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A"),
                List.of(item("坐标系", ReworkInspectionResult.PASSED)));

        assertThatIllegalArgumentException()
                .isThrownBy(() -> inspection.requireAppliesTo(round, rework,
                        processing(rework, artifactId, version, comment, reference)))
                .withMessage("inspection does not apply to the current processing evidence");
    }

    @Test
    void rejectsReuseAcrossRoundsEvenForTheSameArtifact() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkProcessingSnapshot processing = processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A");
        ReworkInspection inspection = inspection("CHECK-A", ReworkRound.from(rework, 1), rework, processing,
                List.of(item("坐标系", ReworkInspectionResult.PASSED)));

        assertThatIllegalArgumentException()
                .isThrownBy(() -> inspection.requireAppliesTo(ReworkRound.from(rework, 2), rework, processing))
                .withMessage("inspection must belong to the same rework round");
    }

    @Test
    void acceptsReloadedEntitiesAndEquivalentImmutableMaterials() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkInspection inspection = inspection("CHECK-A", ReworkRound.from(rework, 1), rework,
                processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A"),
                List.of(item("坐标系", ReworkInspectionResult.PASSED)));
        ReworkTask reloaded = rework("REWORK-A", "TASK-A", "ISSUE-A");

        inspection.requireAppliesTo(ReworkRound.from(reloaded, 1), reloaded,
                processing(reloaded, "ARTIFACT-A", "v2", "处理说明", "REPORT-A"));
    }

    @Test
    void preservesImmutableItemsAndCheckEvidenceAfterCallersChangeTheirLists() {
        List<String> references = new ArrayList<>(List.of("CHECK-REPORT-A"));
        ReworkInspectionItem item = new ReworkInspectionItem("坐标系", ReworkInspectionResult.PASSED,
                "人工检查说明", references);
        List<ReworkInspectionItem> items = new ArrayList<>(List.of(item));
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkInspection inspection = inspection("CHECK-A", ReworkRound.from(rework, 1), rework,
                processing(rework, "ARTIFACT-A", "v2", "处理说明", "REPORT-A"), items);

        references.clear();
        items.clear();

        assertThat(inspection.getItems()).containsExactly(item);
        assertThat(item.evidenceReferences()).containsExactly("CHECK-REPORT-A");
        assertThat(inspection.getResult()).isEqualTo(ReworkInspectionResult.PASSED);
        assertThatThrownBy(() -> inspection.getItems().clear()).isInstanceOf(UnsupportedOperationException.class);
        assertThatThrownBy(() -> item.evidenceReferences().clear()).isInstanceOf(UnsupportedOperationException.class);
    }

    private ReworkInspection inspection(String id, ReworkRound round, ReworkTask rework,
            ReworkProcessingSnapshot processing, List<ReworkInspectionItem> items) {
        return ReworkInspection.recorded(id, round, rework, processing, "REVIEWER-TEST", INSPECTED_AT, items);
    }

    private ReworkInspectionItem item(String name, ReworkInspectionResult result) {
        return new ReworkInspectionItem(name, result, "人工检查说明", List.of("CHECK-REPORT-A"));
    }

    private ReworkProcessingSnapshot processing(ReworkTask rework, String artifactId, String version,
            String comment, String reference) {
        return ReworkProcessingSnapshot.recorded(rework,
                new ReworkProcessingEvidence(new ReworkArtifact(artifactId, version), comment, List.of(reference)));
    }

    private ReworkTask rework(String reworkId, String taskId, String issueId) {
        ProductionTask task = new ProductionTask(taskId, ProductionTaskStatus.COMPLETED);
        QualityIssue issue = new QualityIssue(issueId, "COORDINATE_SYSTEM", QualityIssueStatus.OPEN, "坐标系问题");
        task.addQualityIssue(issue);
        ReworkTask rework = new ReworkTask(reworkId, ProductionTaskStatus.PENDING, "修正坐标系");
        rework.setSourceIssue(issue);
        task.addReworkTask(rework);
        return rework;
    }
}
