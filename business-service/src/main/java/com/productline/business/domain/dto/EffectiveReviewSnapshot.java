package com.productline.business.domain.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;

/** 当前绑定与旧复核分开表示；null表示没有真实材料或有效结论，不能补造通过。 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record EffectiveReviewSnapshot(String issueId, String reworkTaskId, Long roundNumber,
        Long processingRevision, String inspectionId, ReworkLifecycleSnapshot.Review review,
        List<ReviewRecordDto> legacyReviews) {
    public EffectiveReviewSnapshot {
        legacyReviews = List.copyOf(legacyReviews);
    }
}
