package com.productline.business.domain.dto;

import com.productline.business.domain.enums.ProductionTaskStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record ReworkTaskDto(
        @NotBlank String reworkTaskId,
        @NotBlank String taskId,
        String sourceIssueId,
        @NotNull ProductionTaskStatus status,
        @NotBlank String reason) {
}
