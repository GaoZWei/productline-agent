package com.productline.business.api.dto;

import com.productline.business.domain.dto.DeliveryRecordDto;
import java.util.List;

public record DeliveryStatusResponse(String orderId, List<DeliveryRecordDto> records) {

    public DeliveryStatusResponse {
        records = List.copyOf(records);
    }
}
