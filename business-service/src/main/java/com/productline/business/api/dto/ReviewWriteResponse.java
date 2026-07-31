package com.productline.business.api.dto;

import com.productline.business.domain.dto.ReviewRecordDto;

public record ReviewWriteResponse(ReviewRecordDto review, long taskVersion) {
}
