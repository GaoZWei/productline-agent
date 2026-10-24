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
    void seedsExactlyTheThirtyDocumentedOrderScenarios() {
        assertThat(orderRepository.findAll())
                .extracting(Order::getOrderId)
                .containsExactlyInAnyOrderElementsOf(java.util.stream.IntStream.rangeClosed(1, 30)
                        .mapToObj(number -> "ORDER-%03d".formatted(number)).toList());
        assertThat(taskRepository.count()).isEqualTo(34);
        assertThat(stepRepository.count()).isEqualTo(38);
        assertThat(issueRepository.count()).isEqualTo(24);
        assertThat(reviewRepository.count()).isEqualTo(23);
        assertThat(reworkRepository.count()).isEqualTo(3);
        assertThat(deliveryRepository.count()).isEqualTo(31);

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
    void keepsAllThirtySeededOrdersBusinessStateConsistent() {
        BusinessStateConsistencyValidator validator =
                new BusinessStateConsistencyValidator();

        assertThat(orderRepository.findAll())
                .allSatisfy(order -> assertThat(validator.validate(order)).isEmpty());
    }

    @Test
    void matchesTheExpandedScenarioContractsAndParentRelationships() {
        String matrix = """
                006|CREATED|-|-|-|-|NOT_READY
                007|PRODUCING|PENDING|PENDING|-|-|NOT_READY
                008|PRODUCING|RUNNING|COMPLETED,RUNNING,PENDING|-|-|NOT_READY
                009|BLOCKED|FAILED|COMPLETED,FAILED,PENDING|-|-|NOT_READY
                010|PRODUCING|COMPLETED,RUNNING|COMPLETED,RUNNING|-|-|NOT_READY
                011|BLOCKED|FAILED,RUNNING|FAILED,RUNNING|-|-|NOT_READY
                012|QUALITY_CHECKING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:PROCESSING|PENDING|BLOCKED
                013|QUALITY_CHECKING|COMPLETED|COMPLETED|CLOUD_COVER:OPEN|PENDING|BLOCKED
                014|QUALITY_CHECKING|COMPLETED|COMPLETED|GEOMETRIC_ACCURACY:OPEN|PENDING|BLOCKED
                015|QUALITY_CHECKING|COMPLETED|COMPLETED|RADIOMETRIC_QUALITY:OPEN|PENDING|BLOCKED
                016|QUALITY_CHECKING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:OPEN,CLOUD_COVER:OPEN|PENDING,PENDING|BLOCKED
                017|QUALITY_CHECKING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:CLOSED,GEOMETRIC_ACCURACY:OPEN|APPROVED,PENDING|BLOCKED
                018|QUALITY_CHECKING|COMPLETED,COMPLETED|COMPLETED,COMPLETED|COORDINATE_SYSTEM:OPEN,COORDINATE_SYSTEM:OPEN|PENDING,PENDING|BLOCKED
                019|REVIEWING|COMPLETED|COMPLETED|CLOUD_COVER:RESOLVED|PENDING|BLOCKED
                020|REVIEWING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:RESOLVED|REJECTED|BLOCKED
                021|REVIEWING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:RESOLVED|REWORK_REQUIRED|BLOCKED
                022|QUALITY_CHECKING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:RESOLVED|-|BLOCKED
                023|REVIEWING|COMPLETED,COMPLETED|COMPLETED,COMPLETED|CLOUD_COVER:RESOLVED,CLOUD_COVER:RESOLVED|PENDING,PENDING|BLOCKED
                024|READY_FOR_DELIVERY|COMPLETED|COMPLETED|-|-|NOT_READY
                025|BLOCKED|COMPLETED|COMPLETED|-|-|FAILED
                026|DELIVERING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:CLOSED|APPROVED|DELIVERING
                027|DELIVERED|COMPLETED|COMPLETED|COORDINATE_SYSTEM:CLOSED|APPROVED|DELIVERED
                028|BLOCKED|COMPLETED|COMPLETED|-|-|READY,FAILED
                029|QUALITY_CHECKING|COMPLETED|COMPLETED|COORDINATE_SYSTEM:OPEN|REWORK_REQUIRED|BLOCKED
                030|QUALITY_CHECKING|COMPLETED,COMPLETED|COMPLETED,COMPLETED|COORDINATE_SYSTEM:PROCESSING,COORDINATE_SYSTEM:RESOLVED|REWORK_REQUIRED,PENDING|BLOCKED
                """;
        matrix.lines().forEach(row -> {
            String[] expected = row.split("[|]");
            String orderId = "ORDER-" + expected[0];
            Order order = orderRepository.findById(orderId).orElseThrow();
            var tasks = taskRepository.findAllByOrderOrderIdOrderByTaskIdAsc(orderId);
            assertThat(order.getStatus().name()).as(orderId).isEqualTo(expected[1]);
            assertThat(tasks.stream().map(task -> task.getStatus().name()).toList())
                    .as(orderId).containsExactlyElementsOf(values(expected[2]));
            assertThat(tasks.stream().flatMap(task -> stepRepository
                    .findAllByTaskTaskIdOrderBySequenceNumberAsc(task.getTaskId()).stream())
                    .map(step -> step.getStatus().name()).toList())
                    .as(orderId).containsExactlyElementsOf(values(expected[3]));
            assertThat(tasks.stream().flatMap(task -> issueRepository
                    .findAllByTaskTaskIdOrderByIssueIdAsc(task.getTaskId()).stream())
                    .map(issue -> issue.getIssueType() + ":" + issue.getStatus().name()).toList())
                    .as(orderId).containsExactlyElementsOf(values(expected[4]));
            assertThat(tasks.stream().flatMap(task -> reviewRepository
                    .findAllByTaskIdOrderByReviewIdAsc(task.getTaskId()).stream())
                    .map(review -> review.getStatus().name()).toList())
                    .as(orderId).containsExactlyElementsOf(values(expected[5]));
            assertThat(deliveryRepository.findAllByOrderOrderIdOrderByDeliveryIdAsc(orderId).stream()
                    .map(delivery -> delivery.getStatus().name()).toList())
                    .as(orderId).containsExactlyElementsOf(values(expected[6]));
        });
        assertThat(orderRepository.findAll()).allSatisfy(order -> {
            assertThat(order.getProductType()).isEqualTo("DOM");
            order.getTasks().forEach(task -> {
                assertThat(task.getOrder().getOrderId()).isEqualTo(order.getOrderId());
                assertThat(task.getVersion()).isZero();
                task.getSteps().forEach(step -> assertThat(step.getTask().getTaskId()).isEqualTo(task.getTaskId()));
                task.getQualityIssues().forEach(issue -> {
                    assertThat(issue.getTask().getTaskId()).isEqualTo(task.getTaskId());
                    issue.getReviewRecords().forEach(review ->
                            assertThat(review.getIssue().getIssueId()).isEqualTo(issue.getIssueId()));
                });
            });
        });
        assertThat(reworkRepository.findAll()).allSatisfy(rework -> {
            assertThat(rework.getReworkTaskId()).doesNotStartWith("REWORK-WRITE-");
            assertThat(rework.getSourceIssue()).isNotNull();
            assertThat(rework.getSourceIssue().getTask().getTaskId()).isEqualTo(rework.getTask().getTaskId());
        });
        assertThat(reworkRepository.findById("REWORK-029-01").orElseThrow().getStatus()).isEqualTo(ProductionTaskStatus.PENDING);
        assertThat(reworkRepository.findById("REWORK-030-A-01").orElseThrow().getStatus()).isEqualTo(ProductionTaskStatus.RUNNING);
        assertThat(reworkRepository.findById("REWORK-030-B-01").orElseThrow().getStatus()).isEqualTo(ProductionTaskStatus.COMPLETED);
    }

    private java.util.List<String> values(String value) {
        return value.equals("-") ? java.util.List.of() : java.util.List.of(value.split(","));
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
