package com.productline.business.api.dto;

import com.productline.business.domain.dto.QualityIssueDto;
import com.productline.business.domain.dto.ReviewRecordDto;
import java.util.List;

public record QualityIssueOverviewResponse(
        QualityIssueDto issue, List<ReviewRecordDto> reviews) {

    public QualityIssueOverviewResponse {
        reviews = List.copyOf(reviews);
    }
}
