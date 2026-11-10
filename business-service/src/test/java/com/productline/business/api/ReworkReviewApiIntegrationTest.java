package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
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

/** 复核通过与问题关闭的真实HTTP、当前材料、并发及逐写入点/提交原子性验收。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t817_review_write", "spring.flyway.default-schema=t817_review_write",
        "spring.datasource.hikari.schema=t817_review_write", "spring.jpa.properties.hibernate.default_schema=t817_review_write"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkReviewApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private DataSource dataSource;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T817','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T817','ORDER-T817','BLOCKED')");
        ready("INVALID");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T817'", String.class)).isEqualTo("QUALITY_CHECKING");
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T817'", String.class)).isEqualTo("BLOCKED");
        } finally { jdbc.execute("DROP SCHEMA t817_review_write CASCADE"); }
    }

    private String task(String id) { return "TASK-T817-" + id; }
    private String rework(String id) { return "REWORK-T817-" + id; }
    private String issue(String id) { return "ISSUE-T817-" + id; }
    private String check(String id, long sequence) { return "CHECK-T817-" + id + "-" + sequence; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }

    private void fixture(String id, String taskState, String reworkState, String issueState, boolean lifecycle, boolean material) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T817',?)", task(id), taskState);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM',?,'独立复核问题')", issue(id), task(id), issueState);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?,'原始创建原因')", rework(id), task(id), issue(id), reworkState);
        if (lifecycle) {
            jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at) VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-10 00:00:00+00','original-handler',TIMESTAMPTZ '2026-11-10 00:01:00+00')", rework(id), task(id), issue(id));
            if (material) {
                processing(id, 1); inspection(id, 1, 1, "FAILED"); inspection(id, 1, 2, "PASSED");
            }
        }
    }

    private void ready(String id) { fixture(id, "COMPLETED", "COMPLETED", "RESOLVED", true, true); }
    private void processing(String id, long revision) {
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,?,'成果-A','同一版本文本','  人工处理说明  ','[\"report:material\"]'::jsonb,'handler-test',TIMESTAMPTZ '2026-11-10 00:02:00+00')", rework(id), revision);
    }
    private void inspection(String id, long revision, long sequence, String result) {
        String items = "[{\"checkItem\":\"坐标系\",\"result\":\"" + result + "\",\"comment\":\"人工检查说明\",\"evidenceReferences\":[\"report:inspection\"]}]";
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,?,?,?,?::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-10 00:03:00+00')", check(id, sequence), rework(id), revision, sequence, result, items);
    }
    private ObjectNode body(String id, long version) {
        return mapper.createObjectNode().put("expectedVersion", version).put("processingRevision", 1)
                .put("inspectionId", check(id, 2)).put("status", "APPROVED").put("reviewComment", "  人工审查当前成果与通过检查🚀  ");
    }
    private ResponseEntity<JsonNode> post(String path, String body, String key, String actor, String role) {
        var headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON); headers.set("X-Trace-Id", "trace-t817");
        if (key != null) headers.set("Idempotency-Key", key);
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        return http.exchange(path, HttpMethod.POST, new HttpEntity<>(body, headers), JsonNode.class);
    }
    private ResponseEntity<JsonNode> submit(String id, JsonNode body, String key) { return post(base(id) + "/review", body.toString(), key, "reviewer-test", "REVIEWER"); }
    private JsonNode get(String path) {
        var headers = new HttpHeaders(); headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER");
        var response = http.exchange(path, HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200); return response.getBody().path("data");
    }
    private JsonNode success(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        var envelope = response.getBody(); assertThat(envelope).isNotNull(); assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue(); assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse(); assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t817");
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t817");
        var data = envelope.path("data"); assertThat(data.size()).isEqualTo(12);
        assertThat(data.path("operation").asText()).isEqualTo("SUBMIT_REWORK_REVIEW");
        assertThat(data.path("reviewId").asText()).matches("^REVIEW-[A-Z0-9-]+$");
        assertThat(data.path("status").asText()).isEqualTo("COMPLETED"); assertThat(data.path("issueStatus").asText()).isEqualTo("CLOSED");
        return data;
    }
    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code); assertThat(response.getBody().path("data").isNull()).isTrue();
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("report:material", "request_hash", "原始创建原因", "人工审查当前成果");
    }
    private List<String> facts() {
        return Stream.of("production_orders", "production_tasks", "quality_issues", "rework_tasks", "review_records", "delivery_records",
                "rework_lifecycles", "rework_processing_revisions", "rework_inspections", "rework_reviews", "idempotency_records", "operation_logs", "rework_operation_receipts")
                .flatMap(t -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + t + " r ORDER BY to_jsonb(r)::text", String.class).stream()).toList();
    }
    private List<String> materials(String id) {
        return Stream.of("rework_tasks", "rework_lifecycles", "rework_processing_revisions", "rework_inspections")
                .flatMap(t -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + t + " r WHERE rework_task_id=? ORDER BY to_jsonb(r)::text", String.class, rework(id)).stream()).toList();
    }
    private Map<String,Object> state(String id) {
        return jdbc.queryForMap("SELECT t.status AS task_status,t.version,r.status AS rework_status,q.status AS issue_status FROM production_tasks t JOIN rework_tasks r ON r.task_id=t.task_id JOIN quality_issues q ON q.issue_id=r.source_issue_id WHERE r.rework_task_id=?", rework(id));
    }
    private int reviews(String id) { return jdbc.queryForObject("SELECT count(*) FROM rework_reviews WHERE rework_task_id=?", Integer.class, rework(id)); }
    private int audits(String key) { return jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')", Integer.class, key); }
    private void absent(String key) {
        for (String table : List.of("idempotency_records", "rework_operation_receipts")) assertThat(jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE idempotency_key=?", Integer.class, key)).isZero();
        assertThat(audits(key)).isZero();
    }

    @Test
    void approvesOnlyCurrentPassedMaterialAndPreservesAllEarlierFacts() throws Exception {
        String id = "SUCCESS"; ready(id); var materials = materials(id); Instant before = Instant.now();
        jdbc.update("INSERT INTO review_records VALUES ('REVIEW-OLD-T817-SUCCESS',?,'REWORK_REQUIRED','旧表复核不覆盖')", issue(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','其他未关闭问题')", issue("SUCCESS-OTHER"), task(id));
        var legacy = get("/api/tasks/" + task(id) + "/review"); var input = body(id, 0); String key = "t817-success";
        var receipt = success(submit(id, input, key));
        assertThat(receipt.path("taskId").asText()).isEqualTo(task(id)); assertThat(receipt.path("reworkTaskId").asText()).isEqualTo(rework(id));
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(1); assertThat(receipt.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(receipt.path("previousReworkTaskId").isNull()).isTrue(); assertThat(receipt.path("processingRevision").asLong()).isEqualTo(1);
        assertThat(receipt.path("inspectionId").asText()).isEqualTo(check(id, 2)); assertThat(materials(id)).isEqualTo(materials);
        assertThat(state(id)).containsEntry("version", 1L).containsEntry("task_status", "COMPLETED").containsEntry("rework_status", "COMPLETED").containsEntry("issue_status", "CLOSED");
        assertThat(jdbc.queryForObject("SELECT status FROM quality_issues WHERE issue_id=?", String.class, issue("SUCCESS-OTHER"))).isEqualTo("OPEN");
        var row = jdbc.queryForMap("SELECT * FROM rework_reviews WHERE review_id=?", receipt.path("reviewId").asText());
        assertThat(row).containsEntry("reviewed_by", "reviewer-test").containsEntry("review_comment", input.path("reviewComment").asText()).containsEntry("review_sequence", 1L).containsEntry("status", "APPROVED");
        assertThat(((java.sql.Timestamp) row.get("reviewed_at")).toInstant()).isBetween(before.minusSeconds(1), Instant.now().plusSeconds(1));
        var audit = jdbc.queryForMap("SELECT * FROM operation_logs WHERE operation_id=?", receipt.path("operationId").asText());
        assertThat(audit).containsEntry("actor_user_id", "reviewer-test"); assertThat(audit.get("idempotency_key_hash").toString()).matches("[a-f0-9]{64}");
        assertThat(mapper.readTree(audit.get("after_state").toString()).path("reviewId").asText()).isEqualTo(receipt.path("reviewId").asText());
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key=?", String.class, key))).isEqualTo(receipt);
        assertThat(get("/api/tasks/" + task(id) + "/review")).isEqualTo(legacy);
        var current = get("/api/tasks/" + task(id) + "/effective-reviews").path("issues").get(0);
        assertThat(current.path("review").path("reviewId").asText()).isEqualTo(receipt.path("reviewId").asText()); assertThat(current.path("legacyReviews").isEmpty()).isTrue();
        assertThat(get(base(id) + "/reviews").path("records").size()).isEqualTo(1);
    }

    static Stream<String> invalidBodies() {
        String valid = "{\"expectedVersion\":0,\"processingRevision\":1,\"inspectionId\":\"CHECK-T817-INVALID-2\",\"status\":\"APPROVED\",\"reviewComment\":\"说明\"}";
        return Stream.concat(Stream.of("", "null", "[]", "{}", "{not-json}", valid + " {}",
                valid.replace("\"status\":\"APPROVED\"", "\"status\":\"PENDING\""), valid.replace("APPROVED", "approved"),
                valid.replace("CHECK-T817-INVALID-2", "check-lower"), valid.replace("\"reviewComment\":\"说明\"", "\"reviewComment\":\"　 \""),
                valid.substring(0, valid.length() - 1) + ",\"status\":\"APPROVED\"}",
                valid.substring(0, valid.length() - 1) + ",\"confirmed\":true}"),
                Stream.of("expectedVersion", "processingRevision", "inspectionId", "status", "reviewComment").flatMap(field -> {
                    try {
                        var mapper = new ObjectMapper(); var original = (ObjectNode) mapper.readTree(valid);
                        var absent = original.deepCopy(); absent.remove(field);
                        var nil = original.deepCopy(); nil.putNull(field);
                        var wrong = original.deepCopy(); if (field.equals("expectedVersion") || field.equals("processingRevision")) wrong.put(field, "1"); else wrong.put(field, true);
                        return Stream.of(absent.toString(), nil.toString(), wrong.toString());
                    } catch (Exception exception) { throw new IllegalStateException(exception); }
                }));
    }

    @ParameterizedTest
    @MethodSource("invalidBodies")
    void rejectsAmbiguousMissingUnknownAndCoercedInput(String body) {
        var before = facts(); error(post(base("INVALID") + "/review", body, "t817-invalid", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        absent("t817-invalid"); assertThat(facts()).isEqualTo(before);
    }

    static Stream<Arguments> badNumbers() {
        return Stream.of("expectedVersion", "processingRevision").flatMap(f -> Stream.of("true", "1.0", "-1", "9007199254740992").map(n -> Arguments.of(f, n)));
    }
    @ParameterizedTest
    @MethodSource("badNumbers")
    void rejectsUnsafeNumbers(String field, String raw) {
        String json = body("INVALID", 0).toString().replace("\"" + field + "\":" + (field.equals("expectedVersion") ? "0" : "1"), "\"" + field + "\":" + raw);
        error(post(base("INVALID") + "/review", json, "t817-number", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); absent("t817-number");
    }

    @ParameterizedTest
    @ValueSource(ints = {0, 0xD800, 0xDC00})
    void rejectsLossyComments(int codeUnit) throws Exception {
        var input = body("INVALID", 0).put("reviewComment", String.valueOf((char) codeUnit));
        String json = mapper.writer().with(JsonGenerator.Feature.ESCAPE_NON_ASCII).writeValueAsString(input);
        error(post(base("INVALID") + "/review", json, "t817-lossy", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); absent("t817-lossy");
    }

    @ParameterizedTest
    @ValueSource(strings = {"字", "🚀"})
    void enforcesUtf16LengthAndPreservesRawComment(String unit) {
        String id = unit.equals("字") ? "BMP" : "NONBMP"; ready(id); int count = 1000 / unit.length();
        error(submit(id, body(id, 0).put("reviewComment", unit.repeat(count + 1)), "t817-long-" + id), 400, "PARAM_VALIDATION_ERROR"); absent("t817-long-" + id);
        var receipt = success(submit(id, body(id, 0).put("reviewComment", unit.repeat(count)), "t817-utf-" + id));
        assertThat(jdbc.queryForObject("SELECT review_comment FROM rework_reviews WHERE review_id=?", String.class, receipt.path("reviewId").asText())).isEqualTo(unit.repeat(count));
    }

    static Stream<Arguments> illegalStates() {
        return Stream.of(Arguments.of("TASKRUNNING", "RUNNING", "COMPLETED", "RESOLVED"), Arguments.of("PENDING", "COMPLETED", "PENDING", "OPEN"),
                Arguments.of("RUNNING", "COMPLETED", "RUNNING", "PROCESSING"), Arguments.of("BLOCKED", "COMPLETED", "BLOCKED", "PROCESSING"),
                Arguments.of("FAILED", "COMPLETED", "FAILED", "PROCESSING"), Arguments.of("OPEN", "COMPLETED", "COMPLETED", "OPEN"),
                Arguments.of("PROCESSING", "COMPLETED", "COMPLETED", "PROCESSING"), Arguments.of("CLOSED", "COMPLETED", "COMPLETED", "CLOSED"));
    }
    @ParameterizedTest
    @MethodSource("illegalStates")
    void rejectsIllegalStateWithoutSideEffects(String id, String ts, String rs, String qs) {
        fixture(id, ts, rs, qs, true, true); var before = facts(); String key = "t817-state-" + id;
        error(submit(id, body(id, 0), key), 409, "BUSINESS_CONFLICT"); absent(key); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void acceptsNonApprovedBranchAfterT818WithoutChangingCompletedWork(String status) {
        String id = "RETURN-" + status.replace('_', '-'); ready(id);
        var response = submit(id, body(id, 0).put("status", status), "t817-return-" + status);
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody().path("data").path("issueStatus").asText()).isEqualTo("OPEN");
        assertThat(state(id)).containsEntry("version", 1L).containsEntry("issue_status", "OPEN").containsEntry("rework_status", "COMPLETED");
        assertThat(jdbc.queryForObject("SELECT status FROM rework_reviews WHERE rework_task_id=?", String.class, rework(id))).isEqualTo(status);
    }

    @Test
    void validatesIdentityOwnershipResourceAndHeaders() {
        var before = facts(); String json = body("INVALID", 0).toString(); String path = base("INVALID") + "/review";
        error(post(path, json, "t817-auth", null, "REVIEWER"), 401, "PERMISSION_DENIED");
        error(post(path, json, "t817-auth", "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        error(post(path, json, "t817-auth", "x".repeat(129), "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        for (String key : new String[]{null, "bad key", "x".repeat(129)}) error(post(path, json, key, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(post("/api/tasks/task-lower/reworks/" + rework("INVALID") + "/review", json, "t817-id", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(post("/api/tasks/TASK-003/reworks/" + rework("INVALID") + "/review", json, "t817-owner", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(submit("MISSING", body("MISSING", 0), "t817-missing"), 404, "RESOURCE_NOT_FOUND");
        error(post("/api/tasks/" + task("INVALID") + "/reworks/REWORK-MISSING/review", json, "t817-missing-rw", "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        for (String key : List.of("t817-auth", "t817-id", "t817-owner", "t817-missing", "t817-missing-rw")) absent(key);
        assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"LEGACY", "SOURCE", "MATERIAL", "REVISION", "CHECK", "FAILEDCHECK", "NEWCHECK", "STALE", "SUCCESSOR"})
    void rechecksManagedRoundCurrentMaterialAndVersion(String kind) {
        String id = "FACT-" + kind;
        fixture(id, "COMPLETED", "COMPLETED", "RESOLVED", !List.of("LEGACY", "SOURCE").contains(kind), !kind.equals("MATERIAL"));
        if (kind.equals("SOURCE")) jdbc.update("UPDATE rework_tasks SET source_issue_id=NULL WHERE rework_task_id=?", rework(id));
        if (kind.equals("REVISION")) processing(id, 2);
        if (kind.equals("FAILEDCHECK") || kind.equals("NEWCHECK")) inspection(id, 1, 3, kind.equals("FAILEDCHECK") ? "FAILED" : "PASSED");
        if (kind.equals("STALE")) jdbc.update("UPDATE production_tasks SET version=1 WHERE task_id=?", task(id));
        if (kind.equals("SUCCESSOR")) {
            jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','下一轮原因')", rework(id) + "-NEXT", task(id), issue(id));
            jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES (?,?,?,2,?,1,'creator-test',CURRENT_TIMESTAMP)", rework(id) + "-NEXT", task(id), issue(id), rework(id));
        }
        var input = body(id, 0); if (kind.equals("CHECK")) input.put("inspectionId", check(id, 1));
        var before = facts(); String key = "t817-fact-" + kind;
        error(submit(id, input, key), 409, "BUSINESS_CONFLICT"); absent(key); assertThat(facts()).isEqualTo(before);
    }

    @Test
    void protectsVersionAndReviewSequenceSafeIntegerLimits() {
        ready("MAXVERSION"); jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?", task("MAXVERSION"));
        error(submit("MAXVERSION", body("MAXVERSION", 9007199254740991L), "t817-maxversion"), 409, "BUSINESS_CONFLICT"); absent("t817-maxversion");
        ready("LASTVERSION"); jdbc.update("UPDATE production_tasks SET version=9007199254740990 WHERE task_id=?", task("LASTVERSION"));
        assertThat(success(submit("LASTVERSION", body("LASTVERSION", 9007199254740990L), "t817-lastversion")).path("taskVersion").asLong()).isEqualTo(9007199254740991L);
        ready("MAXSEQ");
        jdbc.update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES ('REVIEW-T817-MAX',?,1,?,9007199254740991,'REJECTED','原历史边界','reviewer-test',now())", rework("MAXSEQ"), check("MAXSEQ", 2));
        var before = facts(); error(submit("MAXSEQ", body("MAXSEQ", 0), "t817-maxseq"), 409, "BUSINESS_CONFLICT"); absent("t817-maxseq"); assertThat(facts()).isEqualTo(before);
    }

    @Test
    void bindsEntireRequestAndReplaysOriginalReceiptAfterOtherTaskFactsAdvance() throws Exception {
        String id = "BIND"; ready(id); var input = body(id, 0); String key = "t817-bind"; var original = success(submit(id, input, key));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','另一个待处理问题')", issue("BIND-OTHER"), task(id));
        String legacy = mapper.writeValueAsString(Map.of("issueId", issue("BIND-OTHER"), "expectedVersion", 1, "status", "REWORK_REQUIRED", "reviewComment", "独立旧复核"));
        assertThat(post("/api/tasks/" + task(id) + "/review", legacy, "t817-other-issue", "reviewer-test", "REVIEWER").getStatusCode().value()).isEqualTo(200);
        ready("BINDOTHER"); var before = facts(); assertThat(success(submit(id, input, key))).isEqualTo(original);
        for (String field : List.of("expectedVersion", "processingRevision", "inspectionId", "reviewComment")) {
            var changed = input.deepCopy();
            if (field.equals("expectedVersion")) changed.put(field, 2); else if (field.equals("processingRevision")) changed.put(field, 2);
            else if (field.equals("inspectionId")) changed.put(field, "CHECK-OTHER"); else changed.put(field, input.path(field).asText().strip());
            error(submit(id, changed, key), 409, "BUSINESS_CONFLICT");
        }
        error(submit(id, input.deepCopy().put("status", "REJECTED"), key), 409, "BUSINESS_CONFLICT");
        error(post(base(id) + "/review", input.toString(), key, "other-user", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(post(base(id) + "/review", input.toString(), key, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        error(submit("BINDOTHER", input, key), 409, "BUSINESS_CONFLICT");
        error(post(base(id) + "/block", "{\"expectedVersion\":2,\"reason\":\"不同动作\"}", key, "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(submit(id, body(id, 2), "t817-bind-new"), 409, "BUSINESS_CONFLICT"); absent("t817-bind-new");
        assertThat(facts()).isEqualTo(before); assertThat(reviews(id)).isEqualTo(1); assertThat(audits(key)).isEqualTo(1);
        assertThat(state(id)).containsEntry("version", 2L).containsEntry("issue_status", "CLOSED");
    }

    static Stream<Arguments> failurePoints() {
        return Stream.of("version", "review", "issue", "reservation", "audit", "receipt").flatMap(point -> Stream.of(false, true).map(zero -> Arguments.of(point, zero)));
    }
    private String table(String point) {
        return switch (point) { case "version" -> "production_tasks"; case "review" -> "rework_reviews"; case "issue" -> "quality_issues"; case "reservation" -> "idempotency_records"; case "audit" -> "operation_logs"; default -> "rework_operation_receipts"; };
    }
    private void trigger(String table, String event, String body) {
        jdbc.execute("CREATE FUNCTION t817_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN " + body + " END $$");
        jdbc.execute("CREATE TRIGGER t817_fault BEFORE " + event + " ON " + table + " FOR EACH ROW EXECUTE FUNCTION t817_fault()");
    }
    private void removeTrigger(String table) { jdbc.execute("DROP TRIGGER t817_fault ON " + table); jdbc.execute("DROP FUNCTION t817_fault()"); }

    @ParameterizedTest
    @MethodSource("failurePoints")
    void anyExceptionOrZeroRowRollsBackClosureReviewAuditAndReceipt(String point, boolean zero) {
        String id = "ROLL-" + point.toUpperCase(Locale.ROOT) + (zero ? "-ZERO" : "-ERROR"); ready(id); var before = facts(); String key = "t817-" + id;
        String event = List.of("version", "issue", "reservation").contains(point) ? "UPDATE" : "INSERT";
        trigger(table(point), event, zero ? "RETURN NULL;" : "RAISE EXCEPTION 'forced T817 failure';");
        try {
            error(submit(id, body(id, 0), key), zero ? 409 : 500, zero ? "BUSINESS_CONFLICT" : "INTERNAL_SERVER_ERROR"); absent(key);
            assertThat(facts()).isEqualTo(before);
        } finally { removeTrigger(table(point)); }
        success(submit(id, body(id, 0), key)); assertThat(reviews(id)).isEqualTo(1); assertThat(audits(key)).isEqualTo(1);
    }

    @Test
    void commitFailureCannotPublishHalfSuccessfulClosure() {
        String id = "COMMIT"; ready(id); var before = facts(); String key = "t817-commit";
        jdbc.execute("CREATE FUNCTION t817_commit_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T817 commit failure'; END $$");
        jdbc.execute("CREATE CONSTRAINT TRIGGER t817_commit_fault AFTER INSERT ON rework_operation_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION t817_commit_fault()");
        try { error(submit(id, body(id, 0), key), 500, "INTERNAL_SERVER_ERROR"); absent(key); assertThat(facts()).isEqualTo(before); }
        finally { jdbc.execute("DROP TRIGGER t817_commit_fault ON rework_operation_receipts"); jdbc.execute("DROP FUNCTION t817_commit_fault()"); }
        success(submit(id, body(id, 0), key));
    }

    private List<ResponseEntity<JsonNode>> concurrent(String id, Callable<ResponseEntity<JsonNode>> first, Callable<ResponseEntity<JsonNode>> second) throws Exception {
        var ready = new CountDownLatch(2); var go = new CountDownLatch(1);
        try (var pool = Executors.newFixedThreadPool(2); var blocker = dataSource.getConnection()) {
            blocker.setAutoCommit(false);
            try (var statement = blocker.prepareStatement("SELECT task_id FROM production_tasks WHERE task_id=? FOR UPDATE")) {
                statement.setString(1, task(id)); try (var row = statement.executeQuery()) { assertThat(row.next()).isTrue(); }
            }
            var a = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return first.call(); });
            var b = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return second.call(); });
            try {
                assertThat(ready.await(10, TimeUnit.SECONDS)).isTrue(); go.countDown(); long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    // 新接口等父任务锁，旧接口等共享版本CAS；两者都必须真实到达数据库锁等待。
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND wait_event_type='Lock' AND (lower(query) LIKE '%production_tasks%' OR lower(query) LIKE '%idempotency_records%')", Integer.class);
                    if (waiting >= 2) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).as("both HTTP writers must contend before releasing the parent lock").isEqualTo(2);
            } finally { blocker.rollback(); }
            return List.of(a.get(30, TimeUnit.SECONDS), b.get(30, TimeUnit.SECONDS));
        }
    }

    @ParameterizedTest
    @ValueSource(booleans = {true, false})
    void concurrentApprovalsHaveExactlyOneCommittedClosure(boolean sameKey) throws Exception {
        String id = sameKey ? "SAMEKEY" : "DIFFERENTKEY"; ready(id); String a = "t817-concurrent-" + id; String b = sameKey ? a : a + "-other";
        var results = concurrent(id, () -> submit(id, body(id, 0), a), () -> submit(id, body(id, 0), b));
        if (sameKey) assertThat(success(results.get(0))).isEqualTo(success(results.get(1)));
        else {
            assertThat(results.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
            int winner = results.get(0).getStatusCode().value() == 200 ? 0 : 1; success(results.get(winner)); error(results.get(1 - winner), 409, "BUSINESS_CONFLICT"); absent(winner == 0 ? b : a);
        }
        assertThat(state(id)).containsEntry("version", 1L).containsEntry("issue_status", "CLOSED"); assertThat(reviews(id)).isEqualTo(1);
    }

    @Test
    void legacyReviewAndApprovalShareOneTaskVersionWithoutPartialWrites() throws Exception {
        String id = "LEGACYRACE"; ready(id);
        String legacy = mapper.writeValueAsString(Map.of("issueId", issue(id), "expectedVersion", 0, "status", "REWORK_REQUIRED", "reviewComment", "独立旧复核"));
        var results = concurrent(id, () -> submit(id, body(id, 0), "t817-race-new"), () -> post("/api/tasks/" + task(id) + "/review", legacy, "t817-race-old", "reviewer-test", "REVIEWER"));
        assertThat(results.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        if (results.get(0).getStatusCode().value() == 200) {
            success(results.get(0)); absent("t817-race-old"); assertThat(reviews(id)).isEqualTo(1);
            assertThat(state(id)).containsEntry("issue_status", "CLOSED");
        } else {
            error(results.get(0), 409, "BUSINESS_CONFLICT"); absent("t817-race-new"); assertThat(reviews(id)).isZero();
            assertThat(state(id)).containsEntry("issue_status", "RESOLVED"); assertThat(audits("t817-race-old")).isEqualTo(1);
        }
        assertThat(state(id)).containsEntry("version", 1L);
    }

    @Test
    void independentReadersCannotSeeNewReviewOrClosedIssueBeforeCommit() throws Exception {
        String id = "PAUSE"; ready(id); var before = facts(); var detail = get(base(id));
        trigger("rework_operation_receipts", "INSERT", "PERFORM pg_advisory_xact_lock(817,1); RETURN NEW;");
        try (var pool = Executors.newSingleThreadExecutor(); var blocker = dataSource.getConnection()) {
            try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_lock(817,1)"); }
            var response = pool.submit(() -> submit(id, body(id, 0), "t817-pause"));
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=817 AND objid=1 AND objsubid=2 AND NOT granted", Integer.class);
                    if (waiting == 1) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).isEqualTo(1); assertThat(response.isDone()).isFalse(); assertThat(facts()).isEqualTo(before);
                assertThat(get(base(id))).isEqualTo(detail);
                var current = get("/api/tasks/" + task(id) + "/effective-reviews"); assertThat(current.path("taskVersion").asLong()).isZero(); assertThat(current.path("issues").get(0).path("review").isNull()).isTrue();
            } finally { try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_unlock(817,1)"); } }
            success(response.get(30, TimeUnit.SECONDS)); assertThat(state(id)).containsEntry("issue_status", "CLOSED");
        } finally { removeTrigger("rework_operation_receipts"); }
    }

    @Test
    void actualLifecycleCompletesChecksThenApprovesWithoutAdvancingDelivery() {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T817','COMPLETED')", task("HTTP"));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','真实HTTP链路')", issue("HTTP"), task("HTTP"));
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','初始原因')", rework("HTTP"), task("HTTP"), issue("HTTP"));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,?,?,1,'creator-test',CURRENT_TIMESTAMP)", rework("HTTP"), task("HTTP"), issue("HTTP"));
        assertThat(post(base("HTTP") + "/start", "{\"expectedVersion\":0}", "t817-http-start", "reviewer-test", "REVIEWER").getStatusCode().value()).isEqualTo(200);
        var material = mapper.createObjectNode().put("expectedVersion", 1).put("processingComment", "真实人工登记"); material.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "v1"); material.putArray("evidenceReferences").add("report:manual");
        assertThat(post(base("HTTP") + "/results", material.toString(), "t817-http-result", "reviewer-test", "REVIEWER").getStatusCode().value()).isEqualTo(200);
        var check = mapper.createObjectNode().put("expectedVersion", 2).put("processingRevision", 1); var item = check.putArray("items").addObject().put("checkItem", "坐标系").put("result", "PASSED").put("comment", "人工通过"); item.putArray("evidenceReferences").add("report:passed");
        var checked = post(base("HTTP") + "/inspections", check.toString(), "t817-http-inspection", "reviewer-test", "REVIEWER"); assertThat(checked.getStatusCode().value()).isEqualTo(200);
        var request = body("HTTP", 3).put("inspectionId", checked.getBody().path("data").path("inspectionId").asText());
        var receipt = success(submit("HTTP", request, "t817-http-review")); assertThat(receipt.path("taskVersion").asLong()).isEqualTo(4);
        assertThat(state("HTTP")).containsEntry("task_status", "COMPLETED").containsEntry("rework_status", "COMPLETED").containsEntry("issue_status", "CLOSED");
    }

    @Test
    void secondRoundApprovalKeepsPriorRejectionAndUsesRealPredecessor() {
        String id = "SECOND"; ready(id);
        jdbc.update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES ('REVIEW-T817-OLD-ROUND',?,1,?,1,'REWORK_REQUIRED','原轮次退回','reviewer-test',CURRENT_TIMESTAMP)", rework(id), check(id, 2));
        String next = rework(id) + "-NEXT"; String inspection = "CHECK-T817-SECOND-NEXT";
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','第二轮原因')", next, task(id), issue(id));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES (?,?,?,2,?,1,'creator-test',CURRENT_TIMESTAMP)", next, task(id), issue(id), rework(id));
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,1,'成果-B','v2','第二轮处理','[\"report:second\"]'::jsonb,'handler-test',CURRENT_TIMESTAMP)", next);
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,1,1,'PASSED','[{\"checkItem\":\"坐标系\",\"result\":\"PASSED\",\"comment\":\"实际通过\",\"evidenceReferences\":[\"report:second-check\"]}]'::jsonb,'inspector-test',CURRENT_TIMESTAMP)", inspection, next);
        var prior = get(base(id) + "/reviews");
        error(submit(id, body(id, 0), "t817-old-round"), 409, "BUSINESS_CONFLICT"); absent("t817-old-round");
        var receipt = success(post("/api/tasks/" + task(id) + "/reworks/" + next + "/review", body(id, 0).put("inspectionId", inspection).toString(), "t817-second-round", "reviewer-test", "REVIEWER"));
        assertThat(receipt.path("roundNumber").asLong()).isEqualTo(2); assertThat(receipt.path("previousReworkTaskId").asText()).isEqualTo(rework(id));
        assertThat(receipt.path("reworkTaskId").asText()).isEqualTo(next); assertThat(get(base(id) + "/reviews")).isEqualTo(prior);
        var current = get("/api/tasks/" + task(id) + "/effective-reviews").path("issues").get(0);
        assertThat(current.path("roundNumber").asLong()).isEqualTo(2); assertThat(current.path("review").path("status").asText()).isEqualTo("APPROVED");
    }

    @Test
    void requiresJsonContentTypeAndPositiveRevision() {
        var headers = new HttpHeaders(); headers.setContentType(MediaType.TEXT_PLAIN); headers.set("X-User-Id", "reviewer-test");
        headers.set("X-User-Role", "REVIEWER"); headers.set("Idempotency-Key", "t817-media");
        error(http.exchange(base("INVALID") + "/review", HttpMethod.POST, new HttpEntity<>(body("INVALID", 0).toString(), headers), JsonNode.class), 400, "PARAM_VALIDATION_ERROR");
        error(submit("INVALID", body("INVALID", 0).put("processingRevision", 0), "t817-zero-revision"), 400, "PARAM_VALIDATION_ERROR");
        absent("t817-media"); absent("t817-zero-revision");
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
