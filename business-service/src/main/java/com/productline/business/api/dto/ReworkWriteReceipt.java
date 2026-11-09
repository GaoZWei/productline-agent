package com.productline.business.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;

/** 首次成功的固定回执；后续重放不能按实体当前状态重新构造。 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record ReworkWriteReceipt(
        String operation, String operationId, String taskId, String reworkTaskId, long taskVersion,
        ProductionTaskStatus status, QualityIssueStatus issueStatus, long roundNumber,
        String previousReworkTaskId, Long processingRevision, String inspectionId, String reviewId) {}
