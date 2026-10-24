package com.productline.business.api.dto;

import com.productline.business.domain.dto.OrderDto;
import java.util.List;

public record OrderListResponse(List<OrderDto> orders) {
    public OrderListResponse {
        orders = List.copyOf(orders);
    }
}
