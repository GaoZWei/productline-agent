package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.jdbc.Sql;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class BusinessQueryApiIntegrationTest extends PostgresIntegrationTestSupport {

    @LocalServerPort private int port;

    @Autowired private TestRestTemplate restTemplate;

    @Test
    void returnsOrderDetailAndNotFoundForUnknownOrder() {
        ResponseEntity<JsonNode> found = get("/api/orders/ORDER-003");
        ResponseEntity<JsonNode> missing = get("/api/orders/ORDER-404");

        assertThat(found.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(found.getBody().path("orderId").asText()).isEqualTo("ORDER-003");
        assertThat(found.getBody().path("productType").asText()).isEqualTo("DOM");
        assertThat(found.getBody().path("status").asText()).isEqualTo("QUALITY_CHECKING");
        assertThat(missing.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    @Sql(
            statements =
                    "INSERT INTO production_orders (order_id, product_type, status)"
                            + " VALUES ('ORDER-API-EMPTY', 'DOM', 'CREATED')")
    @Sql(
            statements = "DELETE FROM production_orders WHERE order_id = 'ORDER-API-EMPTY'",
            executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    void distinguishesEmptyTaskCollectionFromMissingOrder() {
        ResponseEntity<JsonNode> populated = get("/api/orders/ORDER-003/tasks");
        ResponseEntity<JsonNode> empty = get("/api/orders/ORDER-API-EMPTY/tasks");
        ResponseEntity<JsonNode> missing = get("/api/orders/ORDER-404/tasks");

        assertThat(populated.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(populated.getBody().path("orderId").asText()).isEqualTo("ORDER-003");
        assertThat(populated.getBody().path("tasks")).hasSize(1);
        assertThat(populated.getBody().path("tasks").get(0).path("taskId").asText())
                .isEqualTo("TASK-003");
        assertThat(empty.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(empty.getBody().path("tasks").isArray()).isTrue();
        assertThat(empty.getBody().path("tasks")).isEmpty();
        assertThat(missing.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void returnsTaskDetailAndNotFoundForUnknownTask() {
        ResponseEntity<JsonNode> found = get("/api/tasks/TASK-003");
        ResponseEntity<JsonNode> missing = get("/api/tasks/TASK-404");

        assertThat(found.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(found.getBody().path("taskId").asText()).isEqualTo("TASK-003");
        assertThat(found.getBody().path("orderId").asText()).isEqualTo("ORDER-003");
        assertThat(found.getBody().path("status").asText()).isEqualTo("COMPLETED");
        assertThat(found.getBody().path("version").asLong()).isZero();
        assertThat(missing.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    @Sql(
            statements = {
                "INSERT INTO production_orders (order_id, product_type, status)"
                        + " VALUES ('ORDER-API-PROGRESS', 'DOM', 'PRODUCING')",
                "INSERT INTO production_tasks (task_id, order_id, status)"
                        + " VALUES ('TASK-API-PROGRESS', 'ORDER-API-PROGRESS', 'RUNNING')",
                "INSERT INTO production_steps"
                        + " (step_id, task_id, step_name, sequence_number, status)"
                        + " VALUES ('STEP-API-02', 'TASK-API-PROGRESS', '第二步', 2, 'RUNNING')",
                "INSERT INTO production_steps"
                        + " (step_id, task_id, step_name, sequence_number, status)"
                        + " VALUES ('STEP-API-01', 'TASK-API-PROGRESS', '第一步', 1, 'COMPLETED')"
            })
    @Sql(
            statements =
                    "DELETE FROM production_orders WHERE order_id = 'ORDER-API-PROGRESS'",
            executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    void returnsProductionStepsInBusinessSequence() {
        ResponseEntity<JsonNode> response = get("/api/tasks/TASK-API-PROGRESS/progress");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().path("taskId").asText()).isEqualTo("TASK-API-PROGRESS");
        JsonNode steps = response.getBody().path("steps");
        assertThat(steps).hasSize(2);
        assertThat(steps.get(0).path("sequenceNumber").asInt()).isEqualTo(1);
        assertThat(steps.get(0).path("stepId").asText()).isEqualTo("STEP-API-01");
        assertThat(steps.get(1).path("sequenceNumber").asInt()).isEqualTo(2);
    }

    @Test
    void returnsNotFoundWhenProgressTaskDoesNotExist() {
        assertThat(get("/api/tasks/TASK-404/progress").getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void filtersQualityIssuesByStatusWithoutChangingTheResponseShape() {
        ResponseEntity<JsonNode> all = get("/api/tasks/TASK-003/quality-issues");
        ResponseEntity<JsonNode> open = get("/api/tasks/TASK-003/quality-issues?status=OPEN");
        ResponseEntity<JsonNode> closed = get("/api/tasks/TASK-003/quality-issues?status=CLOSED");

        assertThat(all.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(all.getBody().path("issues")).hasSize(1);
        assertThat(open.getBody().path("issues")).hasSize(1);
        assertThat(open.getBody().path("issues").get(0).path("issueId").asText())
                .isEqualTo("ISSUE-001");
        assertThat(open.getBody().path("issues").get(0).path("status").asText())
                .isEqualTo("OPEN");
        assertThat(closed.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(closed.getBody().path("issues")).isEmpty();
    }

    @Test
    void rejectsInvalidQualityIssueStatusAndUnknownTask() {
        assertThat(get("/api/tasks/TASK-003/quality-issues?status=UNKNOWN").getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(get("/api/tasks/TASK-404/quality-issues").getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void returnsReviewRecordsAndUsesEmptyListWhenTaskHasNoReview() {
        ResponseEntity<JsonNode> pending = get("/api/tasks/TASK-003/review");
        ResponseEntity<JsonNode> empty = get("/api/tasks/TASK-001/review");

        assertThat(pending.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(pending.getBody().path("reviews")).hasSize(1);
        assertThat(pending.getBody().path("reviews").get(0).path("reviewId").asText())
                .isEqualTo("REVIEW-003");
        assertThat(pending.getBody().path("reviews").get(0).path("status").asText())
                .isEqualTo("PENDING");
        assertThat(empty.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(empty.getBody().path("reviews")).isEmpty();
    }

    @Test
    void returnsNotFoundWhenReviewTaskDoesNotExist() {
        assertThat(get("/api/tasks/TASK-404/review").getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void returnsBlockedAndReadyDeliveryFacts() {
        ResponseEntity<JsonNode> blocked = get("/api/orders/ORDER-003/delivery-status");
        ResponseEntity<JsonNode> ready = get("/api/orders/ORDER-005/delivery-status");

        assertThat(blocked.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(blocked.getBody().path("records")).hasSize(1);
        assertThat(blocked.getBody().path("records").get(0).path("status").asText())
                .isEqualTo("BLOCKED");
        assertThat(ready.getBody().path("records").get(0).path("status").asText())
                .isEqualTo("READY");
    }

    @Test
    void returnsNotFoundWhenDeliveryOrderDoesNotExist() {
        assertThat(get("/api/orders/ORDER-404/delivery-status").getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void aggregatesTheOrder003GoldenChainWithoutInventingFacts() {
        ResponseEntity<JsonNode> response = get("/api/orders/ORDER-003/overview");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode overview = response.getBody();
        assertThat(overview.path("order").path("orderId").asText()).isEqualTo("ORDER-003");
        assertThat(overview.path("tasks")).hasSize(1);
        JsonNode task = overview.path("tasks").get(0);
        assertThat(task.path("task").path("status").asText()).isEqualTo("COMPLETED");
        assertThat(task.path("steps").get(0).path("status").asText()).isEqualTo("COMPLETED");
        assertThat(task.path("qualityIssues")).hasSize(1);
        JsonNode issue = task.path("qualityIssues").get(0);
        assertThat(issue.path("issue").path("issueType").asText())
                .isEqualTo("COORDINATE_SYSTEM");
        assertThat(issue.path("issue").path("status").asText()).isEqualTo("OPEN");
        assertThat(issue.path("reviews").get(0).path("status").asText()).isEqualTo("PENDING");
        assertThat(overview.path("deliveryRecords").get(0).path("status").asText())
                .isEqualTo("BLOCKED");
    }

    @Test
    void returnsNotFoundWhenOverviewOrderDoesNotExist() {
        assertThat(get("/api/orders/ORDER-404/overview").getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }

    private ResponseEntity<JsonNode> get(String path) {
        return restTemplate.getForEntity("http://127.0.0.1:" + port + path, JsonNode.class);
    }
}
