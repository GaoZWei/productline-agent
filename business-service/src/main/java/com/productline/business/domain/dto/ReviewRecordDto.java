package com.productline.business.domain.dto;

import com.productline.business.domain.enums.ReviewStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record ReviewRecordDto(
        @NotBlank String reviewId,
        @NotBlank String issueId,
        @NotNull ReviewStatus status,
        String reviewComment) {
}
