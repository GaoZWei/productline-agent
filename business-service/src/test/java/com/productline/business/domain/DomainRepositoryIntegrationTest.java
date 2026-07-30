package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;

import com.productline.business.domain.enums.DeliveryStatus;
import com.productline.business.domain.enums.OrderStatus;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.model.DeliveryRecord;
import com.productline.business.domain.model.Order;
import com.productline.business.domain.model.ProductionStep;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import com.productline.business.domain.model.ReviewRecord;
import com.productline.business.domain.model.ReworkTask;
import com.productline.business.domain.repository.DeliveryRecordRepository;
import com.productline.business.domain.repository.OrderRepository;
import com.productline.business.domain.repository.ProductionStepRepository;
import com.productline.business.domain.repository.ProductionTaskRepository;
import com.productline.business.domain.repository.QualityIssueRepository;
import com.productline.business.domain.repository.ReviewRecordRepository;
import com.productline.business.domain.repository.ReworkTaskRepository;
import com.productline.business.support.PostgresIntegrationTestSupport;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class DomainRepositoryIntegrationTest extends PostgresIntegrationTestSupport {

    @Autowired private OrderRepository orderRepository;
    @Autowired private ProductionTaskRepository taskRepository;
    @Autowired private ProductionStepRepository stepRepository;
    @Autowired private QualityIssueRepository issueRepository;
    @Autowired private ReviewRecordRepository reviewRepository;
    @Autowired private ReworkTaskRepository reworkRepository;
    @Autowired private DeliveryRecordRepository deliveryRepository;
    @Autowired private EntityManager entityManager;

    @Test
    void persistsAndQueriesAnIndependentRelationshipChain() {
        Order order =
                new Order("ORDER-MODEL-TEST", "DOM", OrderStatus.QUALITY_CHECKING);
        ProductionTask task =
                new ProductionTask("TASK-MODEL-TEST", ProductionTaskStatus.COMPLETED);
        ProductionStep step =
                new ProductionStep(
                        "STEP-MODEL-TEST-01",
                        "DOM production",
                        1,
                        ProductionTaskStatus.COMPLETED);
        QualityIssue issue =
                new QualityIssue(
                        "ISSUE-MODEL-TEST",
                        "COORDINATE_SYSTEM",
                        QualityIssueStatus.OPEN,
                        "Product coordinate system does not match the specification.");
        ReviewRecord review =
                new ReviewRecord("REVIEW-MODEL-TEST", ReviewStatus.PENDING, null);
        ReworkTask rework =
                new ReworkTask(
                        "REWORK-MODEL-TEST",
                        ProductionTaskStatus.PENDING,
                        "Correct the coordinate system.");
        DeliveryRecord delivery =
                new DeliveryRecord("DELIVERY-MODEL-TEST", DeliveryStatus.BLOCKED);

        order.addTask(task);
        order.addDeliveryRecord(delivery);
        task.addStep(step);
        task.addQualityIssue(issue);
        issue.addReviewRecord(review);
        task.addReworkTask(rework);
        rework.setSourceIssue(issue);

        orderRepository.saveAndFlush(order);
        entityManager.clear();

        Order persistedOrder =
                orderRepository.findById("ORDER-MODEL-TEST").orElseThrow();
        ProductionTask persistedTask =
                taskRepository.findById("TASK-MODEL-TEST").orElseThrow();
        QualityIssue persistedIssue =
                issueRepository.findById("ISSUE-MODEL-TEST").orElseThrow();
        ReviewRecord persistedReview =
                reviewRepository.findById("REVIEW-MODEL-TEST").orElseThrow();
        DeliveryRecord persistedDelivery =
                deliveryRepository.findById("DELIVERY-MODEL-TEST").orElseThrow();

        assertThat(persistedOrder.getTasks()).extracting(ProductionTask::getTaskId)
                .containsExactly("TASK-MODEL-TEST");
        assertThat(persistedTask.getOrder().getOrderId()).isEqualTo("ORDER-MODEL-TEST");
        assertThat(persistedTask.getSteps()).extracting(ProductionStep::getStepId)
                .containsExactly("STEP-MODEL-TEST-01");
        assertThat(persistedTask.getQualityIssues()).extracting(QualityIssue::getIssueId)
                .containsExactly("ISSUE-MODEL-TEST");
        assertThat(persistedIssue.getReviewRecords()).extracting(ReviewRecord::getReviewId)
                .containsExactly("REVIEW-MODEL-TEST");
        assertThat(persistedReview.getStatus()).isEqualTo(ReviewStatus.PENDING);
        assertThat(persistedDelivery.getStatus()).isEqualTo(DeliveryStatus.BLOCKED);
        assertThat(stepRepository.findById("STEP-MODEL-TEST-01")).isPresent();
        assertThat(reworkRepository.findById("REWORK-MODEL-TEST")).isPresent();
        assertThat(deliveryRepository.findById("DELIVERY-MODEL-TEST")).isPresent();
    }
}
