package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.assertj.core.api.Assertions.assertThatIllegalStateException;
import static org.assertj.core.api.Assertions.assertThatNullPointerException;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import com.productline.business.domain.model.ReworkArtifact;
import com.productline.business.domain.model.ReworkProcessingEvidence;
import com.productline.business.domain.model.ReworkProcessingSnapshot;
import com.productline.business.domain.model.ReworkTask;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;

class ReworkProcessingModelTest {

    @Test
    void capturesEvidenceWithBusinessIdentityWithoutChangingBusinessState() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkProcessingEvidence evidence = evidence();

        ReworkProcessingSnapshot snapshot = ReworkProcessingSnapshot.recorded(rework, evidence);

        assertThat(snapshot.getReworkTaskId()).isEqualTo("REWORK-A");
        assertThat(snapshot.getTaskId()).isEqualTo("TASK-A");
        assertThat(snapshot.getSourceIssueId()).contains("ISSUE-A");
        assertThat(snapshot.getEvidence()).contains(evidence);
        assertThat(rework.getStatus()).isEqualTo(ProductionTaskStatus.PENDING);
        assertThat(rework.getTask().getStatus()).isEqualTo(ProductionTaskStatus.COMPLETED);
        assertThat(rework.getTask().getVersion()).isZero();
        assertThat(rework.getSourceIssue().getStatus()).isEqualTo(QualityIssueStatus.OPEN);
        assertThat(rework.getSourceIssue().getReviewRecords()).isEmpty();
    }

    @Test
    void representsMissingHistoricalEvidenceWithoutInventingAnArtifact() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");

        ReworkProcessingSnapshot snapshot = ReworkProcessingSnapshot.unrecorded(rework);

        assertThat(snapshot.getSourceIssueId()).contains("ISSUE-A");
        assertThat(snapshot.getEvidence()).isEmpty();
        snapshot.requireBelongsTo(rework);
    }

    @Test
    void preservesMissingSourceIssueOnLegacyReworkWithoutInventingAnIssue() {
        ReworkTask rework = rework("REWORK-LEGACY", "TASK-A", null);

        ReworkProcessingSnapshot snapshot = ReworkProcessingSnapshot.unrecorded(rework);

        assertThat(snapshot.getSourceIssueId()).isEmpty();
        assertThat(snapshot.getEvidence()).isEmpty();
        snapshot.requireBelongsTo(rework);
        assertThatIllegalStateException()
                .isThrownBy(() -> ReworkProcessingSnapshot.recorded(rework, evidence()))
                .withMessage("recorded evidence requires a source issue");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "\t", "\n"})
    void rejectsMissingArtifactIdentity(String artifactId) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkArtifact(artifactId, "v2"))
                .withMessage("artifactId must not be blank");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "\t", "\n"})
    void rejectsMissingArtifactVersion(String artifactVersion) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkArtifact("ARTIFACT-A", artifactVersion))
                .withMessage("artifactVersion must not be blank");
    }

    @Test
    void keepsArtifactVersionAsAnExactBusinessIdentity() {
        ReworkArtifact first = new ReworkArtifact("ARTIFACT-A", "release-2026.11.08");
        ReworkArtifact second = new ReworkArtifact("ARTIFACT-A", "release-2026.11.09");

        assertThat(first).isNotEqualTo(second);
        assertThat(first.artifactVersion()).isEqualTo("release-2026.11.08");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "\t", "\n"})
    void rejectsMissingProcessingComment(String comment) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkProcessingEvidence(artifact(), comment, List.of("REPORT-A")))
                .withMessage("processingComment must not be blank");
    }

    @Test
    void rejectsEvidenceWithoutAnArtifactOrReferenceCollection() {
        assertThatNullPointerException()
                .isThrownBy(() -> new ReworkProcessingEvidence(null, "已登记处理说明", List.of("REPORT-A")))
                .withMessage("artifact");
        assertThatNullPointerException()
                .isThrownBy(() -> new ReworkProcessingEvidence(artifact(), "已登记处理说明", null))
                .withMessage("evidenceReferences");
    }

    @Test
    void rejectsAnExplanationWithoutAnyEvidenceReference() {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkProcessingEvidence(artifact(), "已登记处理说明", List.of()))
                .withMessage("evidenceReferences must not be empty");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "\t", "\n"})
    void rejectsMissingIndividualEvidenceReferences(String reference) {
        assertThatIllegalArgumentException()
                .isThrownBy(() -> new ReworkProcessingEvidence(
                        artifact(), "已登记处理说明", Arrays.asList("REPORT-A", reference)))
                .withMessage("evidence reference must not be blank");
    }

    @Test
    void preventsEvidenceReferencesFromBeingChangedAfterCapture() {
        List<String> references = new ArrayList<>(List.of("REPORT-A", "LOG-A"));
        ReworkProcessingEvidence evidence = new ReworkProcessingEvidence(
                artifact(), "已登记处理说明", references);
        ReworkProcessingSnapshot snapshot = ReworkProcessingSnapshot.recorded(
                rework("REWORK-A", "TASK-A", "ISSUE-A"), evidence);

        references.clear();

        assertThat(snapshot.getEvidence().orElseThrow().evidenceReferences())
                .containsExactly("REPORT-A", "LOG-A");
        assertThatThrownBy(() -> evidence.evidenceReferences().add("REPORT-B"))
                .isInstanceOf(UnsupportedOperationException.class);
    }

    @Test
    void rejectsMissingReworkOrRecordedEvidence() {
        assertThatNullPointerException()
                .isThrownBy(() -> ReworkProcessingSnapshot.unrecorded(null))
                .withMessage("rework");
        assertThatNullPointerException()
                .isThrownBy(() -> ReworkProcessingSnapshot.recorded(
                        rework("REWORK-A", "TASK-A", "ISSUE-A"), null))
                .withMessage("evidence");
    }

    @Test
    void rejectsReworkWithoutAProductionTask() {
        ReworkTask rework = new ReworkTask("REWORK-A", ProductionTaskStatus.PENDING, "待处理");

        assertThatIllegalStateException()
                .isThrownBy(() -> ReworkProcessingSnapshot.unrecorded(rework))
                .withMessage("rework must belong to a production task");
    }

    @Test
    void rejectsSourceIssuesWhoseTaskHasNotBeenEstablished() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", null);
        rework.setSourceIssue(issue("ISSUE-A"));

        assertThatIllegalStateException()
                .isThrownBy(() -> ReworkProcessingSnapshot.recorded(rework, evidence()))
                .withMessage("source issue must belong to the rework production task");
    }

    @Test
    void rejectsAnIssueAttachedToAnotherTaskAfterReworkWasAssembled() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", null);
        QualityIssue issue = issue("ISSUE-A");
        rework.setSourceIssue(issue);
        new ProductionTask("TASK-B", ProductionTaskStatus.COMPLETED).addQualityIssue(issue);

        assertThatIllegalStateException()
                .isThrownBy(() -> ReworkProcessingSnapshot.recorded(rework, evidence()))
                .withMessage("source issue must belong to the rework production task");
    }

    @Test
    void acceptsTheSameBusinessIdentityReloadedAsAnotherEntityInstance() {
        ReworkProcessingSnapshot snapshot = ReworkProcessingSnapshot.recorded(
                rework("REWORK-A", "TASK-A", "ISSUE-A"), evidence());

        snapshot.requireBelongsTo(rework("REWORK-A", "TASK-A", "ISSUE-A"));
    }

    @Test
    void rejectsReuseForAnotherRework() {
        assertCannotReuseFor("REWORK-B", "TASK-A", "ISSUE-A");
    }

    @Test
    void rejectsReuseForAnotherProductionTask() {
        assertCannotReuseFor("REWORK-A", "TASK-B", "ISSUE-A");
    }

    @Test
    void rejectsReuseForAnotherSourceIssue() {
        assertCannotReuseFor("REWORK-A", "TASK-A", "ISSUE-B");
    }

    @Test
    void preservesCapturedIdentityWhenTheSourceAssociationChanges() {
        ReworkTask rework = rework("REWORK-A", "TASK-A", "ISSUE-A");
        ReworkProcessingSnapshot snapshot = ReworkProcessingSnapshot.recorded(rework, evidence());
        QualityIssue replacement = issue("ISSUE-B");
        rework.getTask().addQualityIssue(replacement);
        rework.setSourceIssue(replacement);

        assertThat(snapshot.getSourceIssueId()).contains("ISSUE-A");
        assertThatIllegalArgumentException()
                .isThrownBy(() -> snapshot.requireBelongsTo(rework))
                .withMessage("processing snapshot must belong to the same rework, task and source issue");
    }

    private void assertCannotReuseFor(String reworkId, String taskId, String issueId) {
        ReworkProcessingSnapshot snapshot = ReworkProcessingSnapshot.recorded(
                rework("REWORK-A", "TASK-A", "ISSUE-A"), evidence());

        assertThatIllegalArgumentException()
                .isThrownBy(() -> snapshot.requireBelongsTo(rework(reworkId, taskId, issueId)))
                .withMessage("processing snapshot must belong to the same rework, task and source issue");
    }

    private ReworkArtifact artifact() {
        return new ReworkArtifact("ARTIFACT-A", "v2");
    }

    private ReworkProcessingEvidence evidence() {
        return new ReworkProcessingEvidence(artifact(), "修正坐标系并登记处理报告", List.of("REPORT-A"));
    }

    private QualityIssue issue(String issueId) {
        return new QualityIssue(issueId, "COORDINATE_SYSTEM", QualityIssueStatus.OPEN, "坐标系问题");
    }

    private ReworkTask rework(String reworkId, String taskId, String issueId) {
        ProductionTask task = new ProductionTask(taskId, ProductionTaskStatus.COMPLETED);
        ReworkTask rework = new ReworkTask(reworkId, ProductionTaskStatus.PENDING, "修正坐标系");
        task.addReworkTask(rework);
        if (issueId != null) {
            QualityIssue issue = issue(issueId);
            task.addQualityIssue(issue);
            rework.setSourceIssue(issue);
        }
        return rework;
    }
}
