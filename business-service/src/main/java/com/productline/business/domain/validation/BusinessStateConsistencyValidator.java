package com.productline.business.domain.validation;

import com.productline.business.domain.enums.DeliveryStatus;
import com.productline.business.domain.enums.OrderStatus;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.model.Order;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import java.util.EnumSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * 判断跨订单、生产、质检、复核和交付对象的状态组合是否违反业务基线。
 *
 * <p>该类只返回稳定的违规代码，不执行持久化或状态修改。后续写接口可以在提交事务前调用它，
 * 再把违规代码映射到统一错误模型。
 */
public final class BusinessStateConsistencyValidator {

    public enum Violation {
        DELIVERED_ORDER_HAS_INCOMPLETE_TASK,
        READY_DELIVERY_HAS_OPEN_QUALITY_ISSUE,
        DELIVERED_ORDER_HAS_PENDING_REVIEW
    }

    public List<Violation> validate(Order order) {
        Order requiredOrder = Objects.requireNonNull(order, "order");
        Set<Violation> violations = EnumSet.noneOf(Violation.class);

        if (requiredOrder.getStatus() == OrderStatus.DELIVERED
                && requiredOrder.getTasks().stream()
                        .anyMatch(
                                task ->
                                        task.getStatus()
                                                != ProductionTaskStatus.COMPLETED)) {
            violations.add(Violation.DELIVERED_ORDER_HAS_INCOMPLETE_TASK);
        }

        boolean hasReadyDelivery =
                requiredOrder.getDeliveryRecords().stream()
                        .anyMatch(record -> record.getStatus() == DeliveryStatus.READY);
        boolean hasOpenQualityIssue =
                requiredOrder.getTasks().stream()
                        .flatMap(task -> task.getQualityIssues().stream())
                        .anyMatch(issue -> issue.getStatus() == QualityIssueStatus.OPEN);
        if (hasReadyDelivery && hasOpenQualityIssue) {
            violations.add(Violation.READY_DELIVERY_HAS_OPEN_QUALITY_ISSUE);
        }

        if (requiredOrder.getStatus() == OrderStatus.DELIVERED
                && hasPendingReview(requiredOrder)) {
            violations.add(Violation.DELIVERED_ORDER_HAS_PENDING_REVIEW);
        }

        return List.copyOf(violations);
    }

    private boolean hasPendingReview(Order order) {
        return order.getTasks().stream()
                .map(ProductionTask::getQualityIssues)
                .flatMap(List::stream)
                .map(QualityIssue::getReviewRecords)
                .flatMap(List::stream)
                .anyMatch(review -> review.getStatus() == ReviewStatus.PENDING);
    }
}
