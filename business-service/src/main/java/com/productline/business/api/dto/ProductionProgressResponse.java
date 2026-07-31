package com.productline.business.api.dto;

import com.productline.business.domain.dto.ProductionStepDto;
import java.util.List;

public record ProductionProgressResponse(String taskId, List<ProductionStepDto> steps) {

    public ProductionProgressResponse {
        steps = List.copyOf(steps);
    }
}
