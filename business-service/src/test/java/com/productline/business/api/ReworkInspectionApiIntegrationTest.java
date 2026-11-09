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

/** 人工检查HTTP验收：结论绑定当前材料，通过检查与完成返工不可分开提交。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t812_rework_inspections", "spring.flyway.default-schema=t812_rework_inspections",
        "spring.datasource.hikari.schema=t812_rework_inspections",
        "spring.jpa.properties.hibernate.default_schema=t812_rework_inspections"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkInspectionApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T812','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T812','ORDER-T812','BLOCKED')");
        fixture("INVALID", "COMPLETED", "RUNNING", "PROCESSING", true, true);
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T812'", String.class)).isEqualTo("BLOCKED");
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T812'", String.class)).isEqualTo("QUALITY_CHECKING");
        } finally { jdbc.execute("DROP SCHEMA t812_rework_inspections CASCADE"); }
    }

    private String task(String id) { return "TASK-T812-" + id; }
    private String rework(String id) { return "REWORK-T812-" + id; }
    private String issue(String id) { return "ISSUE-T812-" + id; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }

    private void fixture(String id, String taskState, String reworkState, String issueState, boolean lifecycle, boolean material) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T812',?)", task(id), taskState);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM',?,'隔离检查问题')", issue(id), task(id), issueState);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?,'创建原因保持')", rework(id), task(id), issue(id), reworkState);
        if (lifecycle) {
            jdbc.update("""
                    INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at)
                    VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00','original-handler',TIMESTAMPTZ '2026-11-09 00:01:00+00')
                    """, rework(id), task(id), issue(id));
            if (material) jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,1,'成果-A','v1','人工处理说明','[\"report:material\"]','handler-test',now())", rework(id));
        }
    }

    private void running(String id) { fixture(id, "COMPLETED", "RUNNING", "PROCESSING", true, true); }

    private ObjectNode body(long version, long revision, String result) {
        ObjectNode body = mapper.createObjectNode(); body.put("expectedVersion", version); body.put("processingRevision", revision);
        var item = body.putArray("items").addObject(); item.put("checkItem", "  坐标系人工核对  "); item.put("result", result);
        item.put("comment", "  根据实际成果记录检查意见  "); item.putArray("evidenceReferences").add("report:inspection");
        return body;
    }

    private ResponseEntity<JsonNode> post(String path, String body, String key, String actor, String role) {
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON); headers.set("X-Trace-Id", "trace-t812-test");
        if (key != null) headers.set("Idempotency-Key", key);
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        return http.exchange(path, HttpMethod.POST, new HttpEntity<>(body, headers), JsonNode.class);
    }

    private ResponseEntity<JsonNode> inspect(String id, JsonNode body, String key) {
        return post(base(id) + "/inspections", body.toString(), key, "reviewer-test", "REVIEWER");
    }

    private JsonNode success(ResponseEntity<JsonNode> response, String result) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        var envelope = response.getBody(); assertThat(envelope).isNotNull(); assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue(); assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse();
        assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t812-test");
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t812-test");
        var data = envelope.path("data"); assertThat(data.size()).isEqualTo(12);
        assertThat(data.path("operation").asText()).isEqualTo("REGISTER_REWORK_INSPECTION");
        assertThat(data.path("inspectionId").asText()).matches("^INSPECTION-[A-Z0-9-]+$");
        assertThat(data.path("status").asText()).isEqualTo(result.equals("PASSED") ? "COMPLETED" : "RUNNING");
        assertThat(data.path("issueStatus").asText()).isEqualTo(result.equals("PASSED") ? "RESOLVED" : "PROCESSING");
        assertThat(data.path("reviewId").isNull()).isTrue(); return data;
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("data").isNull()).isTrue(); assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("report:inspection", "request_hash", "创建原因保持");
    }

    private JsonNode detail(String id) {
        HttpHeaders headers = new HttpHeaders(); headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER");
        var response = http.exchange(base(id), HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200); return response.getBody().path("data");
    }

    private Map<String,Object> state(String id) {
        return jdbc.queryForMap("""
                SELECT t.status AS task_status,t.version,r.status AS rework_status,r.reason,q.status AS issue_status,l.started_by,l.started_at
                FROM production_tasks t JOIN rework_tasks r ON r.task_id=t.task_id JOIN quality_issues q ON q.issue_id=r.source_issue_id
                LEFT JOIN rework_lifecycles l ON l.rework_task_id=r.rework_task_id WHERE r.rework_task_id=?
                """, rework(id));
    }

    private List<String> inspections(String id) {
        return jdbc.queryForList("SELECT to_jsonb(i)::text FROM rework_inspections i WHERE rework_task_id=? ORDER BY inspection_sequence", String.class, rework(id));
    }

    private int audits(String key) {
        return jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')", Integer.class, key);
    }

    private void absent(String key) {
        for (String table : List.of("idempotency_records", "rework_operation_receipts")) {
            assertThat(jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE idempotency_key=?", Integer.class, key)).isZero();
        }
        assertThat(audits(key)).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"PASSED", "FAILED"})
    void storesManualItemsServerIdentityTimeAndCorrectAtomicOutcome(String result) throws Exception {
        String id = "SUCCESS-" + result; running(id); var before = state(id); Instant earliest = Instant.now();
        var payload = body(0, 1, result);
        var receipt = success(inspect(id, payload, "t812-" + id), result); Instant latest = Instant.now();
        assertThat(receipt.path("processingRevision").asLong()).isEqualTo(1); assertThat(receipt.path("taskVersion").asLong()).isEqualTo(1);
        assertThat(state(id)).containsEntry("task_status", "COMPLETED").containsEntry("version", 1L)
                .containsEntry("reason", before.get("reason")).containsEntry("started_by", before.get("started_by")).containsEntry("started_at", before.get("started_at"));
        var current = detail(id); var check = current.path("inspection");
        assertThat(check.path("inspectionId")).isEqualTo(receipt.path("inspectionId"));
        assertThat(check.path("inspectionSequence").asLong()).isEqualTo(1); assertThat(check.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(check.path("items")).isEqualTo(payload.path("items")); assertThat(check.path("result").asText()).isEqualTo(result);
        assertThat(check.path("inspectorId").asText()).isEqualTo("reviewer-test");
        assertThat(Instant.parse(check.path("inspectedAt").asText())).isBetween(earliest, latest);
        assertThat(current.path("review").isNull()).isTrue();
        assertThat(current.path("allowedActions").toString()).contains(result.equals("PASSED") ? "SUBMIT_REWORK_REVIEW" : "REGISTER_REWORK_INSPECTION");
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key=?", String.class, "t812-" + id))).isEqualTo(receipt);
        var audit = jdbc.queryForMap("SELECT before_state,after_state,actor_user_id FROM operation_logs WHERE operation_id=?", receipt.path("operationId").asText());
        assertThat(audit).containsEntry("actor_user_id", "reviewer-test");
        assertThat(mapper.readTree(audit.get("after_state").toString()).path("inspectionId")).isEqualTo(receipt.path("inspectionId"));
        assertThat(audit.toString()).doesNotContain("report:inspection", "根据实际成果", "t812-" + id);
        if (result.equals("PASSED")) { error(inspect(id, body(1, 1, result), "t812-terminal"), 409, "BUSINESS_CONFLICT"); absent("t812-terminal"); }
    }

    @Test
    void anyFailedItemDeterminesFailureAndRepeatedChecksPreserveHistory() {
        running("MIXED"); var mixed = body(0, 1, "PASSED");
        mixed.withArray("items").add(body(0, 1, "FAILED").path("items").get(0));
        var first = success(inspect("MIXED", mixed, "t812-mixed-1"), "FAILED"); var old = inspections("MIXED");
        var next = success(inspect("MIXED", body(1, 1, "FAILED"), "t812-mixed-2"), "FAILED");
        assertThat(next.path("inspectionId")).isNotEqualTo(first.path("inspectionId"));
        assertThat(inspections("MIXED")).hasSize(2).startsWith(old.toArray(String[]::new));
        assertThat(detail("MIXED").path("inspection").path("inspectionSequence").asLong()).isEqualTo(2);
        assertThat(state("MIXED")).containsEntry("rework_status", "RUNNING").containsEntry("issue_status", "PROCESSING").containsEntry("version", 2L);
    }

    @Test
    void realHttpResultRegistrationBindsChecksOnlyToCurrentMaterial() {
        fixture("REVISION", "COMPLETED", "RUNNING", "PROCESSING", true, false);
        String material = "{\"expectedVersion\":0,\"artifact\":{\"artifactId\":\"成果-A\",\"artifactVersion\":\"v1\"},\"processingComment\":\"实际处理\",\"evidenceReferences\":[\"report:material\"]}";
        assertThat(post(base("REVISION") + "/results", material, "t812-material-1", "reviewer-test", "REVIEWER").getStatusCode().value()).isEqualTo(200);
        success(inspect("REVISION", body(1, 1, "FAILED"), "t812-old-check"), "FAILED"); var old = inspections("REVISION");
        assertThat(post(base("REVISION") + "/results", material.replace("\"expectedVersion\":0", "\"expectedVersion\":2"), "t812-material-2", "reviewer-test", "REVIEWER").getStatusCode().value()).isEqualTo(200);
        error(inspect("REVISION", body(3, 1, "PASSED"), "t812-wrong-revision"), 409, "BUSINESS_CONFLICT"); absent("t812-wrong-revision");
        assertThat(detail("REVISION").path("inspection").isNull()).isTrue(); assertThat(inspections("REVISION")).isEqualTo(old);
        success(inspect("REVISION", body(3, 2, "PASSED"), "t812-current-check"), "PASSED");
        var current = detail("REVISION"); assertThat(current.path("inspection").path("processingRevision").asLong()).isEqualTo(2);
        assertThat(current.path("inspection").path("inspectionSequence").asLong()).isEqualTo(2);
        assertThat(state("REVISION")).containsEntry("version", 4L).containsEntry("issue_status", "RESOLVED");
    }

    static Stream<String> invalidBodies() {
        String valid = "{\"expectedVersion\":0,\"processingRevision\":1,\"items\":[{\"checkItem\":\"坐标系\",\"result\":\"PASSED\",\"comment\":\"人工核对\",\"evidenceReferences\":[\"report:a\"]}]}";
        return Stream.concat(Stream.of("null", "[]", "{}", valid + "{}", valid.replace("0,", "0,\"expectedVersion\":0,"),
                valid.replace("\"checkItem\":\"坐标系\"", "\"checkItem\":\"坐标系\",\"checkItem\":\"重复\""),
                valid.replace("\"expectedVersion\":0", "\"confirmed\":true"), valid.replace("\"items\":", "\"result\":\"PASSED\",\"items\":"),
                valid.replace("\"comment\":\"人工核对\"", "\"inspectorId\":\"spoof\""),
                valid.replace("\"processingRevision\":1", "\"processingRevision\":0"), valid.replace("\"processingRevision\":1", "\"processingRevision\":\"1\""),
                valid.replace("\"processingRevision\":1", "\"processingRevision\":-1"), valid.replace("\"processingRevision\":1", "\"processingRevision\":null"),
                valid.replace("\"processingRevision\":1", "\"processingRevision\":true"), valid.replace("\"processingRevision\":1", "\"processingRevision\":1.0"),
                valid.replace("\"processingRevision\":1", "\"processingRevision\":9007199254740992"),
                valid.replace("\"PASSED\"", "\"passed\""), valid.replace("\"PASSED\"", "null"), valid.replace("\"坐标系\"", "123"),
                valid.replace("\"人工核对\"", "\" \\t\""), valid.replace("[\"report:a\"]", "[]"), valid.replace("[\"report:a\"]", "[null]"),
                valid.replace("[\"report:a\"]", "[1]"), valid.replace("report:a", " report:a"), valid.replace("[\"report:a\"]", "\"report:a\"")),
                Stream.of("-1", "9007199254740992", "9223372036854775808", "\"0\"", "true", "0.0", "null")
                        .map(version -> valid.replace("\"expectedVersion\":0", "\"expectedVersion\":" + version)));
    }

    @ParameterizedTest
    @MethodSource("invalidBodies")
    void rejectsIncompleteOrAmbiguousInputsAndSelfReportedFacts(String body) {
        error(post(base("INVALID") + "/inspections", body, "t812-invalid", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        absent("t812-invalid"); assertThat(inspections("INVALID")).isEmpty();
    }

    static Stream<Arguments> limits() { return Stream.of(Arguments.of("checkItem", 128), Arguments.of("comment", 1000), Arguments.of("evidenceReferences", 1024)); }

    private void setText(ObjectNode payload, String field, String value) {
        var item = (ObjectNode) payload.path("items").get(0);
        if (field.equals("evidenceReferences")) item.putArray(field).add(value); else item.put(field, value);
    }

    @ParameterizedTest
    @MethodSource("limits")
    void enforcesUtf16LimitsAndPreservesNonBmpAndChinese(String field, int limit) {
        for (String unit : List.of("中", "😀")) {
            String id = "LIMIT-" + field.toUpperCase(Locale.ROOT) + "-" + unit.length(); running(id);
            var payload = body(0, 1, "FAILED"); String value = unit.repeat(limit / unit.length()); setText(payload, field, value);
            success(inspect(id, payload, "t812-" + id), "FAILED");
            var saved = detail(id).path("inspection").path("items").get(0).path(field);
            assertThat(field.equals("evidenceReferences") ? saved.get(0).asText() : saved.asText()).isEqualTo(value);
            payload.put("expectedVersion", 1); setText(payload, field, value + "中");
            error(inspect(id, payload, "t812-over-" + id), 400, "PARAM_VALIDATION_ERROR"); absent("t812-over-" + id);
        }
    }

    static Stream<Arguments> codeUnits() {
        return Stream.of("checkItem", "comment", "evidenceReferences").flatMap(field -> Stream.of(0, 0xd800, 0xdc00).map(unit -> Arguments.of(field, unit)));
    }

    @ParameterizedTest
    @MethodSource("codeUnits")
    void rejectsTextThatCannotBeStoredLosslessly(String field, int unit) throws Exception {
        var payload = body(0, 1, "PASSED"); setText(payload, field, "x" + (char) unit);
        error(post(base("INVALID") + "/inspections", mapper.writer().with(JsonGenerator.Feature.ESCAPE_NON_ASCII).writeValueAsString(payload),
                "t812-code-unit", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); absent("t812-code-unit");
    }

    @Test
    void enforcesItemAndEvidenceCountsAndRequiresEvidenceForEveryItem() {
        running("COUNTS"); var payload = body(0, 1, "FAILED"); var items = payload.withArray("items"); var first = items.get(0).deepCopy();
        for (int i = 1; i < 50; i++) items.add(first.deepCopy());
        var refs = ((ObjectNode) items.get(0)).putArray("evidenceReferences"); for (int i = 0; i < 20; i++) refs.add("report:" + i);
        success(inspect("COUNTS", payload, "t812-counts"), "FAILED"); payload.put("expectedVersion", 1);
        items.add(first.deepCopy()); error(inspect("COUNTS", payload, "t812-many-items"), 400, "PARAM_VALIDATION_ERROR"); absent("t812-many-items");
        items.remove(50); refs.add("report:21"); error(inspect("COUNTS", payload, "t812-many-refs"), 400, "PARAM_VALIDATION_ERROR"); absent("t812-many-refs");
        var empty = body(0, 1, "PASSED"); empty.putArray("items"); error(inspect("INVALID", empty, "t812-empty"), 400, "PARAM_VALIDATION_ERROR"); absent("t812-empty");
    }

    static Stream<Arguments> illegalStates() {
        return Stream.of(Arguments.of("RUNNING", "RUNNING", "PROCESSING"), Arguments.of("FAILED", "RUNNING", "PROCESSING"),
                Arguments.of("COMPLETED", "PENDING", "OPEN"), Arguments.of("COMPLETED", "BLOCKED", "PROCESSING"),
                Arguments.of("COMPLETED", "FAILED", "PROCESSING"), Arguments.of("COMPLETED", "COMPLETED", "RESOLVED"),
                Arguments.of("COMPLETED", "RUNNING", "OPEN"), Arguments.of("COMPLETED", "RUNNING", "CLOSED"));
    }

    @ParameterizedTest
    @MethodSource("illegalStates")
    void rejectsInvalidTaskReworkOrIssueStates(String taskState, String reworkState, String issueState) {
        String id = taskState + "-" + reworkState + "-" + issueState; fixture(id, taskState, reworkState, issueState, true, true);
        var before = state(id); String key = "t812-" + id;
        error(inspect(id, body(0, 1, "PASSED"), key), 409, "BUSINESS_CONFLICT"); absent(key);
        assertThat(state(id)).isEqualTo(before); assertThat(inspections(id)).isEmpty();
    }

    @Test
    void rejectsWrongOwnershipMissingLifecycleMaterialAndStaleVersion() {
        running("OWNER"); running("OTHER"); fixture("LEGACY", "COMPLETED", "RUNNING", "PROCESSING", false, false);
        fixture("EMPTY", "COMPLETED", "RUNNING", "PROCESSING", true, false);
        String json = body(0, 1, "PASSED").toString(); String key = "t812-boundary";
        error(post(base("OWNER") + "/inspections", json, key, null, "REVIEWER"), 401, "PERMISSION_DENIED"); absent(key);
        error(post(base("OWNER") + "/inspections", json, key, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED"); absent(key);
        error(post(base("OWNER") + "/inspections", json, null, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(inspect("MISSING", body(0, 1, "PASSED"), key), 404, "RESOURCE_NOT_FOUND"); absent(key);
        error(post(base("OWNER").replace(task("OWNER"), task("OTHER")) + "/inspections", json, key, "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT"); absent(key);
        error(post(base("OWNER").replace(rework("OWNER"), rework("MISSING")) + "/inspections", json, key, "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND"); absent(key);
        for (String id : List.of("LEGACY", "EMPTY")) { error(inspect(id, body(0, 1, "PASSED"), key), 409, "BUSINESS_CONFLICT"); absent(key); }
        error(inspect("OWNER", body(1, 1, "PASSED"), key), 409, "BUSINESS_CONFLICT"); absent(key);
        error(inspect("OWNER", body(0, 2, "PASSED"), key), 409, "BUSINESS_CONFLICT"); absent(key);
        jdbc.update("UPDATE rework_tasks SET source_issue_id=NULL WHERE rework_task_id=?", rework("LEGACY"));
        error(inspect("LEGACY", body(0, 1, "PASSED"), key), 409, "BUSINESS_CONFLICT"); absent(key);
    }

    @Test
    void rejectsNonJsonUnsafeIdsAndKeysWithoutReservingOrRecording() {
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.TEXT_PLAIN);
        headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER"); headers.set("Idempotency-Key", "t812-content");
        error(http.exchange(base("INVALID") + "/inspections", HttpMethod.POST, new HttpEntity<>(body(0, 1, "PASSED").toString(), headers), JsonNode.class), 400, "PARAM_VALIDATION_ERROR"); absent("t812-content");
        error(post(base("INVALID").replace(task("INVALID"), "TASK-lower") + "/inspections", body(0, 1, "PASSED").toString(), "t812-id", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); absent("t812-id");
        error(post(base("INVALID") + "/inspections", body(0, 1, "PASSED").toString(), "unsafe/key", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); absent("unsafe/key");
    }

    @Test
    void supersededRoundCannotBeInspected() {
        running("SUCCESSOR");
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','下一轮')", rework("NEXT"), task("SUCCESSOR"), issue("SUCCESSOR"));
        jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at)
                VALUES (?,?,?,2,?,1,'creator-test',now())
                """, rework("NEXT"), task("SUCCESSOR"), issue("SUCCESSOR"), rework("SUCCESSOR"));
        var before = state("SUCCESSOR");
        error(inspect("SUCCESSOR", body(0, 1, "PASSED"), "t812-successor"), 409, "BUSINESS_CONFLICT"); absent("t812-successor");
        assertThat(state("SUCCESSOR")).isEqualTo(before); assertThat(inspections("SUCCESSOR")).isEmpty();
    }

    @Test
    void enforcesSafeVersionAndSequenceLimitsWithoutOverflow() {
        running("LASTSAFE");
        jdbc.update("UPDATE production_tasks SET version=9007199254740990 WHERE task_id=?", task("LASTSAFE"));
        jdbc.update("""
                INSERT INTO rework_inspections VALUES ('INSPECTION-T812-LIMIT',?,1,9007199254740990,'FAILED',
                '[{"checkItem":"坐标系","result":"FAILED","comment":"人工检查边界夹具","evidenceReferences":["report:limit"]}]','inspector-test',now())
                """, rework("LASTSAFE"));
        var receipt = success(inspect("LASTSAFE", body(9007199254740990L, 1, "FAILED"), "t812-lastsafe"), "FAILED");
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(9007199254740991L);
        assertThat(detail("LASTSAFE").path("inspection").path("inspectionSequence").asLong()).isEqualTo(9007199254740991L);
        error(inspect("LASTSAFE", body(9007199254740991L, 1, "FAILED"), "t812-maxversion"), 409, "BUSINESS_CONFLICT"); absent("t812-maxversion");
        running("MAXSEQUENCE");
        jdbc.update("""
                INSERT INTO rework_inspections VALUES ('INSPECTION-T812-MAX',?,1,9007199254740991,'FAILED',
                '[{"checkItem":"坐标系","result":"FAILED","comment":"人工检查边界夹具","evidenceReferences":["report:limit"]}]','inspector-test',now())
                """, rework("MAXSEQUENCE"));
        var before = inspections("MAXSEQUENCE");
        error(inspect("MAXSEQUENCE", body(0, 1, "FAILED"), "t812-maxseq"), 409, "BUSINESS_CONFLICT"); absent("t812-maxseq");
        assertThat(inspections("MAXSEQUENCE")).isEqualTo(before); assertThat(state("MAXSEQUENCE")).containsEntry("version", 0L);
    }

    @Test
    void bindsAllItemsResourceRevisionVersionActorAndOperationAndReplaysOriginalAfterCompletion() {
        running("BIND"); String key = "t812-bind"; var payload = body(0, 1, "FAILED"); var original = success(inspect("BIND", payload, key), "FAILED");
        for (String field : List.of("checkItem", "comment", "evidenceReferences")) {
            var changed = body(0, 1, "FAILED"); setText(changed, field, "changed"); error(inspect("BIND", changed, key), 409, "BUSINESS_CONFLICT");
        }
        error(inspect("BIND", body(0, 1, "PASSED"), key), 409, "BUSINESS_CONFLICT");
        error(inspect("BIND", body(1, 1, "FAILED"), key), 409, "BUSINESS_CONFLICT");
        error(inspect("BIND", body(0, 2, "FAILED"), key), 409, "BUSINESS_CONFLICT");
        error(post(base("BIND") + "/inspections", payload.toString(), key, "other-user", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(post(base("BIND") + "/inspections", payload.toString(), key, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        running("BINDOTHER"); error(inspect("BINDOTHER", payload, key), 409, "BUSINESS_CONFLICT"); assertThat(inspections("BINDOTHER")).isEmpty();
        error(post(base("BIND") + "/block", "{\"expectedVersion\":1,\"reason\":\"不同操作\"}", key, "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        var passed = success(inspect("BIND", body(1, 1, "PASSED"), "t812-bind-pass"), "PASSED");
        assertThat(success(inspect("BIND", payload, key), "FAILED")).isEqualTo(original);
        assertThat(success(inspect("BIND", body(1, 1, "PASSED"), "t812-bind-pass"), "PASSED")).isEqualTo(passed);
        assertThat(state("BIND")).containsEntry("version", 2L).containsEntry("rework_status", "COMPLETED").containsEntry("issue_status", "RESOLVED");
        assertThat(audits(key)).isEqualTo(1); assertThat(inspections("BIND")).hasSize(2);
    }

    static Stream<Arguments> races() {
        return Stream.of("PASSED", "FAILED").flatMap(result -> Stream.of("same", "different").map(mode -> Arguments.of(result, mode)));
    }

    @ParameterizedTest
    @MethodSource("races")
    void concurrentInspectionWritesHaveOneCommitAndStableReplay(String result, String mode) throws Exception {
        String id = "RACE-" + result + "-" + mode.toUpperCase(Locale.ROOT); running(id);
        String a = "t812-" + id; String b = mode.equals("same") ? a : a + "-other";
        var responses = concurrent(() -> inspect(id, body(0, 1, result), a), () -> inspect(id, body(0, 1, result), b));
        if (a.equals(b)) assertThat(success(responses.get(0), result)).isEqualTo(success(responses.get(1), result));
        else {
            assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
            int winner = responses.get(0).getStatusCode().value() == 200 ? 0 : 1;
            success(responses.get(winner), result); error(responses.get(1 - winner), 409, "BUSINESS_CONFLICT"); absent(winner == 0 ? b : a);
        }
        assertThat(inspections(id)).hasSize(1); assertThat(state(id)).containsEntry("version", 1L);
    }

    static Stream<Arguments> faultPoints() {
        return Stream.of("PASSED", "FAILED").flatMap(result -> Stream.of("inspection", "reservation", "audit", "receipt")
                .map(point -> Arguments.of(result, point)));
    }

    @ParameterizedTest
    @MethodSource("faultPoints")
    void writeFailureRollsBackCheckVersionStatesAndOperationRecords(String result, String point) {
        String id = "ROLL-" + result + "-" + point.toUpperCase(Locale.ROOT); running(id); var before = state(id); String key = "t812-" + id;
        String table = switch (point) { case "inspection" -> "rework_inspections"; case "reservation" -> "idempotency_records"; case "audit" -> "operation_logs"; default -> "rework_operation_receipts"; };
        jdbc.execute("CREATE FUNCTION t812_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T812 failure'; END $$");
        jdbc.execute("CREATE TRIGGER t812_fail BEFORE " + (point.equals("reservation") ? "UPDATE" : "INSERT") + " ON " + table + " FOR EACH ROW EXECUTE FUNCTION t812_fail()");
        try {
            error(inspect(id, body(0, 1, result), key), 500, "INTERNAL_SERVER_ERROR"); absent(key);
            assertThat(state(id)).isEqualTo(before); assertThat(inspections(id)).isEmpty();
        } finally { jdbc.execute("DROP TRIGGER t812_fail ON " + table); jdbc.execute("DROP FUNCTION t812_fail()"); }
        success(inspect(id, body(0, 1, result), key), result); assertThat(inspections(id)).hasSize(1); assertThat(audits(key)).isEqualTo(1);
    }

    private List<ResponseEntity<JsonNode>> concurrent(Callable<ResponseEntity<JsonNode>> first, Callable<ResponseEntity<JsonNode>> second) throws Exception {
        CountDownLatch ready = new CountDownLatch(2); CountDownLatch go = new CountDownLatch(1);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return first.call(); });
            var b = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return second.call(); });
            assertThat(ready.await(10, TimeUnit.SECONDS)).isTrue(); go.countDown(); return List.of(a.get(30, TimeUnit.SECONDS), b.get(30, TimeUnit.SECONDS));
        }
    }

    private List<String> golden() {
        return jdbc.queryForList("""
                SELECT 'task:' || to_jsonb(t)::text FROM production_tasks t WHERE task_id='TASK-003'
                UNION ALL SELECT 'issue:' || to_jsonb(q)::text FROM quality_issues q WHERE task_id='TASK-003'
                UNION ALL SELECT 'review:' || to_jsonb(r)::text FROM review_records r WHERE issue_id='ISSUE-001'
                UNION ALL SELECT 'delivery:' || to_jsonb(d)::text FROM delivery_records d WHERE order_id='ORDER-003' ORDER BY 1
                """, String.class);
    }
}
