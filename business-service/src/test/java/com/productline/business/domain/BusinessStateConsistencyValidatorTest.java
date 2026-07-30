package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;

import com.productline.business.domain.enums.DeliveryStatus;
import com.productline.business.domain.enums.OrderStatus;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.model.DeliveryRecord;
import com.productline.business.domain.model.Order;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import com.productline.business.domain.model.ReviewRecord;
import com.productline.business.domain.validation.BusinessStateConsistencyValidator;
import com.productline.business.domain.validation.BusinessStateConsistencyValidator.Violation;
import org.junit.jupiter.api.Test;

class BusinessStateConsistencyValidatorTest {

    private final BusinessStateConsistencyValidator validator =
            new BusinessStateConsistencyValidator();

    @Test
    void rejectsDeliveredOrderWhenItsTaskIsIncomplete() {
        Order order = new Order("ORDER-INVALID-001", "DOM", OrderStatus.DELIVERED);
        order.addTask(new ProductionTask("TASK-INVALID-001", ProductionTaskStatus.RUNNING));
        order.addDeliveryRecord(
                new DeliveryRecord("DELIVERY-INVALID-001", DeliveryStatus.DELIVERED));

        assertThat(validator.validate(order))
                .containsExactly(Violation.DELIVERED_ORDER_HAS_INCOMPLETE_TASK);
    }

    @Test
    void rejectsReadyDeliveryWhenAnOpenQualityIssueExists() {
        Order order = new Order("ORDER-INVALID-002", "DOM", OrderStatus.READY_FOR_DELIVERY);
        ProductionTask task =
                new ProductionTask("TASK-INVALID-002", ProductionTaskStatus.COMPLETED);
        task.addQualityIssue(
                new QualityIssue(
                        "ISSUE-INVALID-002",
                        "COORDINATE_SYSTEM",
                        QualityIssueStatus.OPEN,
                        "坐标系问题未关闭。"));
        order.addTask(task);
        order.addDeliveryRecord(
                new DeliveryRecord("DELIVERY-INVALID-002", DeliveryStatus.READY));

        assertThat(validator.validate(order))
                .containsExactly(Violation.READY_DELIVERY_HAS_OPEN_QUALITY_ISSUE);
    }

    @Test
    void rejectsDeliveredOrderWhenAReviewIsPending() {
        Order order = new Order("ORDER-INVALID-003", "DOM", OrderStatus.DELIVERED);
        ProductionTask task =
                new ProductionTask("TASK-INVALID-003", ProductionTaskStatus.COMPLETED);
        QualityIssue issue =
                new QualityIssue(
                        "ISSUE-INVALID-003",
                        "COORDINATE_SYSTEM",
                        QualityIssueStatus.RESOLVED,
                        "坐标系问题已处理。");
        issue.addReviewRecord(
                new ReviewRecord("REVIEW-INVALID-003", ReviewStatus.PENDING, null));
        task.addQualityIssue(issue);
        order.addTask(task);
        order.addDeliveryRecord(
                new DeliveryRecord("DELIVERY-INVALID-003", DeliveryStatus.DELIVERED));

        assertThat(validator.validate(order))
                .containsExactly(Violation.DELIVERED_ORDER_HAS_PENDING_REVIEW);
    }
}
