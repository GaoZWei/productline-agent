package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
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

/** 受控首轮及后继创建独立验收；HTTP链路不把下一轮SQL夹具当作创建成功。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t819_creation", "spring.flyway.default-schema=t819_creation",
        "spring.datasource.hikari.schema=t819_creation", "spring.jpa.properties.hibernate.default_schema=t819_creation"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkCreationApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private DataSource dataSource;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T819','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T819','ORDER-T819','BLOCKED')");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T819'", String.class)).isEqualTo("QUALITY_CHECKING");
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T819'", String.class)).isEqualTo("BLOCKED");
        } finally { jdbc.execute("DROP SCHEMA t819_creation CASCADE"); }
    }

    private String task(String id) { return "TASK-T819-" + id; }
    private String issue(String id) { return "ISSUE-T819-" + id; }
    private String rework(String id) { return "REWORK-T819-" + id; }
    private String path(String id) { return "/api/tasks/" + task(id) + "/reworks"; }
    private String key(String id) { return "t819-" + id; }
    private String tag(String text) { return text.replace('_', '-').toUpperCase(Locale.ROOT); }
    private ObjectNode body(String id, long version) {
        return mapper.createObjectNode().put("sourceIssueId", issue(id)).put("expectedVersion", version).put("reason", "  明确创建新轮的原因🚀  ");
    }
    private ObjectNode nextBody(long version) { return mapper.createObjectNode().put("expectedVersion", version).put("reason", "  另行确认后再次处理🚀  "); }

    private void open(String id) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T819','COMPLETED')", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','受控创建问题')", issue(id), task(id));
    }

    private void returned(String id) {
        open(id);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','原始首轮原因')", rework(id), task(id), issue(id));
        jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at)
                VALUES (?,?,?,1,'first-creator',TIMESTAMPTZ '2026-11-10 00:00:00+00','first-handler',TIMESTAMPTZ '2026-11-10 00:01:00+00')
                """, rework(id), task(id), issue(id));
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,1,'成果-A','release-1','真实原处理','[\"report:first\"]','handler-test',now())", rework(id));
        inspection(id, 1, 1, "PASSED");
        review(id, 1, 1, "CHECK-T819-" + id + "-1", "REWORK_REQUIRED");
    }

    private void inspection(String id, int revision, int seq, String result) {
        String items = "[{\"checkItem\":\"坐标系\",\"result\":\"" + result + "\",\"comment\":\"人工检查\",\"evidenceReferences\":[\"report:check\"]}]";
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,?, ?,?,?::jsonb,'inspector-test',now())",
                "CHECK-T819-" + id + "-" + seq, rework(id), revision, seq, result, items);
    }
    private void review(String id, int revision, int sequence, String inspectionId, String status) {
        jdbc.update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,?,?,'reviewer-test',now())", "REVIEW-T819-" + id + "-" + sequence,
                rework(id), revision, inspectionId, sequence, status, "原始退回意见");
    }

    private ResponseEntity<JsonNode> post(String url, Object body, String key, String actor, String role, MediaType type) {
        var headers = new HttpHeaders(); if (type != null) headers.setContentType(type);
        headers.set("X-Trace-Id", "trace-t819");
        if (key != null) headers.set("Idempotency-Key", key);
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        return http.exchange(url, HttpMethod.POST, new HttpEntity<>(body == null ? null : body.toString(), headers), JsonNode.class);
    }
    private ResponseEntity<JsonNode> post(String url, Object body, String key) { return post(url, body, key, "reviewer-test", "REVIEWER", MediaType.APPLICATION_JSON); }
    private ResponseEntity<JsonNode> create(String id, String key) { return post(path(id), body(id, 0), key); }
    private ResponseEntity<JsonNode> next(String id, String key) { return post(path(id) + "/" + rework(id) + "/next-round", nextBody(0), key); }
    private JsonNode get(String url) {
        var headers = new HttpHeaders(); headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER");
        var response = http.exchange(url, HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200); return response.getBody().path("data");
    }
    private JsonNode ok(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        var envelope = response.getBody(); assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue(); assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse(); assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t819");
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t819"); return envelope.path("data");
    }
    private JsonNode created(ResponseEntity<JsonNode> response, long round, String previous) {
        var receipt = ok(response); assertThat(receipt.size()).isEqualTo(12);
        assertThat(receipt.path("operation").asText()).isEqualTo(round == 1 ? "CREATE_LIFECYCLE_REWORK" : "CREATE_NEXT_REWORK");
        assertThat(receipt.path("operationId").asText()).matches("^OPERATION-[A-Z0-9-]+$");
        assertThat(receipt.path("reworkTaskId").asText()).matches("^REWORK-[A-Z0-9-]+$");
        assertThat(receipt.path("status").asText()).isEqualTo("PENDING"); assertThat(receipt.path("issueStatus").asText()).isEqualTo("OPEN");
        assertThat(receipt.path("roundNumber").asLong()).isEqualTo(round);
        if (previous == null) assertThat(receipt.path("previousReworkTaskId").isNull()).isTrue();
        else assertThat(receipt.path("previousReworkTaskId").asText()).isEqualTo(previous);
        for (String field : List.of("processingRevision", "inspectionId", "reviewId")) assertThat(receipt.path(field).isNull()).isTrue();
        return receipt;
    }
    private void error(ResponseEntity<JsonNode> response, int status) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(switch (status) {
            case 400 -> "PARAM_VALIDATION_ERROR"; case 401, 403 -> "PERMISSION_DENIED";
            case 404 -> "RESOURCE_NOT_FOUND"; case 409 -> "BUSINESS_CONFLICT"; default -> "INTERNAL_SERVER_ERROR";
        });
        assertThat(response.getBody().path("data").isNull()).isTrue(); assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
    }
    private List<String> facts() {
        return Stream.of("production_orders", "delivery_records", "production_tasks", "quality_issues", "rework_tasks", "rework_lifecycles",
                "rework_processing_revisions", "rework_inspections", "rework_reviews", "review_records", "idempotency_records", "operation_logs", "rework_operation_receipts")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + table + " r ORDER BY to_jsonb(r)::text", String.class).stream()).toList();
    }
    private List<String> evidence(String reworkId) {
        return Stream.of("rework_tasks", "rework_lifecycles", "rework_processing_revisions", "rework_inspections", "rework_reviews")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + table + " r WHERE rework_task_id=? ORDER BY to_jsonb(r)::text", String.class, reworkId).stream()).toList();
    }
    private void absent(String key) {
        for (String table : List.of("idempotency_records", "rework_operation_receipts")) assertThat(jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE idempotency_key=?", Integer.class, key)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')", Integer.class, key)).isZero();
    }

    @Test
    void firstRoundStoresRealIdentityRawReasonAndOriginalReceiptAfterStart() throws Exception {
        String id = "FIRST"; open(id); Instant earliest = Instant.now(); var payload = body(id, 0);
        var receipt = created(create(id, key(id)), 1, null); Instant latest = Instant.now();
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(1); String reworkId = receipt.path("reworkTaskId").asText();
        var lifecycle = jdbc.queryForMap("SELECT * FROM rework_lifecycles WHERE rework_task_id=?", reworkId);
        assertThat(lifecycle).containsEntry("created_by", "reviewer-test").containsEntry("round_number", 1L)
                .containsEntry("started_by", null).containsEntry("started_at", null).containsEntry("previous_rework_task_id", null);
        assertThat(((java.sql.Timestamp) lifecycle.get("created_at")).toInstant()).isBetween(earliest, latest);
        assertThat(jdbc.queryForObject("SELECT reason FROM rework_tasks WHERE rework_task_id=?", String.class, reworkId)).isEqualTo(payload.path("reason").asText());
        var detail = get(path(id) + "/" + reworkId); assertThat(detail.path("allowedActions").get(0).asText()).isEqualTo("START_REWORK");
        for (String field : List.of("processing", "inspection", "review")) assertThat(detail.path(field).isNull()).isTrue();
        var audit = jdbc.queryForMap("SELECT * FROM operation_logs WHERE operation_id=?", receipt.path("operationId").asText());
        assertThat(audit).containsEntry("actor_user_id", "reviewer-test");
        assertThat(mapper.readTree(audit.get("after_state").toString()).path("reason").asText()).isEqualTo(payload.path("reason").asText());
        ok(post(path(id) + "/" + reworkId + "/start", mapper.createObjectNode().put("expectedVersion", 1), key(id) + "-start"));
        var before = facts(); assertThat(created(create(id, key(id)), 1, null)).isEqualTo(receipt); assertThat(facts()).isEqualTo(before);
        error(post(path(id), body(id, 2), key(id) + "-duplicate"), 409); absent(key(id) + "-duplicate");
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key=?", String.class, key(id)))).isEqualTo(receipt);
    }

    private JsonNode finishRound(String id, JsonNode creation, String conclusion, String suffix) {
        long version = creation.path("taskVersion").asLong(); String base = path(id) + "/" + creation.path("reworkTaskId").asText();
        ok(post(base + "/start", mapper.createObjectNode().put("expectedVersion", version), key(id) + suffix + "-start"));
        var material = mapper.createObjectNode().put("expectedVersion", version + 1).put("processingComment", "实际处理说明");
        material.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "release-" + suffix);
        material.putArray("evidenceReferences").add("report:" + suffix);
        ok(post(base + "/results", material, key(id) + suffix + "-result"));
        var inspection = mapper.createObjectNode().put("expectedVersion", version + 2).put("processingRevision", 1);
        inspection.putArray("items").addObject().put("checkItem", "坐标系").put("result", "PASSED").put("comment", "实际人工检查")
                .putArray("evidenceReferences").add("report:check-" + suffix);
        var checked = ok(post(base + "/inspections", inspection, key(id) + suffix + "-inspection"));
        var review = mapper.createObjectNode().put("expectedVersion", version + 3).put("processingRevision", 1)
                .put("inspectionId", checked.path("inspectionId").asText()).put("status", conclusion).put("reviewComment", "原始意见-" + suffix);
        return ok(post(base + "/review", review, key(id) + suffix + "-review"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void twoRoundsUseOnlyHttpAndDoNotInheritEvidenceOrReopenAfterOriginalReplay(String conclusion) throws Exception {
        String id = "FLOW-" + tag(conclusion); open(id);
        var first = created(create(id, key(id)), 1, null); String firstId = first.path("reworkTaskId").asText();
        var returned = finishRound(id, first, conclusion, "first"); assertThat(returned.path("issueStatus").asText()).isEqualTo("OPEN");
        var oldEvidence = evidence(firstId);
        String nextPath = path(id) + "/" + firstId + "/next-round"; var payload = nextBody(5);
        var second = created(post(nextPath, payload, key(id) + "-next"), 2, firstId); assertThat(second.path("taskVersion").asLong()).isEqualTo(6);
        String secondId = second.path("reworkTaskId").asText(); assertThat(evidence(firstId)).isEqualTo(oldEvidence);
        var effective = get("/api/tasks/" + task(id) + "/effective-reviews").path("issues").get(0);
        assertThat(effective.path("reworkTaskId").asText()).isEqualTo(secondId); assertThat(effective.path("roundNumber").asLong()).isEqualTo(2);
        for (String field : List.of("processingRevision", "inspectionId", "review")) assertThat(effective.path(field).isNull()).isTrue();
        var audit = jdbc.queryForMap("SELECT after_state FROM operation_logs WHERE operation_id=?", second.path("operationId").asText());
        var after = mapper.readTree(audit.get("after_state").toString()); assertThat(after.path("previousReviewId").asText()).isEqualTo(returned.path("reviewId").asText());
        assertThat(after.path("previousReviewStatus").asText()).isEqualTo(conclusion); assertThat(after.path("previousReviewComment").asText()).isEqualTo("原始意见-first");
        var approved = finishRound(id, second, "APPROVED", "second"); assertThat(approved.path("taskVersion").asLong()).isEqualTo(10);
        assertThat(approved.path("issueStatus").asText()).isEqualTo("CLOSED");
        var before = facts(); assertThat(created(create(id, key(id)), 1, null)).isEqualTo(first);
        assertThat(created(post(nextPath, payload, key(id) + "-next"), 2, firstId)).isEqualTo(second); assertThat(facts()).isEqualTo(before);
        assertThat(evidence(firstId)).isEqualTo(oldEvidence);
        assertThat(get("/api/tasks/" + task(id) + "/effective-reviews").path("issues").get(0).path("review").path("status").asText()).isEqualTo("APPROVED");
        assertThat(get(path(id) + "/" + firstId + "/reviews").path("records").get(0).path("status").asText()).isEqualTo(conclusion);
        assertThat(get(path(id) + "/" + secondId + "/reviews").path("records").get(0).path("status").asText()).isEqualTo("APPROVED");
        error(post(nextPath, nextBody(10), key(id) + "-third-from-old"), 409); absent(key(id) + "-third-from-old");
        assertThat(jdbc.queryForObject("SELECT status FROM production_tasks WHERE task_id=?", String.class, task(id))).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_tasks WHERE task_id=?", Integer.class, task(id))).isEqualTo(2);
    }

    @ParameterizedTest
    @ValueSource(strings = {"PENDING", "RUNNING", "BLOCKED"})
    void firstCannotBypassActiveLegacyRework(String status) {
        String id = "LEGACY-ACTIVE-" + status; open(id);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?, '旧活动返工')", rework(id), task(id), issue(id), status);
        var before = facts(); error(create(id, key(id)), 409); absent(key(id)); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"COMPLETED", "FAILED"})
    void inactiveLegacyReworkIsNotSilentlyEnrolledOrUsedAsPredecessor(String status) {
        String id = "LEGACY-INACTIVE-" + status; open(id);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?, '旧历史保持')", rework(id), task(id), issue(id), status);
        var old = evidence(rework(id)); var receipt = created(create(id, key(id)), 1, null);
        assertThat(evidence(rework(id))).isEqualTo(old); assertThat(receipt.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(get(path(id) + "/" + rework(id)).path("roundNumber").isNull()).isTrue();
    }

    @ParameterizedTest
    @ValueSource(strings = {"OPEN", "PROCESSING", "RESOLVED", "CLOSED"})
    void existingControlledChainRejectsBothNewAndLegacyFirstEntrances(String status) {
        String id = "CHAIN-" + status; returned(id);
        jdbc.update("UPDATE quality_issues SET status=? WHERE issue_id=?", status, issue(id));
        var before = facts(); error(create(id, key(id)), 409);
        error(post("/api/tasks/" + task(id) + "/rework", body(id, 0), key(id) + "-legacy"), 409);
        absent(key(id)); absent(key(id) + "-legacy"); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"TASK-PENDING", "VERSION", "MAX-VERSION", "MISSING-TASK", "MISSING-ISSUE", "OTHER-ISSUE", "PROCESSING", "RESOLVED", "CLOSED"})
    void firstValidatesCurrentParentOwnershipVersionAndOpenIssue(String condition) {
        String id = "FIRST-BAD-" + condition; open(id); var payload = body(id, 0); String url = path(id); int status = 409;
        switch (condition) {
            case "TASK-PENDING" -> jdbc.update("UPDATE production_tasks SET status='PENDING' WHERE task_id=?", task(id));
            case "VERSION" -> payload.put("expectedVersion", 1);
            case "MAX-VERSION" -> { jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?", task(id)); payload.put("expectedVersion", 9007199254740991L); }
            case "MISSING-TASK" -> { url = "/api/tasks/TASK-T819-MISSING/reworks"; status = 404; }
            case "MISSING-ISSUE" -> { payload.put("sourceIssueId", "ISSUE-T819-MISSING"); status = 404; }
            case "OTHER-ISSUE" -> { open(id + "-OTHER"); payload.put("sourceIssueId", issue(id + "-OTHER")); }
            default -> jdbc.update("UPDATE quality_issues SET status=? WHERE issue_id=?", condition, issue(id));
        }
        var before = facts(); error(post(url, payload, key(id)), status); absent(key(id)); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"PENDING", "RUNNING", "BLOCKED", "FAILED", "CLOSED", "RESOLVED", "APPROVED", "NO-REVIEW", "NEW-REVISION", "NEW-FAILED", "NEW-PASSED", "LEGACY", "OTHER-ACTIVE", "WRONG-OWNER", "MISSING", "VERSION", "MAX-VERSION", "TASK-PENDING", "MISSING-TASK"})
    void nextRequiresTheCurrentControlledCompletedRoundAndEffectiveReturn(String condition) {
        String id = "NEXT-BAD-" + condition; if (condition.equals("LEGACY")) {
            open(id); jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','无轮次历史')", rework(id), task(id), issue(id));
        } else returned(id);
        String url = path(id) + "/" + rework(id) + "/next-round"; int status = 409; var payload = nextBody(0);
        switch (condition) {
            case "PENDING", "RUNNING", "BLOCKED", "FAILED" -> jdbc.update("UPDATE rework_tasks SET status=? WHERE rework_task_id=?", condition, rework(id));
            case "CLOSED", "RESOLVED" -> jdbc.update("UPDATE quality_issues SET status=? WHERE issue_id=?", condition, issue(id));
            case "APPROVED" -> review(id, 1, 2, "CHECK-T819-" + id + "-1", "APPROVED");
            case "NO-REVIEW" -> inspection(id, 1, 2, "PASSED");
            case "NEW-REVISION" -> jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,2,'成果-A','release-2','新处理','[\"report:new\"]','handler-test',now())", rework(id));
            case "NEW-FAILED", "NEW-PASSED" -> inspection(id, 1, 2, condition.equals("NEW-FAILED") ? "FAILED" : "PASSED");
            case "OTHER-ACTIVE" -> jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'BLOCKED','另有活动任务')", rework(id + "-OTHER"), task(id), issue(id));
            case "WRONG-OWNER" -> { open(id + "-OTHER"); url = path(id + "-OTHER") + "/" + rework(id) + "/next-round"; }
            case "MISSING" -> { url = path(id) + "/REWORK-T819-MISSING/next-round"; status = 404; }
            case "VERSION" -> payload.put("expectedVersion", 1);
            case "MAX-VERSION" -> { jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?", task(id)); payload.put("expectedVersion", 9007199254740991L); }
            case "TASK-PENDING" -> jdbc.update("UPDATE production_tasks SET status='PENDING' WHERE task_id=?", task(id));
            case "MISSING-TASK" -> { url = "/api/tasks/TASK-T819-MISSING/reworks/" + rework(id) + "/next-round"; status = 404; }
            default -> { }
        }
        var before = facts(); error(post(url, payload, key(id)), status); absent(key(id)); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void lastSafeVersionMayBeProducedWithoutOverflow(boolean next) {
        String id = "LAST-VERSION-" + (next ? "NEXT" : "FIRST"); if (next) returned(id); else open(id);
        jdbc.update("UPDATE production_tasks SET version=9007199254740990 WHERE task_id=?", task(id));
        var receipt = created(post(next ? path(id) + "/" + rework(id) + "/next-round" : path(id),
                next ? nextBody(9007199254740990L) : body(id, 9007199254740990L), key(id)), next ? 2 : 1, next ? rework(id) : null);
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(9007199254740991L);
    }

    @Test
    void managedFailedRoundRequiresRecoveryAndCannotBeSkippedByEitherFirstEntrance() {
        String id = "MANAGED-FAILED"; returned(id);
        jdbc.update("UPDATE rework_tasks SET status='FAILED' WHERE rework_task_id=?", rework(id));
        var before = facts(); error(create(id, key(id)), 409); error(next(id, key(id) + "-next"), 409);
        error(post("/api/tasks/" + task(id) + "/rework", body(id, 0), key(id) + "-legacy"), 409);
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void aDifferentSourceIssueMayStartItsOwnControlledRoundWithoutChangingExistingChain() {
        String id = "OTHER-SOURCE"; returned(id); var old = evidence(rework(id));
        String otherIssue = issue(id + "-OTHER"); jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','另一个问题')", otherIssue, task(id));
        var receipt = created(post(path(id), body(id, 0).put("sourceIssueId", otherIssue), key(id)), 1, null);
        assertThat(get(path(id) + "/" + receipt.path("reworkTaskId").asText()).path("reworkTask").path("sourceIssueId").asText()).isEqualTo(otherIssue);
        assertThat(evidence(rework(id))).isEqualTo(old);
    }

    static Stream<Arguments> invalidBodies() {
        List<String> both = List.of("null", "[]", "{}", "{\"expectedVersion\":0}",
                "{\"expectedVersion\":\"0\",\"reason\":\"x\"}", "{\"expectedVersion\":true,\"reason\":\"x\"}",
                "{\"expectedVersion\":0.0,\"reason\":\"x\"}", "{\"expectedVersion\":-1,\"reason\":\"x\"}",
                "{\"expectedVersion\":9007199254740992,\"reason\":\"x\"}", "{\"expectedVersion\":null,\"reason\":\"x\"}",
                "{\"expectedVersion\":0,\"reason\":null}", "{\"expectedVersion\":0,\"reason\":1}",
                "{\"expectedVersion\":0,\"reason\":\" \"}", "{\"expectedVersion\":0,\"reason\":\"x\",\"confirmed\":true}",
                "{\"expectedVersion\":0,\"expectedVersion\":0,\"reason\":\"x\"}", "{\"expectedVersion\":0,\"reason\":\"x\"} {}",
                "{\"expectedVersion\":0,\"reason\":\"\\u0000\"}", "{\"expectedVersion\":0,\"reason\":\"\\ud800\"}",
                "{\"expectedVersion\":0,\"reason\":\"" + "🚀".repeat(501) + "\"}", "{");
        return Stream.of(false, true).flatMap(next -> java.util.stream.IntStream.range(0, both.size()).mapToObj(index -> {
            String body = both.get(index);
            if (!next && body.startsWith("{") && body.length() > 1) body = "{\"sourceIssueId\":\"ISSUE-T819-INPUT\"," + body.substring(1);
            return Arguments.of(next, index, body);
        }));
    }
    @ParameterizedTest
    @MethodSource("invalidBodies")
    void strictJsonDoesNotReserveAKey(boolean next, int index, String payload) {
        String id = "INPUT-" + (next ? "NEXT-" : "FIRST-") + index; if (next) returned(id); else open(id);
        String url = next ? path(id) + "/" + rework(id) + "/next-round" : path(id);
        var before = facts(); error(post(url, payload, key(id)), 400); absent(key(id)); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"sourceIssueId", "expectedVersion", "reason"})
    void firstRejectsNullOrUnknownSourceFields(String field) {
        String id = "FIELD-" + tag(field); open(id); var payload = body(id, 0); payload.putNull(field);
        error(post(path(id), payload, key(id)), 400); absent(key(id));
        payload = body(id, 0); payload.put("roundNumber", 1); error(post(path(id), payload, key(id)), 400); absent(key(id));
        payload = body(id, 0).put("sourceIssueId", "issue-lowercase"); error(post(path(id), payload, key(id)), 400); absent(key(id));
    }

    static Stream<Arguments> headerCases() {
        return Stream.of(false, true).flatMap(next -> Stream.of("NO-USER", "LONG-USER", "NO-ROLE", "ROLE", "NO-KEY", "BAD-KEY", "MEDIA")
                .map(kind -> Arguments.of(next, kind)));
    }
    @ParameterizedTest
    @MethodSource("headerCases")
    void identityRoleKeyAndMediaAreCheckedBeforeWrites(boolean next, String kind) {
        String id = "HEADER-" + (next ? "NEXT-" : "FIRST-") + kind; if (next) returned(id); else open(id);
        String actor = kind.equals("NO-USER") ? null : kind.equals("LONG-USER") ? "u".repeat(129) : "reviewer-test";
        String role = kind.equals("NO-ROLE") ? null : kind.equals("ROLE") ? "reviewer" : "REVIEWER";
        String key = kind.equals("NO-KEY") ? null : kind.equals("BAD-KEY") ? "key with spaces" : key(id);
        int status = kind.equals("NO-USER") ? 401 : List.of("NO-ROLE", "ROLE").contains(kind) ? 403 : 400;
        var before = facts(); error(post(next ? path(id) + "/" + rework(id) + "/next-round" : path(id),
                next ? nextBody(0) : body(id, 0), key, actor, role, kind.equals("MEDIA") ? MediaType.TEXT_PLAIN : MediaType.APPLICATION_JSON), status);
        if (key != null) absent(key); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void rawUnicodeReasonAcceptsExactlyOneThousandUtf16Units(boolean next) {
        String id = "UNICODE-" + (next ? "NEXT" : "FIRST"); if (next) returned(id); else open(id);
        var payload = next ? nextBody(0) : body(id, 0); payload.put("reason", "🚀".repeat(500));
        var receipt = created(post(next ? path(id) + "/" + rework(id) + "/next-round" : path(id), payload, key(id)), next ? 2 : 1, next ? rework(id) : null);
        assertThat(jdbc.queryForObject("SELECT reason FROM rework_tasks WHERE rework_task_id=?", String.class, receipt.path("reworkTaskId").asText())).isEqualTo(payload.path("reason").asText());
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void idempotencyBindsOriginalActorTargetVersionReasonAndOperation(boolean next) {
        String id = "BIND-" + (next ? "NEXT" : "FIRST"); if (next) returned(id); else open(id);
        String url = next ? path(id) + "/" + rework(id) + "/next-round" : path(id);
        var payload = next ? nextBody(0) : body(id, 0); created(post(url, payload, key(id)), next ? 2 : 1, next ? rework(id) : null);
        var before = facts(); error(post(url, payload, key(id), "different-reviewer", "REVIEWER", MediaType.APPLICATION_JSON), 409);
        error(post(url, payload.deepCopy().put("expectedVersion", 1), key(id)), 409);
        error(post(url, payload.deepCopy().put("reason", payload.path("reason").asText().strip()), key(id)), 409);
        error(post(next ? path(id) + "/REWORK-T819-OTHER/next-round" : path(id),
                next ? payload : payload.deepCopy().put("sourceIssueId", "ISSUE-T819-OTHER"), key(id)), 409);
        error(post(next ? path(id) : path(id) + "/REWORK-T819-OTHER/next-round", next ? body(id, 0) : nextBody(0), key(id)), 409);
        error(post("/api/tasks/" + task(id) + "/rework", body(id, 0), key(id)), 409); assertThat(facts()).isEqualTo(before);
    }

    private String table(String point) { return switch (point) { case "version" -> "production_tasks"; case "task" -> "rework_tasks"; case "lifecycle" -> "rework_lifecycles"; case "reservation" -> "idempotency_records"; case "audit" -> "operation_logs"; default -> "rework_operation_receipts"; }; }
    private void trigger(String table, String event, String code) {
        jdbc.execute("CREATE FUNCTION t819_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN " + code + " END $$");
        jdbc.execute("CREATE TRIGGER t819_fault BEFORE " + event + " ON " + table + " FOR EACH ROW EXECUTE FUNCTION t819_fault()");
    }
    private void removeTrigger(String table) { jdbc.execute("DROP TRIGGER t819_fault ON " + table); jdbc.execute("DROP FUNCTION t819_fault()"); }
    static Stream<Arguments> failures() {
        return Stream.of(false, true).flatMap(next -> Stream.of("version", "task", "lifecycle", "reservation", "audit", "receipt")
                .flatMap(point -> Stream.of(false, true).map(zero -> Arguments.of(next, point, zero))));
    }
    @ParameterizedTest
    @MethodSource("failures")
    void everyFailedOrSkippedWriteRollsBackTheEntireCreation(boolean next, String point, boolean zero) {
        String id = "FAULT-" + (next ? "NEXT-" : "FIRST-") + tag(point) + (zero ? "-ZERO" : "-THROW"); if (next) returned(id); else open(id);
        var before = facts(); String table = table(point);
        trigger(table, List.of("version", "reservation").contains(point) ? "UPDATE" : "INSERT", zero ? "RETURN NULL;" : "RAISE EXCEPTION 'forced T819 failure';");
        try {
            error(next ? next(id, key(id)) : create(id, key(id)), zero ? 409 : 500); absent(key(id)); assertThat(facts()).isEqualTo(before);
        } finally { removeTrigger(table); }
        created(next ? next(id, key(id)) : create(id, key(id)), next ? 2 : 1, next ? rework(id) : null);
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void commitFailureAlsoRollsBackNewTaskLifecycleAuditAndReceipt(boolean next) {
        String id = "COMMIT-" + (next ? "NEXT" : "FIRST"); if (next) returned(id); else open(id); var before = facts();
        jdbc.execute("CREATE FUNCTION t819_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced commit failure'; END $$");
        jdbc.execute("CREATE CONSTRAINT TRIGGER t819_commit AFTER INSERT ON rework_operation_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION t819_commit()");
        try { error(next ? next(id, key(id)) : create(id, key(id)), 500); absent(key(id)); assertThat(facts()).isEqualTo(before); }
        finally { jdbc.execute("DROP TRIGGER t819_commit ON rework_operation_receipts"); jdbc.execute("DROP FUNCTION t819_commit()"); }
        created(next ? next(id, key(id)) : create(id, key(id)), next ? 2 : 1, next ? rework(id) : null);
    }

    private List<ResponseEntity<JsonNode>> concurrent(String id, Callable<ResponseEntity<JsonNode>> first, Callable<ResponseEntity<JsonNode>> second) throws Exception {
        try (var pool = Executors.newFixedThreadPool(2); var blocker = dataSource.getConnection()) {
            blocker.setAutoCommit(false);
            try (var statement = blocker.prepareStatement("SELECT task_id FROM production_tasks WHERE task_id=? FOR UPDATE")) {
                statement.setString(1, task(id)); try (var row = statement.executeQuery()) { assertThat(row.next()).isTrue(); }
            }
            var a = pool.submit(first); var b = pool.submit(second);
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND wait_event_type='Lock' AND (lower(query) LIKE '%production_tasks%' OR lower(query) LIKE '%idempotency_records%')", Integer.class);
                    if (waiting == 2) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).as("both real HTTP writes must wait before releasing the parent lock").isEqualTo(2);
            } finally { blocker.rollback(); }
            return List.of(a.get(30, TimeUnit.SECONDS), b.get(30, TimeUnit.SECONDS));
        }
    }
    static Stream<Arguments> duplicates() { return Stream.of(false, true).flatMap(next -> Stream.of(false, true).map(same -> Arguments.of(next, same))); }
    @ParameterizedTest
    @MethodSource("duplicates")
    void sameAndDifferentKeysCannotForkTheControlledChain(boolean next, boolean same) throws Exception {
        String id = "RACE-" + (next ? "NEXT-" : "FIRST-") + (same ? "SAME" : "DIFFERENT"); if (next) returned(id); else open(id);
        String otherKey = same ? key(id) : key(id) + "-other";
        var responses = concurrent(id, () -> next ? next(id, key(id)) : create(id, key(id)), () -> next ? next(id, otherKey) : create(id, otherKey));
        if (same) assertThat(created(responses.get(0), next ? 2 : 1, next ? rework(id) : null)).isEqualTo(created(responses.get(1), next ? 2 : 1, next ? rework(id) : null));
        else {
            assertThat(responses.stream().map(response -> response.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
            int winner = responses.get(0).getStatusCode().value() == 200 ? 0 : 1; created(responses.get(winner), next ? 2 : 1, next ? rework(id) : null);
            absent(winner == 0 ? otherKey : key(id));
        }
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_lifecycles WHERE task_id=?", Integer.class, task(id))).isEqualTo(next ? 2 : 1);
        assertThat(jdbc.queryForObject("SELECT version FROM production_tasks WHERE task_id=?", Long.class, task(id))).isEqualTo(1);
    }

    @Test
    void legacyAndControlledFirstEntrancesCompeteForTheSameVersion() throws Exception {
        String id = "LEGACY-RACE"; open(id);
        var responses = concurrent(id, () -> create(id, key(id)), () -> post("/api/tasks/" + task(id) + "/rework", body(id, 0), key(id) + "-legacy"));
        assertThat(responses.stream().map(response -> response.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_tasks WHERE task_id=?", Integer.class, task(id))).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT version FROM production_tasks WHERE task_id=?", Long.class, task(id))).isEqualTo(1);
        absent(responses.get(0).getStatusCode().value() == 200 ? key(id) + "-legacy" : key(id));
    }

    @Test
    void legacySuccessfulReplayKeepsPendingEvenAfterLifecycleFactsChange() {
        String id = "LEGACY-REPLAY"; open(id); String url = "/api/tasks/" + task(id) + "/rework";
        var original = ok(post(url, body(id, 0), key(id))); String legacyId = original.path("reworkTask").path("reworkTaskId").asText();
        jdbc.update("UPDATE rework_tasks SET status='COMPLETED' WHERE rework_task_id=?", legacyId);
        var controlled = created(post(path(id), body(id, 1), key(id) + "-controlled"), 1, null);
        assertThat(controlled.path("taskVersion").asLong()).isEqualTo(2);
        var before = facts(); assertThat(ok(post(url, body(id, 0), key(id)))).isEqualTo(original); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void outsideReadersCannotObserveAnUncommittedNewRound(boolean next) throws Exception {
        String id = "OBSERVE-" + (next ? "NEXT" : "FIRST"); if (next) returned(id); else open(id);
        var before = facts(); var effective = get("/api/tasks/" + task(id) + "/effective-reviews");
        trigger("rework_operation_receipts", "INSERT", "PERFORM pg_advisory_xact_lock(819,1); RETURN NEW;");
        try (var pool = Executors.newSingleThreadExecutor(); var blocker = dataSource.getConnection()) {
            try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_lock(819,1)"); }
            var response = pool.submit(() -> next ? next(id, key(id)) : create(id, key(id)));
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=819 AND objid=1 AND objsubid=2 AND NOT granted", Integer.class);
                    if (waiting == 1) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).isEqualTo(1); assertThat(response.isDone()).isFalse(); assertThat(facts()).isEqualTo(before);
                assertThat(get("/api/tasks/" + task(id) + "/effective-reviews")).isEqualTo(effective);
            } finally { try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_unlock(819,1)"); } }
            created(response.get(30, TimeUnit.SECONDS), next ? 2 : 1, next ? rework(id) : null);
        } finally { removeTrigger("rework_operation_receipts"); }
    }

    private List<String> golden() {
        return jdbc.queryForList("""
                SELECT 'order:' || to_jsonb(o)::text FROM production_orders o WHERE order_id='ORDER-003'
                UNION ALL SELECT 'task:' || to_jsonb(t)::text FROM production_tasks t WHERE task_id='TASK-003'
                UNION ALL SELECT 'issue:' || to_jsonb(q)::text FROM quality_issues q WHERE task_id='TASK-003'
                UNION ALL SELECT 'rework:' || to_jsonb(r)::text FROM rework_tasks r WHERE task_id='TASK-003'
                UNION ALL SELECT 'review:' || to_jsonb(r)::text FROM review_records r WHERE issue_id='ISSUE-001'
                UNION ALL SELECT 'delivery:' || to_jsonb(d)::text FROM delivery_records d WHERE order_id='ORDER-003' ORDER BY 1
                """, String.class);
    }
}
