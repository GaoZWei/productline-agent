package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.assertj.core.api.Assertions.assertThatIllegalStateException;

import com.productline.business.domain.dto.OrderDto;
import com.productline.business.domain.enums.OrderStatus;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.model.Order;
import com.productline.business.domain.model.ProductionStep;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import com.productline.business.domain.model.ReworkTask;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.Test;

class DomainModelValidationTest {

    private final Validator validator =
            Validation.buildDefaultValidatorFactory().getValidator();

    @Test
    void rejectsBlankDtoIdentifiers() {
        OrderDto dto = new OrderDto(" ", "DOM", OrderStatus.CREATED);

        assertThat(validator.validate(dto))
                .extracting(violation -> violation.getPropertyPath().toString())
                .containsExactly("orderId");
    }

    @Test
    void rejectsInvalidStepSequence() {
        assertThatIllegalArgumentException()
                .isThrownBy(
                        () ->
                                new ProductionStep(
                                        "STEP-001",
                                        "preprocess",
                                        0,
                                        ProductionTaskStatus.PENDING))
                .withMessage("sequenceNumber must be greater than zero");
    }

    @Test
    void preventsMovingAChildToAnotherAggregate() {
        Order firstOrder = new Order("ORDER-A", "DOM", OrderStatus.CREATED);
        Order secondOrder = new Order("ORDER-B", "DOM", OrderStatus.CREATED);
        ProductionTask task = new ProductionTask("TASK-A", ProductionTaskStatus.PENDING);

        firstOrder.addTask(task);

        assertThatIllegalStateException()
                .isThrownBy(() -> secondOrder.addTask(task))
                .withMessage("task is already assigned to another order");
    }

    @Test
    void preventsReworkFromReferencingAnotherTasksIssue() {
        ProductionTask firstTask =
                new ProductionTask("TASK-A", ProductionTaskStatus.PENDING);
        ProductionTask secondTask =
                new ProductionTask("TASK-B", ProductionTaskStatus.PENDING);
        QualityIssue issue =
                new QualityIssue(
                        "ISSUE-A",
                        "COORDINATE_SYSTEM",
                        QualityIssueStatus.OPEN,
                        "Coordinate system mismatch.");
        ReworkTask rework =
                new ReworkTask(
                        "REWORK-B",
                        ProductionTaskStatus.PENDING,
                        "Correct coordinate system.");

        firstTask.addQualityIssue(issue);
        secondTask.addReworkTask(rework);

        assertThatIllegalArgumentException()
                .isThrownBy(() -> rework.setSourceIssue(issue))
                .withMessage("source issue must belong to the same production task");
    }

    @Test
    void preventsAssigningAReworkAfterItReferencesAnotherTasksIssue() {
        ProductionTask firstTask =
                new ProductionTask("TASK-A", ProductionTaskStatus.PENDING);
        ProductionTask secondTask =
                new ProductionTask("TASK-B", ProductionTaskStatus.PENDING);
        QualityIssue issue =
                new QualityIssue(
                        "ISSUE-A",
                        "COORDINATE_SYSTEM",
                        QualityIssueStatus.OPEN,
                        "Coordinate system mismatch.");
        ReworkTask rework =
                new ReworkTask(
                        "REWORK-B",
                        ProductionTaskStatus.PENDING,
                        "Correct coordinate system.");

        firstTask.addQualityIssue(issue);
        rework.setSourceIssue(issue);

        assertThatIllegalArgumentException()
                .isThrownBy(() -> secondTask.addReworkTask(rework))
                .withMessage("source issue must belong to the same production task");
    }
}
