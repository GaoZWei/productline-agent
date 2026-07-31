package com.productline.business.api.dto;

import com.productline.business.domain.dto.QualityIssueDto;
import java.util.List;

// 响应结构定义
public record QualityIssueListResponse(String taskId, List<QualityIssueDto> issues) {

    public QualityIssueListResponse {
        issues = List.copyOf(issues);
    }
}
