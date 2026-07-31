package com.productline.business.api.dto;

import com.productline.business.domain.dto.DeliveryRecordDto;
import com.productline.business.domain.dto.OrderDto;
import java.util.List;

public record OrderOverviewResponse(
        OrderDto order,
        List<TaskOverviewResponse> tasks,
        List<DeliveryRecordDto> deliveryRecords) {

    public OrderOverviewResponse {
        tasks = List.copyOf(tasks);
        deliveryRecords = List.copyOf(deliveryRecords);
    }
}
