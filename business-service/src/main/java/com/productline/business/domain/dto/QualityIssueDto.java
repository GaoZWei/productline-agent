package com.productline.business.domain.dto;

import com.productline.business.domain.enums.QualityIssueStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record QualityIssueDto(
        @NotBlank String issueId,
        @NotBlank String taskId,
        @NotBlank String issueType,
        @NotNull QualityIssueStatus status,
        @NotBlank String description) {
}
