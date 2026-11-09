package com.productline.business.api.dto;

import com.productline.business.domain.dto.ReworkLifecycleSnapshot;
import com.productline.business.domain.dto.ReworkTaskDto;
import com.productline.business.domain.enums.QualityIssueStatus;
import java.util.List;

/** 查询结果只说明当前事实与动作前提，不能作为人工确认或写入授权。 */
public record ReworkDetailResponse(
        ReworkTaskDto reworkTask, QualityIssueStatus issueStatus, Long roundNumber,
        String previousReworkTaskId, List<AllowedAction> allowedActions, long taskVersion,
        ReworkLifecycleSnapshot.Processing processing,
        ReworkLifecycleSnapshot.Inspection inspection,
        ReworkLifecycleSnapshot.Review review) {

    public ReworkDetailResponse {
        allowedActions = List.copyOf(allowedActions);
    }

    public enum AllowedAction {
        START_REWORK, BLOCK_REWORK, FAIL_REWORK, RESUME_REWORK,
        REGISTER_REWORK_RESULT, REGISTER_REWORK_INSPECTION,
        SUBMIT_REWORK_REVIEW, CREATE_NEXT_REWORK
    }
}
