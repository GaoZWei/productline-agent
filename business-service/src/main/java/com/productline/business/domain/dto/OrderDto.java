package com.productline.business.domain.dto;

import com.productline.business.domain.enums.OrderStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record OrderDto(
        @NotBlank String orderId,
        @NotBlank String productType,
        @NotNull OrderStatus status) {
}
