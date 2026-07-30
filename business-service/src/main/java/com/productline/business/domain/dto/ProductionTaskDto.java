package com.productline.business.domain.dto;

import com.productline.business.domain.enums.ProductionTaskStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record ProductionTaskDto(
        @NotBlank String taskId,
        @NotBlank String orderId,
        @NotNull ProductionTaskStatus status) {
}
