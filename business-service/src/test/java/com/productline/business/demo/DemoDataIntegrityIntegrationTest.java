package com.productline.business.demo;

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
import com.productline.business.domain.repository.DeliveryRecordRepository;
import com.productline.business.domain.repository.OrderRepository;
import com.productline.business.domain.repository.ProductionStepRepository;
import com.productline.business.domain.repository.ProductionTaskRepository;
import com.productline.business.domain.repository.QualityIssueRepository;
import com.productline.business.domain.repository.ReviewRecordRepository;
import com.productline.business.domain.repository.ReworkTaskRepository;
import com.productline.business.domain.validation.BusinessStateConsistencyValidator;
import com.productline.business.support.PostgresIntegrationTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class DemoDataIntegrityIntegrationTest extends PostgresIntegrationTestSupport {

    @Autowired private OrderRepository orderRepository;
    @Autowired private ProductionTaskRepository taskRepository;
    @Autowired private ProductionStepRepository stepRepository;
    @Autowired private QualityIssueRepository issueRepository;
    @Autowired private ReviewRecordRepository reviewRepository;
    @Autowired private ReworkTaskRepository reworkRepository;
    @Autowired private DeliveryRecordRepository deliveryRepository;

    @Test
    void seedsExactlyTheFiveDocumentedOrderScenarios() {
        assertThat(orderRepository.findAll())
                .extracting(Order::getOrderId)
                .containsExactlyInAnyOrder(
                        "ORDER-001", "ORDER-002", "ORDER-003", "ORDER-004", "ORDER-005");
        assertThat(taskRepository.count()).isEqualTo(5);
        assertThat(stepRepository.count()).isEqualTo(5);
        assertThat(issueRepository.count()).isEqualTo(3);
        assertThat(reviewRepository.count()).isEqualTo(3);
        assertThat(reworkRepository.count()).isZero();
        assertThat(deliveryRepository.count()).isEqualTo(5);

        assertScenario(
                "ORDER-001",
                OrderStatus.PRODUCING,
                "TASK-001",
                ProductionTaskStatus.RUNNING,
                null,
                null,
                null,
                DeliveryStatus.NOT_READY);
        assertScenario(
                "ORDER-002",
                OrderStatus.BLOCKED,
                "TASK-002",
                ProductionTaskStatus.FAILED,
                null,
                null,
                null,
                DeliveryStatus.NOT_READY);
        assertScenario(
                "ORDER-003",
                OrderStatus.QUALITY_CHECKING,
                "TASK-003",
                ProductionTaskStatus.COMPLETED,
                "ISSUE-001",
                QualityIssueStatus.OPEN,
                ReviewStatus.PENDING,
                DeliveryStatus.BLOCKED);
        assertScenario(
                "ORDER-004",
                OrderStatus.REVIEWING,
                "TASK-004",
                ProductionTaskStatus.COMPLETED,
                "ISSUE-002",
                QualityIssueStatus.RESOLVED,
                ReviewStatus.PENDING,
                DeliveryStatus.BLOCKED);
        assertScenario(
                "ORDER-005",
                OrderStatus.READY_FOR_DELIVERY,
                "TASK-005",
                ProductionTaskStatus.COMPLETED,
                "ISSUE-003",
                QualityIssueStatus.CLOSED,
                ReviewStatus.APPROVED,
                DeliveryStatus.READY);
    }

    @Test
    void keepsTheOrder002FailureAtImagePreprocessing() {
        ProductionTask task = taskRepository.findById("TASK-002").orElseThrow();

        assertThat(task.getSteps())
                .singleElement()
                .extracting(
                        ProductionStep::getStepName,
                        ProductionStep::getSequenceNumber,
                        ProductionStep::getStatus)
                .containsExactly("影像预处理", 1, ProductionTaskStatus.FAILED);
    }

    @Test
    void preservesTheOrder003GoldenChain() {
        Order order = orderRepository.findById("ORDER-003").orElseThrow();
        ProductionTask task = taskRepository.findById("TASK-003").orElseThrow();
        QualityIssue issue = issueRepository.findById("ISSUE-001").orElseThrow();

        assertThat(order.getTasks()).extracting(ProductionTask::getTaskId)
                .containsExactly("TASK-003");
        assertThat(task.getOrder().getOrderId()).isEqualTo("ORDER-003");
        assertThat(task.getQualityIssues()).extracting(QualityIssue::getIssueId)
                .containsExactly("ISSUE-001");
        assertThat(issue.getIssueType()).isEqualTo("COORDINATE_SYSTEM");
        assertThat(issue.getReviewRecords()).extracting(ReviewRecord::getStatus)
                .containsExactly(ReviewStatus.PENDING);
        assertThat(order.getDeliveryRecords()).extracting(DeliveryRecord::getStatus)
                .containsExactly(DeliveryStatus.BLOCKED);
    }

    @Test
    void keepsAllFiveSeededOrdersBusinessStateConsistent() {
        BusinessStateConsistencyValidator validator =
                new BusinessStateConsistencyValidator();

        assertThat(orderRepository.findAll())
                .allSatisfy(order -> assertThat(validator.validate(order)).isEmpty());
    }

    private void assertScenario(
            String orderId,
            OrderStatus orderStatus,
            String taskId,
            ProductionTaskStatus taskStatus,
            String issueId,
            QualityIssueStatus issueStatus,
            ReviewStatus reviewStatus,
            DeliveryStatus deliveryStatus) {
        Order order = orderRepository.findById(orderId).orElseThrow();
        ProductionTask task = taskRepository.findById(taskId).orElseThrow();

        assertThat(order.getStatus()).isEqualTo(orderStatus);
        assertThat(order.getTasks()).extracting(ProductionTask::getTaskId)
                .containsExactly(taskId);
        assertThat(task.getStatus()).isEqualTo(taskStatus);
        assertThat(order.getDeliveryRecords()).extracting(DeliveryRecord::getStatus)
                .containsExactly(deliveryStatus);

        if (issueId == null) {
            assertThat(task.getQualityIssues()).isEmpty();
            return;
        }

        QualityIssue issue = issueRepository.findById(issueId).orElseThrow();
        assertThat(task.getQualityIssues()).extracting(QualityIssue::getIssueId)
                .containsExactly(issueId);
        assertThat(issue.getStatus()).isEqualTo(issueStatus);
        assertThat(issue.getReviewRecords()).extracting(ReviewRecord::getStatus)
                .containsExactly(reviewStatus);
    }
}
