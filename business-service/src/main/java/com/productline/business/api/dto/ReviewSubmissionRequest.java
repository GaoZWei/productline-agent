package com.productline.business.api.dto;

import com.productline.business.domain.enums.ReviewStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

// 请求参数结构定义
public record ReviewSubmissionRequest(
                @NotBlank String issueId,
                @NotNull ReviewStatus status,
                @NotBlank @Size(max = 1000) String reviewComment,
                @NotNull @PositiveOrZero Long expectedVersion) {
}
