package com.productline.business.api.dto;

import com.productline.business.domain.dto.ReviewRecordDto;
import java.util.List;

public record ReviewResultResponse(String taskId, List<ReviewRecordDto> reviews) {

    public ReviewResultResponse {
        reviews = List.copyOf(reviews);
    }
}
