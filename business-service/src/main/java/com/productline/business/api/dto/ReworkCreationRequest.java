package com.productline.business.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

public record ReworkCreationRequest(
        @NotBlank String sourceIssueId,
        @NotBlank @Size(max = 1000) String reason,
        @NotNull @PositiveOrZero Long expectedVersion) {
}
