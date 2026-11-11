package com.productline.business.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.productline.business.domain.dto.DeliveryRecordDto;
import com.productline.business.domain.dto.EffectiveReviewSnapshot;
import com.productline.business.domain.dto.OrderDto;
import com.productline.business.domain.dto.ProductionStepDto;
import com.productline.business.domain.dto.QualityIssueDto;
import com.productline.business.domain.dto.ReworkTaskDto;
import com.productline.business.domain.enums.ProductionTaskStatus;
import java.util.List;

/** 同一读取快照内的已知条件；没有阻塞不等于授权交付或改变订单状态。 */
public record DeliveryConditionsResponse(OrderDto order, List<TaskConditions> tasks,
        List<DeliveryRecordDto> deliveryRecords, List<Blocker> blockers, boolean hasBlockers) {
    public DeliveryConditionsResponse {
        tasks = List.copyOf(tasks);
        deliveryRecords = List.copyOf(deliveryRecords);
        blockers = List.copyOf(blockers);
        hasBlockers = !blockers.isEmpty();
    }

    public record TaskConditions(String taskId, long taskVersion, ProductionTaskStatus productionStatus,
            List<ProductionStepDto> steps, List<IssueCondition> issues, List<ReworkTaskDto> activeReworks) {
        public TaskConditions {
            steps = List.copyOf(steps);
            issues = List.copyOf(issues);
            activeReworks = List.copyOf(activeReworks);
        }
    }

    public record IssueCondition(QualityIssueDto issue, EffectiveReviewSnapshot effectiveReview) {}

    @JsonInclude(JsonInclude.Include.ALWAYS)
    public record Blocker(Code code, String taskId, String resourceId, String status) {}

    public enum Code {
        ORDER_BLOCKED,
        MISSING_PRODUCTION_TASKS,
        PRODUCTION_TASK_NOT_COMPLETED,
        MISSING_PRODUCTION_STEPS,
        PRODUCTION_STEP_NOT_COMPLETED,
        ACTIVE_REWORK,
        QUALITY_ISSUE_UNRESOLVED,
        CONTROLLED_ISSUE_NOT_CLOSED,
        EFFECTIVE_REVIEW_NOT_APPROVED,
        LEGACY_REVIEW_NOT_APPROVED,
        LEGACY_RESOLVED_ISSUE_WITHOUT_APPROVAL,
        MISSING_DELIVERY_RECORDS,
        DELIVERY_NOT_READY
    }
}
