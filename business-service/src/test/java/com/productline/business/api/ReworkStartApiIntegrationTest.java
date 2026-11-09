package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkStartRequest;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.application.ReworkStartService;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
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
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;

/** 仅在独占schema中验证开始HTTP、原回执重放、真实并发及整笔回滚。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t807_rework_start", "spring.flyway.default-schema=t807_rework_start",
        "spring.datasource.hikari.schema=t807_rework_start",
        "spring.jpa.properties.hibernate.default_schema=t807_rework_start"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkStartApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private ReworkStartService service;
    private Map<String, Object> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T807','DOM','QUALITY_CHECKING')");
        fixture("INVALID", "COMPLETED", "PENDING", "OPEN", true);
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
        } finally {
            jdbc.execute("DROP SCHEMA t807_rework_start CASCADE");
        }
    }

    private void fixture(String suffix, String taskStatus, String reworkStatus, String issueStatus, boolean lifecycle) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T807',?)", task(suffix), taskStatus);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM',?,'T807独立问题')", issue(suffix), task(suffix), issueStatus);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?, 'T807固定原因')", rework(suffix), task(suffix), issue(suffix), reworkStatus);
        if (lifecycle) {
            jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')", rework(suffix), task(suffix), issue(suffix));
        }
    }

    private String task(String suffix) { return "TASK-T807-" + suffix; }
    private String rework(String suffix) { return "REWORK-T807-" + suffix; }
    private String issue(String suffix) { return "ISSUE-T807-" + suffix; }
    private String path(String suffix) { return "/api/tasks/" + task(suffix) + "/reworks/" + rework(suffix) + "/start"; }

    private ResponseEntity<JsonNode> post(String path, String body, String key, String actor, String role) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Trace-Id", "trace-t807-start");
        if (key != null) headers.set("Idempotency-Key", key);
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        return http.exchange(path, HttpMethod.POST, new HttpEntity<>(body, headers), JsonNode.class);
    }

    private ResponseEntity<JsonNode> start(String suffix, String key) {
        return post(path(suffix), "{\"expectedVersion\":0}", key, "reviewer-test", "REVIEWER");
    }

    private JsonNode success(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t807-start");
        JsonNode body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.size()).isEqualTo(6);
        assertThat(body.path("success").asBoolean()).isTrue();
        assertThat(body.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(body.path("retryable").asBoolean()).isFalse();
        assertThat(body.path("trace_id").asText()).isEqualTo("trace-t807-start");
        JsonNode data = body.path("data");
        assertThat(data.size()).isEqualTo(12);
        assertThat(data.path("operation").asText()).isEqualTo("START_REWORK");
        assertThat(data.path("operationId").asText()).matches("^OPERATION-[A-Z0-9-]+$");
        assertThat(data.path("status").asText()).isEqualTo("RUNNING");
        assertThat(data.path("issueStatus").asText()).isEqualTo("PROCESSING");
        return data;
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        JsonNode body = response.getBody();
        assertThat(body.path("code").asText()).isEqualTo(code);
        assertThat(body.path("success").asBoolean()).isFalse();
        assertThat(body.path("retryable").asBoolean()).isFalse();
        assertThat(body.path("data").isNull()).isTrue();
        assertThat(body.toString()).doesNotContain("started_by", "request_hash", "response_data");
    }

    private Map<String, Object> state(String suffix) {
        return jdbc.queryForMap("SELECT t.status AS task_status,t.version,r.status AS rework_status,q.status AS issue_status,l.started_by,l.started_at FROM production_tasks t JOIN rework_tasks r ON r.task_id=t.task_id JOIN quality_issues q ON q.issue_id=r.source_issue_id LEFT JOIN rework_lifecycles l ON l.rework_task_id=r.rework_task_id WHERE r.rework_task_id=?", rework(suffix));
    }

    private int countKey(String table, String key) {
        return jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE idempotency_key=?", Integer.class, key);
    }

    private int auditCount(String key) {
        return jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')", Integer.class, key);
    }

    private void absent(String key) {
        assertThat(countKey("idempotency_records", key)).isZero();
        assertThat(countKey("rework_operation_receipts", key)).isZero();
        assertThat(auditCount(key)).isZero();
    }

    @Test
    void startsAtomicallyWithServerActorTimeVersionAuditAndFixedReceipt() throws Exception {
        fixture("SUCCESS", "COMPLETED", "PENDING", "OPEN", true);
        Instant before = Instant.now();
        JsonNode data = success(start("SUCCESS", "t807-success"));
        Instant after = Instant.now();
        assertThat(data.path("taskVersion").asLong()).isEqualTo(1);
        assertThat(data.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(data.path("taskId").asText()).isEqualTo(task("SUCCESS"));
        assertThat(data.path("reworkTaskId").asText()).isEqualTo(rework("SUCCESS"));
        for (String field : List.of("previousReworkTaskId", "processingRevision", "inspectionId", "reviewId")) {
            assertThat(data.has(field)).as(field).isTrue();
            assertThat(data.get(field).isNull()).as(field).isTrue();
        }
        Map<String, Object> state = state("SUCCESS");
        assertThat(state).containsEntry("task_status", "COMPLETED").containsEntry("version", 1L)
                .containsEntry("rework_status", "RUNNING").containsEntry("issue_status", "PROCESSING")
                .containsEntry("started_by", "reviewer-test");
        Instant started = ((java.sql.Timestamp) state.get("started_at")).toInstant();
        assertThat(started).isBetween(before.minusSeconds(1), after.plusSeconds(1));
        assertThat(countKey("idempotency_records", "t807-success")).isEqualTo(1);
        assertThat(auditCount("t807-success")).isEqualTo(1);
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key='t807-success'", String.class))).isEqualTo(data);
        var audit = jdbc.queryForMap("SELECT before_state,after_state,target_type,target_id FROM operation_logs WHERE operation_id=?", data.path("operationId").asText());
        assertThat(audit).containsEntry("target_type", "PRODUCTION_TASK").containsEntry("target_id", task("SUCCESS"));
        assertThat(audit.get("before_state").toString()).contains("PENDING", "OPEN").doesNotContain("t807-success");
        assertThat(audit.get("after_state").toString()).contains("RUNNING", "PROCESSING").doesNotContain("t807-success");
    }

    @Test
    void replayReturnsOriginalReceiptAfterLaterStateAndVersionChanges() {
        fixture("REPLAY", "COMPLETED", "PENDING", "OPEN", true);
        JsonNode original = success(start("REPLAY", "t807-replay"));
        Object startedAt = state("REPLAY").get("started_at");
        jdbc.update("UPDATE rework_tasks SET status='BLOCKED' WHERE rework_task_id=?", rework("REPLAY"));
        jdbc.update("UPDATE production_tasks SET version=2 WHERE task_id=?", task("REPLAY"));
        assertThat(success(post(path("REPLAY"), "{ \"expectedVersion\" : 0 }", "t807-replay", "reviewer-test", "REVIEWER"))).isEqualTo(original);
        assertThat(state("REPLAY")).containsEntry("rework_status", "BLOCKED").containsEntry("version", 2L)
                .containsEntry("started_at", startedAt);
        assertThat(auditCount("t807-replay")).isEqualTo(1);
    }

    @Test
    void rejectsKeyReuseByOtherActorTargetVersionOrOperation() {
        fixture("BIND", "COMPLETED", "PENDING", "OPEN", true);
        fixture("OTHER", "COMPLETED", "PENDING", "OPEN", true);
        success(start("BIND", "t807-bind"));
        error(post(path("BIND"), "{\"expectedVersion\":0}", "t807-bind", "other-reviewer", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(post(path("BIND"), "{\"expectedVersion\":1}", "t807-bind", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(start("OTHER", "t807-bind"), 409, "BUSINESS_CONFLICT");
        error(post(path("BIND"), "{\"expectedVersion\":0}", "t807-bind", "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        jdbc.update("INSERT INTO idempotency_records(idempotency_key,operation_type,request_hash,actor_user_id) VALUES ('t807-legacy-op','CREATE_REWORK','legacy','reviewer-test')");
        error(start("OTHER", "t807-legacy-op"), 409, "BUSINESS_CONFLICT");
        assertThat(state("OTHER")).containsEntry("version", 0L).containsEntry("rework_status", "PENDING");
        assertThat(auditCount("t807-bind")).isEqualTo(1);
        assertThat(countKey("rework_operation_receipts", "t807-legacy-op")).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "null", "[]", "{}", "{not-json}",
            "{\"expectedVersion\":null}", "{\"expectedVersion\":\"0\"}",
            "{\"expectedVersion\":true}", "{\"expectedVersion\":0.0}",
            "{\"expectedVersion\":-1}", "{\"expectedVersion\":9007199254740992}",
            "{\"expectedVersion\":999999999999999999999999}",
            "{\"expectedVersion\":0,\"confirmed\":true}",
            "{\"expectedVersion\":0,\"role\":\"REVIEWER\"}",
            "{\"expectedVersion\":0,\"startedBy\":\"forged\"}",
            "{\"expectedVersion\":0,\"startedAt\":\"2026-01-01T00:00:00Z\"}",
            "{\"expectedVersion\":0,\"status\":\"RUNNING\"}",
            "{\"expectedVersion\":0,\"taskId\":\"TASK-FORGED\"}",
            "{\"expectedVersion\":0,\"expectedVersion\":0}",
            "{\"expectedVersion\":0} {\"expectedVersion\":0}"})
    void rejectsMalformedOrSelfReportedFieldsWithoutReservation(String body) {
        error(post(path("INVALID"), body, "t807-invalid-input", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        absent("t807-invalid-input");
        assertThat(state("INVALID")).containsEntry("version", 0L).containsEntry("rework_status", "PENDING");
    }

    @Test
    void rejectsMissingIdentityRoleKeyUnsafeHeadersAndInvalidPathsBeforeWriting() {
        error(post(path("INVALID"), "{\"expectedVersion\":0}", "t807-auth", null, "REVIEWER"), 401, "PERMISSION_DENIED");
        error(post(path("INVALID"), "{\"expectedVersion\":0}", "t807-auth", "reviewer-test", null), 403, "PERMISSION_DENIED");
        error(post(path("INVALID"), "{\"expectedVersion\":0}", "t807-auth", "reviewer-test", "ADMIN"), 403, "PERMISSION_DENIED");
        error(post(path("INVALID"), "{\"expectedVersion\":0}", "t807-auth", "x".repeat(129), "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        for (String key : new String[]{null, "bad key", "x".repeat(129)}) {
            error(post(path("INVALID"), "{\"expectedVersion\":0}", key, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        }
        error(post("/api/tasks/task-invalid/reworks/REWORK-T807-INVALID/start", "{\"expectedVersion\":0}", "t807-auth", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> service.start(task("INVALID"), rework("INVALID"), "bad\nactor", "REVIEWER", "t807-auth", new ReworkStartRequest(0)))
                .isInstanceOf(InvalidRequestException.class);
        absent("t807-auth");
    }

    @Test
    void rejectsNonJsonContentTypeWithoutWriting() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.TEXT_PLAIN);
        headers.set("X-User-Id", "reviewer-test");
        headers.set("X-User-Role", "REVIEWER");
        headers.set("Idempotency-Key", "t807-media");
        error(http.exchange(path("INVALID"), HttpMethod.POST, new HttpEntity<>("{\"expectedVersion\":0}",headers), JsonNode.class), 400, "PARAM_VALIDATION_ERROR");
        absent("t807-media");
    }

    @Test
    void distinguishesMissingResourcesAndWrongTaskWithoutLeavingReservations() {
        error(start("MISSING", "t807-missing-parent"), 404, "RESOURCE_NOT_FOUND");
        error(post("/api/tasks/" + task("INVALID") + "/reworks/REWORK-MISSING/start", "{\"expectedVersion\":0}", "t807-missing-rework", "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        error(post("/api/tasks/TASK-003/reworks/" + rework("INVALID") + "/start", "{\"expectedVersion\":0}", "t807-owner", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        for (String key : List.of("t807-missing-parent", "t807-missing-rework", "t807-owner")) absent(key);
    }

    @ParameterizedTest
    @CsvSource({"TASKRUNNING,RUNNING,PENDING,OPEN", "TASKFAILED,FAILED,PENDING,OPEN",
            "REWORKRUNNING,COMPLETED,RUNNING,OPEN", "REWORKBLOCKED,COMPLETED,BLOCKED,OPEN",
            "REWORKFAILED,COMPLETED,FAILED,OPEN", "REWORKDONE,COMPLETED,COMPLETED,OPEN",
            "ISSUEPROCESSING,COMPLETED,PENDING,PROCESSING", "ISSUERESOLVED,COMPLETED,PENDING,RESOLVED",
            "ISSUECLOSED,COMPLETED,PENDING,CLOSED"})
    void rejectsIllegalStatesAndLeavesAllFactsUnchanged(String suffix, String taskStatus, String reworkStatus, String issueStatus) {
        fixture(suffix, taskStatus, reworkStatus, issueStatus, true);
        var before = state(suffix);
        String key = "t807-state-" + suffix;
        error(start(suffix, key), 409, "BUSINESS_CONFLICT");
        assertThat(state(suffix)).isEqualTo(before);
        absent(key);
    }

    @Test
    void rejectsLegacyMissingSourceAlreadyStartedAndSuccessorWithoutBackfill() {
        fixture("LEGACY", "COMPLETED", "PENDING", "OPEN", false);
        error(start("LEGACY", "t807-legacy"), 409, "BUSINESS_CONFLICT");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_lifecycles WHERE rework_task_id=?", Integer.class, rework("LEGACY"))).isZero();
        fixture("NOSOURCE", "COMPLETED", "PENDING", "OPEN", false);
        jdbc.update("UPDATE rework_tasks SET source_issue_id=NULL WHERE rework_task_id=?", rework("NOSOURCE"));
        error(start("NOSOURCE", "t807-nosource"), 409, "BUSINESS_CONFLICT");
        fixture("STARTED", "COMPLETED", "PENDING", "OPEN", true);
        jdbc.update("UPDATE rework_lifecycles SET started_by='original-user',started_at=TIMESTAMPTZ '2026-11-09 00:00:00+00' WHERE rework_task_id=?", rework("STARTED"));
        var started = state("STARTED");
        error(start("STARTED", "t807-started"), 409, "BUSINESS_CONFLICT");
        assertThat(state("STARTED")).isEqualTo(started);
        fixture("PREVIOUS", "COMPLETED", "PENDING", "OPEN", true);
        jdbc.update("INSERT INTO rework_tasks VALUES ('REWORK-T807-NEXT',?,?,'PENDING','后继夹具')", task("PREVIOUS"), issue("PREVIOUS"));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES ('REWORK-T807-NEXT',?,?,2,?,1,'creator-test',CURRENT_TIMESTAMP)",task("PREVIOUS"),issue("PREVIOUS"),rework("PREVIOUS"));
        error(start("PREVIOUS", "t807-predecessor"), 409, "BUSINESS_CONFLICT");
        for (String key : List.of("t807-legacy", "t807-nosource", "t807-started", "t807-predecessor")) absent(key);
    }

    @Test
    void rejectsStaleAndExhaustedVersionsWithoutOverflow() {
        fixture("STALE", "COMPLETED", "PENDING", "OPEN", true);
        jdbc.update("UPDATE production_tasks SET version=2 WHERE task_id=?", task("STALE"));
        error(start("STALE", "t807-stale"), 409, "BUSINESS_CONFLICT");
        fixture("EXHAUSTED", "COMPLETED", "PENDING", "OPEN", true);
        jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?", task("EXHAUSTED"));
        error(post(path("EXHAUSTED"), "{\"expectedVersion\":9007199254740991}", "t807-exhausted", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        assertThat(state("EXHAUSTED")).containsEntry("version", 9007199254740991L).containsEntry("rework_status", "PENDING");
        absent("t807-stale");
        absent("t807-exhausted");
    }

    @Test
    void acceptsSafeHeaderLimitsAndLastIncrementableVersion() {
        fixture("LIMITS", "COMPLETED", "PENDING", "OPEN", true);
        jdbc.update("UPDATE production_tasks SET version=9007199254740990 WHERE task_id=?", task("LIMITS"));
        String actor = "a".repeat(128);
        String key = "k".repeat(128);
        JsonNode receipt = success(post(path("LIMITS"), "{\"expectedVersion\":9007199254740990}", key, actor, "REVIEWER"));
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(9007199254740991L);
        assertThat(state("LIMITS")).containsEntry("started_by", actor).containsEntry("task_status", "COMPLETED");
    }

    @Test
    void rollsBackVersionStatesStartMetadataReservationAndAuditWhenReceiptInsertFails() {
        fixture("ROLLBACK", "COMPLETED", "PENDING", "OPEN", true);
        jdbc.execute("CREATE FUNCTION t807_fail_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced receipt failure'; END $$");
        jdbc.execute("CREATE TRIGGER t807_fail_receipt BEFORE INSERT ON rework_operation_receipts FOR EACH ROW EXECUTE FUNCTION t807_fail_receipt()");
        var before = state("ROLLBACK");
        try {
            error(start("ROLLBACK", "t807-rollback"), 500, "INTERNAL_SERVER_ERROR");
            assertThat(state("ROLLBACK")).isEqualTo(before);
            absent("t807-rollback");
        } finally {
            jdbc.execute("DROP TRIGGER t807_fail_receipt ON rework_operation_receipts");
            jdbc.execute("DROP FUNCTION t807_fail_receipt()");
        }
        success(start("ROLLBACK", "t807-rollback"));
        assertThat(auditCount("t807-rollback")).isEqualTo(1);
    }

    @Test
    void concurrentSameKeyReturnsOneOriginalReceiptAndOneWrite() throws Exception {
        fixture("SAMEKEY", "COMPLETED", "PENDING", "OPEN", true);
        var responses = concurrently("SAMEKEY", "t807-same", "t807-same");
        assertThat(success(responses.get(0))).isEqualTo(success(responses.get(1)));
        assertThat(state("SAMEKEY")).containsEntry("version", 1L);
        assertThat(countKey("rework_operation_receipts", "t807-same")).isEqualTo(1);
        assertThat(auditCount("t807-same")).isEqualTo(1);
    }

    @Test
    void concurrentDifferentKeysWithOneVersionHaveOneSuccessAndOneConflict() throws Exception {
        fixture("DIFFKEY", "COMPLETED", "PENDING", "OPEN", true);
        var responses = concurrently("DIFFKEY", "t807-diff-a", "t807-diff-b");
        assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200,409);
        assertThat(state("DIFFKEY")).containsEntry("version", 1L);
        assertThat(countKey("rework_operation_receipts", "t807-diff-a") + countKey("rework_operation_receipts", "t807-diff-b")).isEqualTo(1);
        assertThat(auditCount("t807-diff-a") + auditCount("t807-diff-b")).isEqualTo(1);
        for (int i=0; i<2; i++) {
            if (responses.get(i).getStatusCode().value() == 409) {
                error(responses.get(i),409,"BUSINESS_CONFLICT");
                absent(i == 0 ? "t807-diff-a" : "t807-diff-b");
            }
        }
    }

    private List<ResponseEntity<JsonNode>> concurrently(String suffix, String firstKey, String secondKey) throws Exception {
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch go = new CountDownLatch(1);
        try (var executor = Executors.newFixedThreadPool(2)) {
            var first = executor.submit(() -> { ready.countDown(); go.await(); return start(suffix,firstKey); });
            var second = executor.submit(() -> { ready.countDown(); go.await(); return start(suffix,secondKey); });
            assertThat(ready.await(10,TimeUnit.SECONDS)).isTrue();
            go.countDown();
            return List.of(first.get(30,TimeUnit.SECONDS),second.get(30,TimeUnit.SECONDS));
        }
    }

    private Map<String,Object> golden() {
        return jdbc.queryForMap("SELECT (SELECT status FROM production_tasks WHERE task_id='TASK-003') AS task_status,(SELECT version FROM production_tasks WHERE task_id='TASK-003') AS version,(SELECT status FROM quality_issues WHERE issue_id='ISSUE-001') AS issue_status,(SELECT status FROM review_records WHERE review_id='REVIEW-003') AS review_status,(SELECT status FROM delivery_records WHERE order_id='ORDER-003' ORDER BY delivery_id LIMIT 1) AS delivery_status");
    }
}
