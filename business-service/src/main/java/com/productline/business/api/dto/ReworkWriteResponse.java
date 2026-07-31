package com.productline.business.api.dto;

import com.productline.business.domain.dto.ReworkTaskDto;

public record ReworkWriteResponse(ReworkTaskDto reworkTask, long taskVersion) {
}
