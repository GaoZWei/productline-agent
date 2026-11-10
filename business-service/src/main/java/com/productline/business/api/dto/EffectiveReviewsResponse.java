package com.productline.business.api.dto;

import com.productline.business.domain.dto.EffectiveReviewSnapshot;
import java.util.List;

public record EffectiveReviewsResponse(String taskId, long taskVersion, List<EffectiveReviewSnapshot> issues) {
    public EffectiveReviewsResponse {
        issues = List.copyOf(issues);
    }
}
