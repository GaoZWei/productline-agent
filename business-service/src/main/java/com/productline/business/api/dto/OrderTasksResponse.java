package com.productline.business.api.dto;

import com.productline.business.domain.dto.ProductionTaskDto;
import java.util.List;

public record OrderTasksResponse(String orderId, List<ProductionTaskDto> tasks) {

    public OrderTasksResponse {
        tasks = List.copyOf(tasks);
    }
}
