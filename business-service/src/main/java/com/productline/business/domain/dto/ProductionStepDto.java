package com.productline.business.domain.dto;

import com.productline.business.domain.enums.ProductionTaskStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record ProductionStepDto(
        @NotBlank String stepId,
        @NotBlank String taskId,
        @NotBlank String stepName,
        @Positive int sequenceNumber,
        @NotNull ProductionTaskStatus status) {
}
