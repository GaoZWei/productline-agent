package com.productline.business.domain.dto;

import com.productline.business.domain.enums.DeliveryStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record DeliveryRecordDto(
        @NotBlank String deliveryId,
        @NotBlank String orderId,
        @NotNull DeliveryStatus status) {
}
