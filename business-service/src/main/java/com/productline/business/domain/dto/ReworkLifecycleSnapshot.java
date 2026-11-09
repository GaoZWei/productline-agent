package com.productline.business.domain.dto;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.model.ReworkArtifact;
import com.productline.business.domain.model.ReworkInspectionItem;
import java.time.Instant;
import java.util.List;

/** 同一数据库快照中的返工和当前材料；缺失历史保持null，不补造轮次或结论。 */
public record ReworkLifecycleSnapshot(
        ReworkTaskDto reworkTask, ProductionTaskStatus taskStatus, long taskVersion,
        QualityIssueStatus issueStatus, Long roundNumber, String previousReworkTaskId,
        Processing processing, Inspection inspection, Review review,
        boolean hasSuccessor, boolean hasOtherActiveRework) {

    public record Processing(long processingRevision, ReworkArtifact artifact,
            String processingComment, List<String> evidenceReferences,
            String registeredBy, Instant registeredAt) {
        public Processing {
            evidenceReferences = List.copyOf(evidenceReferences);
        }
    }

    public record Inspection(String inspectionId, long inspectionSequence, long roundNumber,
            long processingRevision, String inspectorId, Instant inspectedAt,
            ReworkInspectionResult result, List<ReworkInspectionItem> items) {
        public Inspection {
            items = List.copyOf(items);
        }
    }

    public record Review(String reviewId, long reviewSequence, long roundNumber,
            long processingRevision, String inspectionId, ReviewStatus status,
            String reviewComment, String reviewedBy, Instant reviewedAt) {}
}
