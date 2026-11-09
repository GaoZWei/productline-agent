package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.application.ReworkQueryService;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.sql.Connection;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;

/** 真实HTTP、授权、SQL快照和V5材料选择；仅使用本测试独占schema。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t806_rework_query", "spring.flyway.default-schema=t806_rework_query",
        "spring.datasource.hikari.schema=t806_rework_query",
        "spring.jpa.properties.hibernate.default_schema=t806_rework_query"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkQueryApiIntegrationTest extends PostgresIntegrationTestSupport {
    private static final String ROOT = "/api/tasks/TASK-T806/reworks/REWORK-T806-";
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private ReworkQueryService service;
    @Autowired private PlatformTransactionManager transactionManager;
    @Autowired private DataSource dataSource;

    @BeforeAll
    void fixtures() throws Exception {
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T806','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status,version) VALUES ('TASK-T806','ORDER-T806','COMPLETED',7),('TASK-T806-NOTDONE','ORDER-T806','RUNNING',3)");
        fixture("LEGACY", "PENDING", "OPEN", false);
        jdbc.update("INSERT INTO rework_tasks VALUES ('REWORK-T806-NOSOURCE','TASK-T806',NULL,'FAILED','保留无来源历史')");
        fixture("PENDING", "PENDING", "OPEN", true);
        fixture("RUNNING", "RUNNING", "PROCESSING", true);
        fixture("RESULT", "RUNNING", "PROCESSING", true);
        processing("RESULT", 1);
        fixture("BLOCKED", "BLOCKED", "PROCESSING", true);
        fixture("FAILED", "FAILED", "PROCESSING", true);
        fixture("PASSED", "COMPLETED", "RESOLVED", true);
        processing("PASSED", 1);
        inspection("PASSED", 1, 1, "PASSED");
        fixture("REJECTED", "COMPLETED", "OPEN", true);
        processing("REJECTED", 1);
        inspection("REJECTED", 1, 1, "PASSED");
        review("REJECTED", 1, "REJECTED");
        fixture("CLOSED", "COMPLETED", "CLOSED", true);
        processing("CLOSED", 1);
        inspection("CLOSED", 1, 1, "PASSED");
        review("CLOSED", 1, "APPROVED");
        fixture("NEWREVISION", "RUNNING", "PROCESSING", true);
        processing("NEWREVISION", 1);
        inspection("NEWREVISION", 1, 1, "PASSED");
        review("NEWREVISION", 1, "APPROVED");
        processing("NEWREVISION", 2);
        fixture("NEWFAILED", "COMPLETED", "RESOLVED", true);
        processing("NEWFAILED", 1);
        inspection("NEWFAILED", 1, 1, "PASSED");
        review("NEWFAILED", 1, "APPROVED");
        inspection("NEWFAILED", 1, 2, "FAILED");
        fixture("NEWCHECK", "COMPLETED", "RESOLVED", true);
        processing("NEWCHECK", 1);
        inspection("NEWCHECK", 1, 1, "PASSED");
        review("NEWCHECK", 1, "APPROVED");
        inspection("NEWCHECK", 1, 2, "PASSED");
        fixture("NEWREVIEW", "COMPLETED", "OPEN", true);
        processing("NEWREVIEW", 1);
        inspection("NEWREVIEW", 1, 1, "PASSED");
        review("NEWREVIEW", 1, "REJECTED");
        review("NEWREVIEW", 2, "APPROVED");
        fixture("ACTIVE", "COMPLETED", "OPEN", true);
        processing("ACTIVE", 1);
        inspection("ACTIVE", 1, 1, "PASSED");
        review("ACTIVE", 1, "REWORK_REQUIRED");
        jdbc.update("INSERT INTO rework_tasks VALUES ('REWORK-T806-ACTIVE-OTHER','TASK-T806','ISSUE-T806-ACTIVE','PENDING','既有活动返工')");
        fixture("PREVIOUS", "COMPLETED", "OPEN", true);
        processing("PREVIOUS", 1);
        inspection("PREVIOUS", 1, 1, "PASSED");
        review("PREVIOUS", 1, "REJECTED");
        jdbc.update("INSERT INTO rework_tasks VALUES ('REWORK-T806-NEXT','TASK-T806','ISSUE-T806-PREVIOUS','PENDING','真实后继')");
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES ('REWORK-T806-NEXT','TASK-T806','ISSUE-T806-PREVIOUS',2,'REWORK-T806-PREVIOUS',1,'reviewer-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')");
        jdbc.update("INSERT INTO quality_issues VALUES ('ISSUE-T806-NOTDONE','TASK-T806-NOTDONE','COORDINATE_SYSTEM','OPEN','未完成生产')");
        jdbc.update("INSERT INTO rework_tasks VALUES ('REWORK-T806-NOTDONE','TASK-T806-NOTDONE','ISSUE-T806-NOTDONE','PENDING','不允许开始')");
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES ('REWORK-T806-NOTDONE','TASK-T806-NOTDONE','ISSUE-T806-NOTDONE',1,'reviewer-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')");
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status,version) VALUES ('TASK-T806-SNAPSHOT','ORDER-T806','COMPLETED',3)");
        jdbc.update("INSERT INTO quality_issues VALUES ('ISSUE-T806-SNAPSHOT','TASK-T806-SNAPSHOT','COORDINATE_SYSTEM','OPEN','快照隔离')");
        jdbc.update("INSERT INTO rework_tasks VALUES ('REWORK-T806-SNAPSHOT','TASK-T806-SNAPSHOT','ISSUE-T806-SNAPSHOT','PENDING','快照隔离')");
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES ('REWORK-T806-SNAPSHOT','TASK-T806-SNAPSHOT','ISSUE-T806-SNAPSHOT',1,'reviewer-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')");
    }

    @AfterAll
    void dropOwnedSchema() {
        jdbc.execute("DROP SCHEMA t806_rework_query CASCADE");
    }

    private void fixture(String suffix, String status, String issueStatus, boolean lifecycle) {
        jdbc.update("INSERT INTO quality_issues VALUES (?, 'TASK-T806','COORDINATE_SYSTEM',?,'独立查询夹具')", "ISSUE-T806-" + suffix, issueStatus);
        jdbc.update("INSERT INTO rework_tasks VALUES (?, 'TASK-T806',?,?, '固定返工原因')", "REWORK-T806-" + suffix, "ISSUE-T806-" + suffix, status);
        if (lifecycle) {
            jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,'TASK-T806',?,1,'reviewer-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')", "REWORK-T806-" + suffix, "ISSUE-T806-" + suffix);
        }
    }

    private void processing(String suffix, int revision) {
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,?, '成果-A','release-2','  保留处理说明  ',?::jsonb,'operator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')",
                "REWORK-T806-" + suffix, revision, "[\"report:处理-" + revision + "\"]");
    }

    private void inspection(String suffix, int revision, int sequence, String result) throws Exception {
        String items = mapper.writeValueAsString(List.of(Map.of("checkItem", "坐标系", "result", result,
                "comment", "保留检查记录", "evidenceReferences", List.of("report:check"))));
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,?,?,?,?::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')",
                "CHECK-T806-" + suffix + "-" + sequence, "REWORK-T806-" + suffix, revision, sequence, result, items);
    }

    private void review(String suffix, int sequence, String result) {
        jdbc.update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,1,?,?,?,'保留复核记录','reviewer-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')",
                "REVIEW-T806-" + suffix + "-" + sequence, "REWORK-T806-" + suffix,
                "CHECK-T806-" + suffix + "-1", sequence, result);
    }

    private ResponseEntity<JsonNode> request(String path, String actor, String role) {
        HttpHeaders headers = new HttpHeaders();
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        headers.set("X-Trace-Id", "trace-t806-query");
        return http.exchange(path, HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
    }

    private JsonNode detail(String suffix) {
        var response = request(ROOT + suffix, "reviewer-test", "REVIEWER");
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t806-query");
        JsonNode body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.size()).isEqualTo(6);
        assertThat(body.path("success").asBoolean()).isTrue();
        assertThat(body.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(body.path("retryable").asBoolean()).isFalse();
        assertThat(body.path("trace_id").asText()).isEqualTo("trace-t806-query");
        return body.path("data");
    }

    @Test
    void preservesLegacyAndMissingSourceAsExplicitNulls() {
        for (String suffix : List.of("LEGACY", "NOSOURCE")) {
            JsonNode data = detail(suffix);
            assertThat(data.path("reworkTask").size()).isEqualTo(5);
            assertThat(data.path("taskVersion").asLong()).isEqualTo(7);
            for (String field : List.of("roundNumber", "previousReworkTaskId", "processing", "inspection", "review")) {
                assertThat(data.has(field)).as(field).isTrue();
                assertThat(data.get(field).isNull()).as(field).isTrue();
            }
            assertThat(data.path("allowedActions")).isEmpty();
        }
        assertThat(detail("NOSOURCE").path("issueStatus").isNull()).isTrue();
    }

    @ParameterizedTest
    @CsvSource({"PENDING,START_REWORK", "BLOCKED,RESUME_REWORK", "FAILED,RESUME_REWORK",
            "PASSED,SUBMIT_REWORK_REVIEW", "REJECTED,CREATE_NEXT_REWORK"})
    void returnsActionsFromCurrentFacts(String suffix, String action) {
        JsonNode data = detail(suffix);
        assertThat(data.path("roundNumber").asInt()).isEqualTo(1);
        assertThat(data.path("allowedActions")).hasSize(1);
        assertThat(data.path("allowedActions").get(0).asText()).isEqualTo(action);
    }

    @Test
    void onlyAllowsInspectionAfterAResultAndPreservesStoredMaterial() {
        JsonNode empty = detail("RUNNING");
        assertThat(empty.path("allowedActions")).hasSize(3);
        assertThat(empty.path("processing").isNull()).isTrue();
        JsonNode recorded = detail("RESULT");
        assertThat(recorded.path("allowedActions")).hasSize(4);
        assertThat(recorded.path("allowedActions").get(3).asText()).isEqualTo("REGISTER_REWORK_INSPECTION");
        JsonNode processing = recorded.path("processing");
        assertThat(processing.path("artifact").path("artifactVersion").asText()).isEqualTo("release-2");
        assertThat(processing.path("processingComment").asText()).isEqualTo("  保留处理说明  ");
        assertThat(processing.path("evidenceReferences").get(0).asText()).isEqualTo("report:处理-1");
        assertThat(processing.path("registeredBy").asText()).isEqualTo("operator-test");
        assertThat(processing.path("registeredAt").asText()).isEqualTo("2026-11-09T00:00:00Z");
    }

    @Test
    void doesNotReuseChecksOrReviewsFromAnOldRevision() {
        JsonNode data = detail("NEWREVISION");
        assertThat(data.path("processing").path("processingRevision").asInt()).isEqualTo(2);
        assertThat(data.path("inspection").isNull()).isTrue();
        assertThat(data.path("review").isNull()).isTrue();
    }

    @Test
    void latestFailedCheckCannotBeSkippedForAnOlderPassedOne() {
        JsonNode data = detail("NEWFAILED");
        assertThat(data.path("inspection").path("inspectionSequence").asInt()).isEqualTo(2);
        assertThat(data.path("inspection").path("result").asText()).isEqualTo("FAILED");
        assertThat(data.path("review").isNull()).isTrue();
        assertThat(data.path("allowedActions")).isEmpty();
    }

    @Test
    void newPassedCheckInvalidatesOldReviewAndLatestReviewWinsWithinItsBinding() {
        assertThat(detail("NEWCHECK").path("review").isNull()).isTrue();
        JsonNode data = detail("NEWREVIEW");
        assertThat(data.path("review").path("reviewSequence").asInt()).isEqualTo(2);
        assertThat(data.path("review").path("status").asText()).isEqualTo("APPROVED");
        assertThat(data.path("allowedActions")).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {"ACTIVE", "PREVIOUS", "CLOSED"})
    void doesNotOfferAnotherRoundWhenActiveSuccessorOrClosed(String suffix) {
        assertThat(detail(suffix).path("allowedActions")).isEmpty();
    }

    @Test
    void returnsRealSuccessorAndBlocksActionsBeforeProductionCompletion() {
        JsonNode next = detail("NEXT");
        assertThat(next.path("roundNumber").asLong()).isEqualTo(2);
        assertThat(next.path("previousReworkTaskId").asText()).isEqualTo("REWORK-T806-PREVIOUS");
        var response = request("/api/tasks/TASK-T806-NOTDONE/reworks/REWORK-T806-NOTDONE", "reviewer-test", "REVIEWER");
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody().path("data").path("allowedActions")).isEmpty();
    }

    @Test
    void distinguishesMissingParentMissingReworkAndCrossTaskWithoutDetailLeak() {
        assertError(request("/api/tasks/TASK-MISSING/reworks/REWORK-T806-PENDING", "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        assertError(request(ROOT + "MISSING", "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        assertError(request("/api/tasks/TASK-003/reworks/REWORK-T806-PENDING", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
    }

    @Test
    void authorizesBeforeLookingUpResourcesAndRejectsInvalidIds() {
        assertError(request(ROOT + "MISSING", null, "REVIEWER"), 401, "PERMISSION_DENIED");
        assertError(request(ROOT + "PENDING", "reviewer-test", null), 403, "PERMISSION_DENIED");
        assertError(request(ROOT + "PENDING", "reviewer-test", "ADMIN"), 403, "PERMISSION_DENIED");
        assertError(request(ROOT + "PENDING", "x".repeat(129), "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        assertError(request("/api/tasks/task-lower/reworks/REWORK-T806-PENDING", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        assertError(request(ROOT + "a".repeat(65), "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> service.getDetail("TASK-T806", "REWORK-T806-PENDING", "bad\nactor", "REVIEWER"))
                .isInstanceOf(com.productline.business.api.error.InvalidRequestException.class);
    }

    @Test
    void queryDoesNotMutateFactsAndOldOverviewAndGoldenChainRemainUnchanged() {
        Map<String, Object> before = counts();
        detail("PASSED");
        detail("REJECTED");
        assertThat(counts()).isEqualTo(before);
        var response = http.getForEntity("/api/orders/ORDER-003/overview", JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        JsonNode golden = response.getBody().path("data");
        assertThat(golden.path("tasks").get(0).path("task").path("version").asLong()).isZero();
        assertThat(jdbc.queryForObject("SELECT status FROM production_tasks WHERE task_id='TASK-003'", String.class)).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("SELECT status FROM quality_issues WHERE issue_id='ISSUE-001'", String.class)).isEqualTo("OPEN");
        assertThat(jdbc.queryForObject("SELECT status FROM review_records WHERE review_id='REVIEW-003'", String.class)).isEqualTo("PENDING");
    }

    private Map<String, Object> counts() {
        return jdbc.queryForMap("SELECT (SELECT count(*) FROM rework_lifecycles) AS rounds,(SELECT count(*) FROM rework_processing_revisions) AS revisions,(SELECT count(*) FROM rework_inspections) AS checks,(SELECT count(*) FROM rework_reviews) AS reviews,(SELECT count(*) FROM rework_operation_receipts) AS receipts,(SELECT count(*) FROM operation_logs) AS logs,(SELECT version FROM production_tasks WHERE task_id='TASK-T806') AS version");
    }

    @Test
    void readsOneSnapshotDespiteAnIndependentCommitBetweenQueries() {
        var interleaved = new ReworkReadRepository(jdbc, mapper) {
            @Override
            public boolean taskExists(String taskId) {
                boolean exists = super.taskExists(taskId);
                assertThat(jdbc.queryForObject("SHOW transaction_isolation", String.class)).isEqualTo("repeatable read");
                assertThat(jdbc.queryForObject("SHOW transaction_read_only", String.class)).isEqualTo("on");
                // 独立JDBC事务只修改本测试专用资源，不把材料快照验证称作HTTP并发测试。
                try (Connection connection = dataSource.getConnection(); Statement statement = connection.createStatement()) {
                    connection.setAutoCommit(false);
                    statement.executeUpdate("UPDATE production_tasks SET version=4 WHERE task_id='TASK-T806-SNAPSHOT'");
                    statement.executeUpdate("UPDATE quality_issues SET status='PROCESSING' WHERE issue_id='ISSUE-T806-SNAPSHOT'");
                    statement.executeUpdate("UPDATE rework_tasks SET status='RUNNING' WHERE rework_task_id='REWORK-T806-SNAPSHOT'");
                    connection.commit();
                } catch (Exception exception) {
                    throw new AssertionError("independent snapshot fixture commit failed", exception);
                }
                return exists;
            }
        };
        var response = new ReworkQueryService(interleaved, transactionManager).getDetail(
                "TASK-T806-SNAPSHOT", "REWORK-T806-SNAPSHOT", "reviewer-test", "REVIEWER");
        assertThat(response.taskVersion()).isEqualTo(3);
        assertThat(response.reworkTask().status().name()).isEqualTo("PENDING");
        assertThat(response.issueStatus().name()).isEqualTo("OPEN");
        var current = request("/api/tasks/TASK-T806-SNAPSHOT/reworks/REWORK-T806-SNAPSHOT", "reviewer-test", "REVIEWER");
        assertThat(current.getStatusCode().value()).isEqualTo(200);
        assertThat(current.getBody().path("data").path("taskVersion").asLong()).isEqualTo(4);
        assertThat(current.getBody().path("data").path("reworkTask").path("status").asText()).isEqualTo("RUNNING");
    }

    private void assertError(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("success").asBoolean()).isFalse();
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().path("data").isNull()).isTrue();
        assertThat(response.getBody().toString()).doesNotContain("artifactId", "processingComment", "evidenceReferences");
    }
}
