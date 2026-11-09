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

/** 成果登记的真实HTTP验收，材料是人工声明，不能由登记动作生成质量结论。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t811_rework_results", "spring.flyway.default-schema=t811_rework_results",
        "spring.datasource.hikari.schema=t811_rework_results",
        "spring.jpa.properties.hibernate.default_schema=t811_rework_results"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkResultApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T811','DOM','QUALITY_CHECKING')");
        fixture("INVALID", "COMPLETED", "RUNNING", "PROCESSING", true);
    }

    @AfterAll
    void cleanup() {
        try { assertThat(golden()).isEqualTo(goldenBefore); }
        finally { jdbc.execute("DROP SCHEMA t811_rework_results CASCADE"); }
    }

    private String task(String id) { return "TASK-T811-" + id; }
    private String rework(String id) { return "REWORK-T811-" + id; }
    private String issue(String id) { return "ISSUE-T811-" + id; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }

    private void fixture(String id, String taskStatus, String reworkStatus, String issueStatus, boolean lifecycle) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T811',?)", task(id), taskStatus);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM',?,'隔离成果测试')", issue(id), task(id), issueStatus);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?,'原始创建原因')", rework(id), task(id), issue(id), reworkStatus);
        if (lifecycle) jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at)
                VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00','original-handler',TIMESTAMPTZ '2026-11-09 00:01:00+00')
                """, rework(id), task(id), issue(id));
    }

    private void running(String id) { fixture(id, "COMPLETED", "RUNNING", "PROCESSING", true); }

    private ObjectNode body(long version) {
        ObjectNode body = mapper.createObjectNode();
        body.put("expectedVersion", version);
        body.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "release-2");
        body.put("processingComment", "  已人工修正成果，等待检查  ");
        body.putArray("evidenceReferences").add("report:人工处理").add("file:成果说明");
        return body;
    }

    private ResponseEntity<JsonNode> post(String path, String body, String key, String actor, String role) {
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Trace-Id", "trace-t811-test");
        if (key != null) headers.set("Idempotency-Key", key);
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        return http.exchange(path, HttpMethod.POST, new HttpEntity<>(body, headers), JsonNode.class);
    }

    private ResponseEntity<JsonNode> register(String id, JsonNode body, String key) {
        return post(base(id) + "/results", body.toString(), key, "reviewer-test", "REVIEWER");
    }

    private JsonNode success(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        JsonNode envelope = response.getBody(); assertThat(envelope).isNotNull();
        assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("success").asBoolean()).isTrue();
        assertThat(envelope.path("retryable").asBoolean()).isFalse();
        assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t811-test");
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t811-test");
        JsonNode data = envelope.path("data"); assertThat(data.size()).isEqualTo(12);
        assertThat(data.path("operation").asText()).isEqualTo("REGISTER_REWORK_RESULT");
        assertThat(data.path("operationId").asText()).matches("^OPERATION-[A-Z0-9-]+$");
        assertThat(data.path("status").asText()).isEqualTo("RUNNING");
        assertThat(data.path("issueStatus").asText()).isEqualTo("PROCESSING");
        assertThat(data.path("inspectionId").isNull()).isTrue(); assertThat(data.path("reviewId").isNull()).isTrue();
        return data;
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("data").isNull()).isTrue();
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("report:人工处理", "request_hash", "原始创建原因");
    }

    private JsonNode detail(String id) {
        HttpHeaders headers = new HttpHeaders(); headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER");
        var response = http.exchange(base(id), HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        return response.getBody().path("data");
    }

    private List<String> materials(String id) {
        return jdbc.queryForList("SELECT to_jsonb(p)::text FROM rework_processing_revisions p WHERE rework_task_id=? ORDER BY processing_revision", String.class, rework(id));
    }

    private Map<String,Object> state(String id) {
        return jdbc.queryForMap("""
                SELECT t.status AS task_status,t.version,r.status AS rework_status,r.reason,q.status AS issue_status,l.started_by,l.started_at
                FROM production_tasks t JOIN rework_tasks r ON r.task_id=t.task_id JOIN quality_issues q ON q.issue_id=r.source_issue_id
                LEFT JOIN rework_lifecycles l ON l.rework_task_id=r.rework_task_id WHERE r.rework_task_id=?
                """, rework(id));
    }

    private void absent(String key) {
        for (String table : List.of("idempotency_records", "rework_operation_receipts")) {
            assertThat(jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE idempotency_key=?", Integer.class, key)).isZero();
        }
        assertThat(audits(key)).isZero();
    }

    private int audits(String key) {
        return jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')", Integer.class, key);
    }

    @Test
    void recordsExactMaterialsWithServerIdentityAndTimeWithoutCompletingOrApproving() throws Exception {
        running("SUCCESS"); var before = state("SUCCESS"); Instant earliest = Instant.now();
        JsonNode receipt = success(register("SUCCESS", body(0), "t811-success")); Instant latest = Instant.now();
        assertThat(receipt.path("processingRevision").asLong()).isEqualTo(1);
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(1);
        assertThat(receipt.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(receipt.path("previousReworkTaskId").isNull()).isTrue();
        var expected = new java.util.HashMap<>(before); expected.put("version", 1L);
        assertThat(state("SUCCESS")).isEqualTo(expected);
        JsonNode current = detail("SUCCESS"); var processing = current.path("processing");
        assertThat(processing.path("artifact")).isEqualTo(body(0).path("artifact"));
        assertThat(processing.path("processingComment")).isEqualTo(body(0).path("processingComment"));
        assertThat(processing.path("evidenceReferences")).isEqualTo(body(0).path("evidenceReferences"));
        assertThat(processing.path("registeredBy").asText()).isEqualTo("reviewer-test");
        assertThat(Instant.parse(processing.path("registeredAt").asText())).isBetween(earliest, latest);
        assertThat(current.path("inspection").isNull()).isTrue(); assertThat(current.path("review").isNull()).isTrue();
        assertThat(current.path("allowedActions").toString()).contains("REGISTER_REWORK_INSPECTION");
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key='t811-success'", String.class))).isEqualTo(receipt);
        var audit = jdbc.queryForMap("SELECT actor_user_id,before_state,after_state FROM operation_logs WHERE operation_id=?", receipt.path("operationId").asText());
        assertThat(audit).containsEntry("actor_user_id", "reviewer-test");
        assertThat(mapper.readTree(audit.get("before_state").toString()).path("processingRevision").isNull()).isTrue();
        assertThat(mapper.readTree(audit.get("after_state").toString()).path("processingRevision").asLong()).isEqualTo(1);
        assertThat(audit.toString()).doesNotContain("report:人工处理", "已人工修正", "t811-success");
    }

    @Test
    void appendsEvenForTheSameArtifactAndPreservesOldInspectionAndReviewWithoutReusingThem() {
        running("REVISIONS");
        JsonNode original = success(register("REVISIONS", body(0), "t811-revision-1"));
        jdbc.update("""
                INSERT INTO rework_inspections VALUES ('INSPECTION-T811-OLD',?,1,1,'PASSED',
                '[{"checkItem":"坐标系","result":"PASSED","comment":"人工检查","evidenceReferences":["report:old"]}]',
                'inspector-test',TIMESTAMPTZ '2026-11-09 00:02:00+00')
                """, rework("REVISIONS"));
        jdbc.update("""
                INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at)
                VALUES ('REVIEW-T811-OLD',?,1,'INSPECTION-T811-OLD',1,'APPROVED','历史夹具复核','reviewer-test',TIMESTAMPTZ '2026-11-09 00:03:00+00')
                """, rework("REVISIONS"));
        var old = materials("REVISIONS");
        var inspectionBefore = jdbc.queryForList("SELECT * FROM rework_inspections WHERE rework_task_id=?", rework("REVISIONS"));
        var reviewBefore = jdbc.queryForList("SELECT * FROM rework_reviews WHERE rework_task_id=?", rework("REVISIONS"));
        var changed = body(1); changed.put("processingComment", "同一版本文本，补充实际处理说明");
        JsonNode next = success(register("REVISIONS", changed, "t811-revision-2"));
        assertThat(next.path("processingRevision").asLong()).isEqualTo(2);
        assertThat(materials("REVISIONS")).hasSize(2).startsWith(old.toArray(String[]::new));
        assertThat(jdbc.queryForList("SELECT * FROM rework_inspections WHERE rework_task_id=?", rework("REVISIONS"))).isEqualTo(inspectionBefore);
        assertThat(jdbc.queryForList("SELECT * FROM rework_reviews WHERE rework_task_id=?", rework("REVISIONS"))).isEqualTo(reviewBefore);
        var current = detail("REVISIONS");
        assertThat(current.path("processing").path("processingRevision").asLong()).isEqualTo(2);
        assertThat(current.path("inspection").isNull()).isTrue(); assertThat(current.path("review").isNull()).isTrue();
        assertThat(success(register("REVISIONS", body(0), "t811-revision-1"))).isEqualTo(original);
        assertThat(state("REVISIONS")).containsEntry("version", 2L);
    }

    static Stream<String> invalidBodies() {
        String valid = "{\"expectedVersion\":0,\"artifact\":{\"artifactId\":\"A\",\"artifactVersion\":\"v1\"},\"processingComment\":\"处理说明\",\"evidenceReferences\":[\"report:a\"]}";
        return Stream.concat(Stream.of("null", "[]", "{}", valid + "{}", valid.replace("0,", "0,\"expectedVersion\":0,"),
                valid.replace("\"artifactId\":\"A\"", "\"artifactId\":\"A\",\"artifactId\":\"B\""),
                valid.replace("\"artifactVersion\":\"v1\"", "\"artifactVersion\":\"v1\",\"path\":\"x\""),
                valid.replace("\"expectedVersion\":0", "\"confirmed\":true"), valid.replace("\"artifact\":{", "\"registeredBy\":\"spoof\",\"artifact\":{"),
                valid.replace("\"artifactId\":\"A\",", ""), valid.replace("\"artifactId\":\"A\"", "\"artifactId\":null"),
                valid.replace("\"artifactId\":\"A\"", "\"artifactId\":123"), valid.replace("\"v1\"", "\" v1\""),
                valid.replace("\"处理说明\"", "null"), valid.replace("\"处理说明\"", "\" \\t\""),
                valid.replace("[\"report:a\"]", "[]"), valid.replace("[\"report:a\"]", "[null]"),
                valid.replace("[\"report:a\"]", "[true]"), valid.replace("[\"report:a\"]", "\"report:a\""),
                valid.replace("report:a", " report:a"), valid.replace("report:a", "report:a\\u0000"),
                valid.replace("处理说明", "\\ud800")),
                Stream.of("-1", "9007199254740992", "9223372036854775808", "\"0\"", "true", "0.0", "null")
                        .map(version -> valid.replace("\"expectedVersion\":0", "\"expectedVersion\":" + version)));
    }

    @ParameterizedTest
    @MethodSource("invalidBodies")
    void rejectsMissingAmbiguousCoercedOrSelfReportedMaterialsBeforeWriting(String body) {
        String key = "t811-invalid";
        error(post(base("INVALID") + "/results", body, key, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        absent(key); assertThat(materials("INVALID")).isEmpty();
    }

    static Stream<Arguments> textLimits() {
        return Stream.of(Arguments.of("artifactId", 256), Arguments.of("artifactVersion", 128),
                Arguments.of("processingComment", 1000), Arguments.of("evidenceReferences", 1024));
    }

    private void setText(ObjectNode body, String field, String value) {
        if (field.startsWith("artifact")) ((ObjectNode) body.get("artifact")).put(field, value);
        else if (field.equals("evidenceReferences")) body.putArray(field).add(value);
        else body.put(field, value);
    }

    @ParameterizedTest
    @MethodSource("textLimits")
    void enforcesUtf16LimitsAndPreservesChineseAndNonBmpText(String field, int limit) {
        for (String prefix : List.of("中", "😀")) {
            String id = "LIMIT-" + field.toUpperCase(Locale.ROOT) + (prefix.length() == 1 ? "-CN" : "-EMOJI"); running(id);
            String text = prefix.repeat(limit / prefix.length()); var payload = body(0); setText(payload, field, text);
            success(register(id, payload, "t811-" + id));
            JsonNode saved = detail(id).path("processing");
            JsonNode actual = field.startsWith("artifact") ? saved.path("artifact").path(field)
                    : field.equals("evidenceReferences") ? saved.path(field).get(0) : saved.path(field);
            assertThat(actual.asText()).isEqualTo(text);
            var tooLong = body(1); setText(tooLong, field, text + "中");
            error(register(id, tooLong, "t811-over-" + id), 400, "PARAM_VALIDATION_ERROR"); absent("t811-over-" + id);
            assertThat(materials(id)).hasSize(1);
        }
    }

    @Test
    void enforcesReferenceCountAndExactWhitespaceWithoutFetchingReferences() {
        running("REFS"); var payload = body(0); var refs = payload.putArray("evidenceReferences");
        for (int i = 0; i < 20; i++) refs.add("https://invalid.example/evidence-" + i);
        success(register("REFS", payload, "t811-refs"));
        payload.put("expectedVersion", 1); refs.add("report:21");
        error(register("REFS", payload, "t811-refs-many"), 400, "PARAM_VALIDATION_ERROR"); absent("t811-refs-many");
        for (String whitespace : List.of(" ", "\t", "\u001c", "\u1680", "\u2003", "\u3000")) {
            for (String field : List.of("artifactId", "artifactVersion", "evidenceReferences", "processingComment")) {
                var invalid = body(0); setText(invalid, field, field.equals("processingComment") ? whitespace : whitespace + "x");
                error(register("INVALID", invalid, "t811-whitespace"), 400, "PARAM_VALIDATION_ERROR"); absent("t811-whitespace");
            }
        }
    }

    static Stream<Arguments> invalidCodeUnits() {
        return Stream.of("artifactId", "artifactVersion", "processingComment", "evidenceReferences")
                .flatMap(field -> Stream.of(0, 0xd800, 0xdc00).map(unit -> Arguments.of(field, unit)));
    }

    @ParameterizedTest
    @MethodSource("invalidCodeUnits")
    void rejectsTextThatCannotBeStoredLosslessly(String field, int unit) throws Exception {
        var invalid = body(0); setText(invalid, field, "x" + (char) unit);
        String json = mapper.writer().with(JsonGenerator.Feature.ESCAPE_NON_ASCII).writeValueAsString(invalid);
        error(post(base("INVALID") + "/results", json, "t811-code-unit", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        absent("t811-code-unit"); assertThat(materials("INVALID")).isEmpty();
    }

    @Test
    void rejectsNonJsonAndUnsafeIdentifiersOrKeysWithoutWriting() {
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.TEXT_PLAIN);
        headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER"); headers.set("Idempotency-Key", "t811-content");
        error(http.exchange(base("INVALID") + "/results", HttpMethod.POST, new HttpEntity<>(body(0).toString(), headers), JsonNode.class), 400, "PARAM_VALIDATION_ERROR"); absent("t811-content");
        error(post(base("INVALID").replace(task("INVALID"), "TASK-lower") + "/results", body(0).toString(), "t811-id", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); absent("t811-id");
        error(post(base("INVALID") + "/results", body(0).toString(), "unsafe/key", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); absent("unsafe/key");
    }

    static Stream<Arguments> illegalStates() {
        return Stream.of(Arguments.of("FAILED", "RUNNING", "PROCESSING"), Arguments.of("RUNNING", "RUNNING", "PROCESSING"),
                Arguments.of("COMPLETED", "PENDING", "OPEN"), Arguments.of("COMPLETED", "BLOCKED", "PROCESSING"),
                Arguments.of("COMPLETED", "FAILED", "PROCESSING"), Arguments.of("COMPLETED", "COMPLETED", "RESOLVED"),
                Arguments.of("COMPLETED", "RUNNING", "OPEN"), Arguments.of("COMPLETED", "RUNNING", "CLOSED"));
    }

    @ParameterizedTest
    @MethodSource("illegalStates")
    void rejectsNonRunningOrInvalidParentAndIssueStates(String taskState, String reworkState, String issueState) {
        String id = taskState + "-" + reworkState + "-" + issueState; fixture(id, taskState, reworkState, issueState, true);
        var before = state(id); String key = "t811-state-" + id;
        error(register(id, body(0), key), 409, "BUSINESS_CONFLICT"); absent(key);
        assertThat(state(id)).isEqualTo(before); assertThat(materials(id)).isEmpty();
    }

    @Test
    void validatesIdentityOwnershipAndLegacyWithoutInventingLifecycle() {
        running("OWNER"); running("OTHER"); fixture("LEGACY", "COMPLETED", "RUNNING", "PROCESSING", false);
        String key = "t811-owner"; String path = base("OWNER") + "/results";
        error(post(path, body(0).toString(), key, null, "REVIEWER"), 401, "PERMISSION_DENIED"); absent(key);
        error(post(path, body(0).toString(), key, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED"); absent(key);
        error(post(path, body(0).toString(), null, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(register("MISSING", body(0), key), 404, "RESOURCE_NOT_FOUND"); absent(key);
        error(post("/api/tasks/" + task("OTHER") + "/reworks/" + rework("OWNER") + "/results", body(0).toString(), key, "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT"); absent(key);
        error(post(base("OWNER").replace(rework("OWNER"), "REWORK-T811-MISSING") + "/results", body(0).toString(), key, "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND"); absent(key);
        error(register("LEGACY", body(0), key), 409, "BUSINESS_CONFLICT"); absent(key);
        jdbc.update("UPDATE rework_tasks SET source_issue_id=NULL WHERE rework_task_id=?", rework("LEGACY"));
        error(register("LEGACY", body(0), key), 409, "BUSINESS_CONFLICT"); absent(key);
        assertThat(materials("OWNER")).isEmpty(); assertThat(materials("LEGACY")).isEmpty();
    }

    @Test
    void rejectsSupersededRoundAndExhaustedTaskOrRevisionWithoutOverflow() {
        running("SUCCESSOR");
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','下一轮')", rework("NEXT"), task("SUCCESSOR"), issue("SUCCESSOR"));
        jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at)
                VALUES (?,?,?,2,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')
                """, rework("NEXT"), task("SUCCESSOR"), issue("SUCCESSOR"), rework("SUCCESSOR"));
        error(register("SUCCESSOR", body(0), "t811-successor"), 409, "BUSINESS_CONFLICT"); absent("t811-successor");
        running("MAXVERSION"); jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?", task("MAXVERSION"));
        error(register("MAXVERSION", body(9007199254740991L), "t811-maxversion"), 409, "BUSINESS_CONFLICT"); absent("t811-maxversion");
        running("MAXREVISION");
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,9007199254740991,'A','v1','说明','[\"report:a\"]','reviewer-test',now())", rework("MAXREVISION"));
        var before = materials("MAXREVISION");
        error(register("MAXREVISION", body(0), "t811-maxrevision"), 409, "BUSINESS_CONFLICT"); absent("t811-maxrevision");
        assertThat(materials("MAXREVISION")).isEqualTo(before); assertThat(state("MAXREVISION")).containsEntry("version", 0L);
    }

    @Test
    void acceptsLastSafeRevisionAndVersionButRejectsStaleSubmissions() {
        running("LASTSAFE");
        jdbc.update("UPDATE production_tasks SET version=9007199254740990 WHERE task_id=?", task("LASTSAFE"));
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,9007199254740990,'A','v1','边界夹具','[\"report:a\"]','reviewer-test',now())", rework("LASTSAFE"));
        error(register("LASTSAFE", body(0), "t811-stale"), 409, "BUSINESS_CONFLICT"); absent("t811-stale");
        var receipt = success(register("LASTSAFE", body(9007199254740990L), "t811-lastsafe"));
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(9007199254740991L);
        assertThat(receipt.path("processingRevision").asLong()).isEqualTo(9007199254740991L);
    }

    @Test
    void bindsEveryRequestFieldAndActorAndReplaysOriginalAfterBlocking() {
        running("BIND"); String key = "t811-bind"; var original = success(register("BIND", body(0), key));
        for (String field : List.of("artifactId", "artifactVersion", "processingComment", "evidenceReferences")) {
            var changed = body(0); setText(changed, field, "changed");
            error(register("BIND", changed, key), 409, "BUSINESS_CONFLICT");
        }
        var reorderedRefs = body(0); reorderedRefs.putArray("evidenceReferences").add("file:成果说明").add("report:人工处理");
        error(register("BIND", reorderedRefs, key), 409, "BUSINESS_CONFLICT");
        error(register("BIND", body(1), key), 409, "BUSINESS_CONFLICT");
        error(post(base("BIND") + "/results", body(0).toString(), key, "other-reviewer", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(post(base("BIND") + "/results", body(0).toString(), key, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        running("BINDOTHER");
        error(register("BINDOTHER", body(0), key), 409, "BUSINESS_CONFLICT");
        assertThat(materials("BINDOTHER")).isEmpty(); assertThat(state("BINDOTHER")).containsEntry("version", 0L);
        error(post(base("BIND") + "/block", "{\"expectedVersion\":1,\"reason\":\"不可复用成果登记的键\"}", key, "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        var blocked = post(base("BIND") + "/block", "{\"expectedVersion\":1,\"reason\":\"等待材料\"}", "t811-bind-block", "reviewer-test", "REVIEWER");
        assertThat(blocked.getStatusCode().value()).isEqualTo(200);
        assertThat(success(register("BIND", body(0), key))).isEqualTo(original);
        assertThat(state("BIND")).containsEntry("version", 2L).containsEntry("rework_status", "BLOCKED");
        assertThat(materials("BIND")).hasSize(1); assertThat(audits(key)).isEqualTo(1);
        error(register("BIND", body(2), "t811-bind-new"), 409, "BUSINESS_CONFLICT"); absent("t811-bind-new");
    }

    @ParameterizedTest
    @ValueSource(strings = {"same-key", "different-key"})
    void concurrentRegistrationDoesNotAllocateDuplicateOrExtraRevisions(String mode) throws Exception {
        String id = "RACE-" + mode.toUpperCase(Locale.ROOT); running(id);
        String a = "t811-" + id; String b = mode.equals("same-key") ? a : a + "-other";
        var responses = concurrent(() -> register(id, body(0), a), () -> register(id, body(0), b));
        if (a.equals(b)) assertThat(success(responses.get(0))).isEqualTo(success(responses.get(1)));
        else {
            assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
            int winner = responses.get(0).getStatusCode().value() == 200 ? 0 : 1;
            success(responses.get(winner)); error(responses.get(1 - winner), 409, "BUSINESS_CONFLICT"); absent(winner == 0 ? b : a);
        }
        assertThat(materials(id)).hasSize(1); assertThat(state(id)).containsEntry("version", 1L);
        assertThat(detail(id).path("processing").path("processingRevision").asLong()).isEqualTo(1);
    }

    @Test
    void registrationAndBlockingShareOneVersionAndCannotBothCommit() throws Exception {
        running("BLOCKRACE");
        var responses = concurrent(() -> register("BLOCKRACE", body(0), "t811-race-result"),
                () -> post(base("BLOCKRACE") + "/block", "{\"expectedVersion\":0,\"reason\":\"人工阻塞\"}", "t811-race-block", "reviewer-test", "REVIEWER"));
        assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        assertThat(state("BLOCKRACE")).containsEntry("version", 1L).containsEntry("issue_status", "PROCESSING");
        if (responses.get(0).getStatusCode().value() == 200) { success(responses.get(0)); absent("t811-race-block"); assertThat(materials("BLOCKRACE")).hasSize(1); }
        else { absent("t811-race-result"); assertThat(materials("BLOCKRACE")).isEmpty(); assertThat(state("BLOCKRACE")).containsEntry("rework_status", "BLOCKED"); }
    }

    @ParameterizedTest
    @ValueSource(strings = {"rework_processing_revisions", "idempotency_records", "operation_logs", "rework_operation_receipts"})
    void anyWriteFailureRollsBackMaterialsVersionReservationAndAudit(String table) {
        String id = "ROLL-" + table.replace("_", "-").toUpperCase(Locale.ROOT); running(id);
        String key = "t811-" + id; var before = state(id);
        jdbc.execute("CREATE FUNCTION t811_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T811 failure'; END $$");
        jdbc.execute("CREATE TRIGGER t811_fail BEFORE " + (table.equals("idempotency_records") ? "UPDATE" : "INSERT") + " ON " + table + " FOR EACH ROW EXECUTE FUNCTION t811_fail()");
        try {
            error(register(id, body(0), key), 500, "INTERNAL_SERVER_ERROR"); absent(key);
            assertThat(state(id)).isEqualTo(before); assertThat(materials(id)).isEmpty();
        } finally { jdbc.execute("DROP TRIGGER t811_fail ON " + table); jdbc.execute("DROP FUNCTION t811_fail()"); }
        success(register(id, body(0), key)); assertThat(materials(id)).hasSize(1); assertThat(audits(key)).isEqualTo(1);
    }

    private List<ResponseEntity<JsonNode>> concurrent(Callable<ResponseEntity<JsonNode>> first,
            Callable<ResponseEntity<JsonNode>> second) throws Exception {
        CountDownLatch ready = new CountDownLatch(2); CountDownLatch go = new CountDownLatch(1);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return first.call(); });
            var b = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return second.call(); });
            assertThat(ready.await(10, TimeUnit.SECONDS)).isTrue(); go.countDown();
            return List.of(a.get(30, TimeUnit.SECONDS), b.get(30, TimeUnit.SECONDS));
        }
    }

    private List<String> golden() {
        return jdbc.queryForList("""
                SELECT 'task:' || to_jsonb(t)::text FROM production_tasks t WHERE task_id='TASK-003'
                UNION ALL SELECT 'issue:' || to_jsonb(q)::text FROM quality_issues q WHERE task_id='TASK-003'
                UNION ALL SELECT 'review:' || to_jsonb(r)::text FROM review_records r WHERE issue_id='ISSUE-001'
                UNION ALL SELECT 'delivery:' || to_jsonb(d)::text FROM delivery_records d WHERE order_id='ORDER-003'
                ORDER BY 1
                """, String.class);
    }
}
