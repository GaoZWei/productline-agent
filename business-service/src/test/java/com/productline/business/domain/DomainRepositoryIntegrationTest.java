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
    void persistsAndQueriesTheOrder003GoldenRelationshipChain() {
        Order order = new Order("ORDER-003", "DOM", OrderStatus.QUALITY_CHECKING);
        ProductionTask task =
                new ProductionTask("TASK-003", ProductionTaskStatus.COMPLETED);
        ProductionStep step =
                new ProductionStep(
                        "STEP-003-01",
                        "DOM production",
                        1,
                        ProductionTaskStatus.COMPLETED);
        QualityIssue issue =
                new QualityIssue(
                        "ISSUE-001",
                        "COORDINATE_SYSTEM",
                        QualityIssueStatus.OPEN,
                        "Product coordinate system does not match the specification.");
        ReviewRecord review = new ReviewRecord("REVIEW-003", ReviewStatus.PENDING, null);
        ReworkTask rework =
                new ReworkTask(
                        "REWORK-003",
                        ProductionTaskStatus.PENDING,
                        "Correct the coordinate system.");
        DeliveryRecord delivery =
                new DeliveryRecord("DELIVERY-003", DeliveryStatus.BLOCKED);

        order.addTask(task);
        order.addDeliveryRecord(delivery);
        task.addStep(step);
        task.addQualityIssue(issue);
        issue.addReviewRecord(review);
        task.addReworkTask(rework);
        rework.setSourceIssue(issue);

        orderRepository.saveAndFlush(order);
        entityManager.clear();

        Order persistedOrder = orderRepository.findById("ORDER-003").orElseThrow();
        ProductionTask persistedTask = taskRepository.findById("TASK-003").orElseThrow();
        QualityIssue persistedIssue = issueRepository.findById("ISSUE-001").orElseThrow();
        ReviewRecord persistedReview = reviewRepository.findById("REVIEW-003").orElseThrow();
        DeliveryRecord persistedDelivery =
                deliveryRepository.findById("DELIVERY-003").orElseThrow();

        assertThat(persistedOrder.getTasks()).extracting(ProductionTask::getTaskId)
                .containsExactly("TASK-003");
        assertThat(persistedTask.getOrder().getOrderId()).isEqualTo("ORDER-003");
        assertThat(persistedTask.getSteps()).extracting(ProductionStep::getStepId)
                .containsExactly("STEP-003-01");
        assertThat(persistedTask.getQualityIssues()).extracting(QualityIssue::getIssueId)
                .containsExactly("ISSUE-001");
        assertThat(persistedIssue.getReviewRecords()).extracting(ReviewRecord::getReviewId)
                .containsExactly("REVIEW-003");
        assertThat(persistedReview.getStatus()).isEqualTo(ReviewStatus.PENDING);
        assertThat(persistedDelivery.getStatus()).isEqualTo(DeliveryStatus.BLOCKED);
        assertThat(stepRepository.count()).isOne();
        assertThat(reworkRepository.count()).isOne();
        assertThat(deliveryRepository.count()).isOne();
    }
}
