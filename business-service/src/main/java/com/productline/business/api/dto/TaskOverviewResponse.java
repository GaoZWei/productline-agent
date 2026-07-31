package com.productline.business.api.dto;

import com.productline.business.domain.dto.ProductionStepDto;
import com.productline.business.domain.dto.ProductionTaskDto;
import java.util.List;

public record TaskOverviewResponse(
        ProductionTaskDto task,
        List<ProductionStepDto> steps,
        List<QualityIssueOverviewResponse> qualityIssues) {

    public TaskOverviewResponse {
        steps = List.copyOf(steps);
        qualityIssues = List.copyOf(qualityIssues);
    }
}
