package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class BusinessWriteApiIntegrationTest extends PostgresIntegrationTestSupport {

    @LocalServerPort private int port;

    @Autowired private TestRestTemplate restTemplate;
    @Autowired private JdbcTemplate jdbcTemplate;

    @BeforeEach
    void resetWriteFixtures() {
        jdbcTemplate.update("DELETE FROM operation_logs");
        jdbcTemplate.update("DELETE FROM idempotency_records");
        jdbcTemplate.update("DELETE FROM review_records WHERE review_id LIKE 'REVIEW-WRITE-%'");
        jdbcTemplate.update("DELETE FROM rework_tasks WHERE rework_task_id LIKE 'REWORK-WRITE-%'");
        jdbcTemplate.update("UPDATE production_tasks SET version = 0");
    }

    @AfterEach
    void restoreFixedDemoData() {
        resetWriteFixtures();
    }

    @Test
    void reviewerSubmitsReviewAndWritesAuditLog() {
        ResponseEntity<JsonNode> response =
                postReview(
                        "TASK-003",
                        "review-success",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "REWORK_REQUIRED", "需要完成坐标系返工。", 0));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().path("review").path("issueId").asText())
                .isEqualTo("ISSUE-001");
        assertThat(response.getBody().path("review").path("status").asText())
                .isEqualTo("REWORK_REQUIRED");
        assertThat(response.getBody().path("taskVersion").asLong()).isEqualTo(1);
        assertThat(count("review_records", "review_id LIKE 'REVIEW-WRITE-%'"))
                .isEqualTo(1);
        assertThat(count("operation_logs", "operation_type = 'SUBMIT_REVIEW'"))
                .isEqualTo(1);
        assertThat(singleText("SELECT before_state FROM operation_logs"))
                .contains("\"taskVersion\":0");
        assertThat(singleText("SELECT after_state FROM operation_logs"))
                .contains("\"taskVersion\":1", "REWORK_REQUIRED");
    }

    @Test
    void rejectsReviewFromUnauthorizedRoleWithoutWriting() {
        ResponseEntity<JsonNode> response =
                postReview(
                        "TASK-003",
                        "review-forbidden",
                        "VIEWER",
                        reviewBody("ISSUE-001", "REWORK_REQUIRED", "不应写入。", 0));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        assertNoWriteSideEffects();
    }

    @Test
    void rejectsReviewWhenIssueDoesNotBelongToTaskOrConclusionIsPending() {
        ResponseEntity<JsonNode> wrongIssue =
                postReview(
                        "TASK-003",
                        "review-wrong-issue",
                        "REVIEWER",
                        reviewBody("ISSUE-002", "APPROVED", "错误任务。", 0));
        ResponseEntity<JsonNode> pending =
                postReview(
                        "TASK-003",
                        "review-pending",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "PENDING", "不能提交待复核。", 0));

        assertThat(wrongIssue.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(pending.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertNoWriteSideEffects();
    }

    @Test
    void rejectsReviewWhenTaskOrIssueStateDoesNotAllowTheConclusion() {
        ResponseEntity<JsonNode> unfinishedTask =
                postReview(
                        "TASK-002",
                        "review-failed-task",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "REWORK_REQUIRED", "失败任务不能复核。", 0));
        ResponseEntity<JsonNode> openIssueApproval =
                postReview(
                        "TASK-003",
                        "review-open-approval",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "APPROVED", "未解决问题不能通过。", 0));
        ResponseEntity<JsonNode> closedIssue =
                postReview(
                        "TASK-005",
                        "review-closed-issue",
                        "REVIEWER",
                        reviewBody("ISSUE-003", "APPROVED", "关闭问题不能重复复核。", 0));

        assertThat(unfinishedTask.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(openIssueApproval.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(closedIssue.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertNoWriteSideEffects();
    }

    @Test
    void sameReviewIdempotencyKeyReturnsTheOriginalResultOnlyOnce() {
        Map<String, Object> body =
                reviewBody("ISSUE-001", "REWORK_REQUIRED", "幂等复核。", 0);

        ResponseEntity<JsonNode> first =
                postReview("TASK-003", "review-idempotent", "REVIEWER", body);
        ResponseEntity<JsonNode> second =
                postReview("TASK-003", "review-idempotent", "REVIEWER", body);

        assertThat(first.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(second.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(second.getBody()).isEqualTo(first.getBody());
        assertThat(count("review_records", "review_id LIKE 'REVIEW-WRITE-%'"))
                .isEqualTo(1);
        assertThat(count("operation_logs", "operation_type = 'SUBMIT_REVIEW'"))
                .isEqualTo(1);
        assertThat(taskVersion("TASK-003")).isEqualTo(1);
    }

    @Test
    void rejectsReusingIdempotencyKeyForDifferentReviewPayload() {
        ResponseEntity<JsonNode> first =
                postReview(
                        "TASK-003",
                        "review-key-reuse",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "REWORK_REQUIRED", "第一次。", 0));
        ResponseEntity<JsonNode> second =
                postReview(
                        "TASK-003",
                        "review-key-reuse",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "REJECTED", "第二次。", 1));

        assertThat(first.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(second.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(count("review_records", "review_id LIKE 'REVIEW-WRITE-%'"))
                .isEqualTo(1);
        assertThat(count("operation_logs", "operation_type = 'SUBMIT_REVIEW'"))
                .isEqualTo(1);
    }

    @Test
    void rejectsStaleTaskVersionWithoutWriting() {
        ResponseEntity<JsonNode> response =
                postReview(
                        "TASK-003",
                        "review-stale",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "REWORK_REQUIRED", "过期版本。", 9));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertNoWriteSideEffects();
    }

    @Test
    void onlyOneConcurrentWriteWithTheSameExpectedVersionSucceeds() throws Exception {
        CountDownLatch start = new CountDownLatch(1);
        try (ExecutorService executor = Executors.newFixedThreadPool(2)) {
            Future<ResponseEntity<JsonNode>> first =
                    executor.submit(
                            () -> {
                                start.await();
                                return postReview(
                                        "TASK-003",
                                        "review-concurrent-a",
                                        "REVIEWER",
                                        reviewBody(
                                                "ISSUE-001",
                                                "REWORK_REQUIRED",
                                                "并发请求 A。",
                                                0));
                            });
            Future<ResponseEntity<JsonNode>> second =
                    executor.submit(
                            () -> {
                                start.await();
                                return postReview(
                                        "TASK-003",
                                        "review-concurrent-b",
                                        "REVIEWER",
                                        reviewBody(
                                                "ISSUE-001",
                                                "REJECTED",
                                                "并发请求 B。",
                                                0));
                            });

            start.countDown();

            assertThat(
                            new int[] {
                                first.get().getStatusCode().value(),
                                second.get().getStatusCode().value()
                            })
                    .containsExactlyInAnyOrder(
                            HttpStatus.OK.value(), HttpStatus.CONFLICT.value());
        }
        assertThat(count("review_records", "review_id LIKE 'REVIEW-WRITE-%'"))
                .isEqualTo(1);
        assertThat(count("operation_logs", "operation_type = 'SUBMIT_REVIEW'"))
                .isEqualTo(1);
        assertThat(taskVersion("TASK-003")).isEqualTo(1);
    }

    @Test
    void reviewerCreatesPendingReworkAndWritesAuditLog() {
        ResponseEntity<JsonNode> response =
                postRework(
                        "TASK-003",
                        "rework-success",
                        "REVIEWER",
                        reworkBody("ISSUE-001", "修正坐标系统。", 0));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().path("reworkTask").path("sourceIssueId").asText())
                .isEqualTo("ISSUE-001");
        assertThat(response.getBody().path("reworkTask").path("status").asText())
                .isEqualTo("PENDING");
        assertThat(response.getBody().path("taskVersion").asLong()).isEqualTo(1);
        assertThat(count("rework_tasks", "rework_task_id LIKE 'REWORK-WRITE-%'"))
                .isEqualTo(1);
        assertThat(count("operation_logs", "operation_type = 'CREATE_REWORK'"))
                .isEqualTo(1);
        assertThat(singleText("SELECT after_state FROM operation_logs"))
                .contains("\"taskVersion\":1", "PENDING");
    }

    @Test
    void sameReworkRequestWritesOnceAndDifferentKeyCannotDuplicateActiveRework() {
        Map<String, Object> original = reworkBody("ISSUE-001", "修正坐标系统。", 0);

        ResponseEntity<JsonNode> first =
                postRework("TASK-003", "rework-idempotent", "REVIEWER", original);
        ResponseEntity<JsonNode> replay =
                postRework("TASK-003", "rework-idempotent", "REVIEWER", original);
        ResponseEntity<JsonNode> duplicate =
                postRework(
                        "TASK-003",
                        "rework-duplicate",
                        "REVIEWER",
                        reworkBody("ISSUE-001", "再次创建同一返工。", 1));

        assertThat(first.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(replay.getBody()).isEqualTo(first.getBody());
        assertThat(duplicate.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(count("rework_tasks", "rework_task_id LIKE 'REWORK-WRITE-%'"))
                .isEqualTo(1);
        assertThat(count("operation_logs", "operation_type = 'CREATE_REWORK'"))
                .isEqualTo(1);
        assertThat(taskVersion("TASK-003")).isEqualTo(1);
    }

    @Test
    void rejectsReworkForClosedOrUnrelatedIssue() {
        ResponseEntity<JsonNode> closed =
                postRework(
                        "TASK-005",
                        "rework-closed",
                        "REVIEWER",
                        reworkBody("ISSUE-003", "关闭问题不能返工。", 0));
        ResponseEntity<JsonNode> unrelated =
                postRework(
                        "TASK-003",
                        "rework-unrelated",
                        "REVIEWER",
                        reworkBody("ISSUE-002", "问题不属于任务。", 0));

        assertThat(closed.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(unrelated.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertNoWriteSideEffects();
    }

    @Test
    void requiresIdempotencyKeyAndKnownTask() {
        ResponseEntity<JsonNode> missingKey =
                post(
                        "/api/tasks/TASK-003/review",
                        null,
                        "REVIEWER",
                        reviewBody("ISSUE-001", "REWORK_REQUIRED", "缺少幂等键。", 0));
        ResponseEntity<JsonNode> missingTask =
                postReview(
                        "TASK-404",
                        "review-missing-task",
                        "REVIEWER",
                        reviewBody("ISSUE-001", "REWORK_REQUIRED", "任务不存在。", 0));

        assertThat(missingKey.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(missingTask.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertNoWriteSideEffects();
    }

    private ResponseEntity<JsonNode> postReview(
            String taskId, String idempotencyKey, String role, Map<String, Object> body) {
        return post("/api/tasks/" + taskId + "/review", idempotencyKey, role, body);
    }

    private ResponseEntity<JsonNode> postRework(
            String taskId, String idempotencyKey, String role, Map<String, Object> body) {
        return post("/api/tasks/" + taskId + "/rework", idempotencyKey, role, body);
    }

    private ResponseEntity<JsonNode> post(
            String path, String idempotencyKey, String role, Map<String, Object> body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-User-Id", "reviewer-001");
        headers.set("X-User-Role", role);
        if (idempotencyKey != null) {
            headers.set("Idempotency-Key", idempotencyKey);
        }
        return restTemplate.exchange(
                "http://127.0.0.1:" + port + path,
                HttpMethod.POST,
                new HttpEntity<>(body, headers),
                JsonNode.class);
    }

    private Map<String, Object> reviewBody(
            String issueId, String status, String comment, long expectedVersion) {
        return Map.of(
                "issueId", issueId,
                "status", status,
                "reviewComment", comment,
                "expectedVersion", expectedVersion);
    }

    private Map<String, Object> reworkBody(
            String sourceIssueId, String reason, long expectedVersion) {
        return Map.of(
                "sourceIssueId", sourceIssueId,
                "reason", reason,
                "expectedVersion", expectedVersion);
    }

    private long count(String table, String where) {
        return jdbcTemplate
                .queryForObject("SELECT count(*) FROM " + table + " WHERE " + where, Long.class);
    }

    private long taskVersion(String taskId) {
        return jdbcTemplate.queryForObject(
                "SELECT version FROM production_tasks WHERE task_id = ?", Long.class, taskId);
    }

    private String singleText(String sql) {
        return jdbcTemplate.queryForObject(sql, String.class);
    }

    private void assertNoWriteSideEffects() {
        assertThat(count("review_records", "review_id LIKE 'REVIEW-WRITE-%'"))
                .isZero();
        assertThat(count("rework_tasks", "rework_task_id LIKE 'REWORK-WRITE-%'"))
                .isZero();
        assertThat(count("operation_logs", "TRUE")).isZero();
        assertThat(count("idempotency_records", "TRUE")).isZero();
    }
}
