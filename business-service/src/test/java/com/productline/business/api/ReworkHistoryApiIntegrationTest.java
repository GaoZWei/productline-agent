package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.application.ReworkHistoryCursor;
import com.productline.business.application.ReworkHistoryService;
import com.productline.business.domain.repository.ReworkHistoryRepository;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
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
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.LinkedMultiValueMap;

/** 真实HTTP历史分页、权限、只读快照与登记/检查幂等收口，仅操作独占测试schema。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t815_history", "spring.flyway.default-schema=t815_history",
        "spring.datasource.hikari.schema=t815_history", "spring.jpa.properties.hibernate.default_schema=t815_history"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkHistoryApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private ReworkReadRepository facts;
    @Autowired private ReworkHistoryCursor cursors;
    @Autowired private PlatformTransactionManager manager;
    @Autowired private DataSource dataSource;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T815','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T815','ORDER-T815','BLOCKED')");
        fixture("PAGES", true); fixture("EMPTY", true); fixture("LEGACY", false);
        for (int n = 1; n <= 103; n++) {
            processing("PAGES", n);
            inspection("PAGES", n, n, n == 103 ? "PASSED" : "FAILED");
        }
        jdbc.update("UPDATE rework_tasks SET status='COMPLETED' WHERE rework_task_id=?", rework("PAGES"));
        jdbc.update("UPDATE quality_issues SET status='RESOLVED' WHERE issue_id=?", issue("PAGES"));
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T815'", String.class)).isEqualTo("QUALITY_CHECKING");
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T815'", String.class)).isEqualTo("BLOCKED");
        } finally { jdbc.execute("DROP SCHEMA t815_history CASCADE"); }
    }

    private String task(String id) { return "TASK-T815-" + id; }
    private String rework(String id) { return "REWORK-T815-" + id; }
    private String issue(String id) { return "ISSUE-T815-" + id; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }

    private void fixture(String id, boolean controlled) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T815','COMPLETED')", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','PROCESSING','独立历史查询')", issue(id), task(id));
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'RUNNING','原始返工原因')", rework(id), task(id), issue(id));
        if (controlled) jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at) VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-10 00:00:00+00','handler-test',TIMESTAMPTZ '2026-11-10 00:01:00+00')", rework(id), task(id), issue(id));
    }

    private void processing(String id, long revision) {
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,?,'成果-A','v文字2','  人工处理说明🚀  ','[\"report:原始材料\"]'::jsonb,'handler-test',TIMESTAMPTZ '2026-11-10 00:02:00+00')", rework(id), revision);
    }

    private void inspection(String id, long sequence, long revision, String result) {
        String items = "[{\"checkItem\":\"坐标系\",\"result\":\"" + result + "\",\"comment\":\"  人工检查意见  \",\"evidenceReferences\":[\"report:原始检查\"]}]";
        // ID逆序且时间相同，防止把随机身份或时间误当Java检查序号。
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,?,?,?,?::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-10 00:03:00+00')",
                "CHECK-T815-" + id + "-" + (1000 - sequence), rework(id), revision, sequence, result, items);
    }

    private HttpHeaders headers(String user, String role) {
        var headers = new HttpHeaders(); headers.set("X-Trace-Id", "trace-t815");
        if (user != null) headers.set("X-User-Id", user);
        if (role != null) headers.set("X-User-Role", role);
        return headers;
    }

    private ResponseEntity<JsonNode> get(String path, String user, String role) {
        return http.exchange(path, HttpMethod.GET, new HttpEntity<>(headers(user, role)), JsonNode.class);
    }

    private JsonNode page(String id, String kind, String query) {
        var response = get(base(id) + "/" + kind + query, "reviewer-test", "REVIEWER");
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t815");
        var envelope = response.getBody(); assertThat(envelope).isNotNull(); assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue();
        assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse();
        var data = envelope.path("data"); assertThat(data.size()).isEqualTo(4);
        assertThat(data.path("taskId").asText()).isEqualTo(task(id));
        assertThat(data.path("reworkTaskId").asText()).isEqualTo(rework(id));
        assertThat(data.path("records").isArray()).isTrue(); assertThat(data.has("nextCursor")).isTrue();
        return data;
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("success").asBoolean()).isFalse();
        assertThat(response.getBody().path("data").isNull()).isTrue();
        assertThat(response.getBody().toString()).doesNotContain("report:原始", "人工处理说明", "handler-test", "request_hash");
    }

    private List<String> allFacts() {
        return Stream.of("production_orders", "production_tasks", "quality_issues", "rework_tasks", "review_records",
                "delivery_records", "rework_lifecycles", "rework_processing_revisions", "rework_inspections",
                "rework_reviews", "idempotency_records", "operation_logs", "rework_operation_receipts")
                .flatMap(t -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + t + " r ORDER BY to_jsonb(r)::text", String.class).stream()).toList();
    }

    private List<String> golden() {
        return jdbc.queryForList("""
                SELECT 'order:' || to_jsonb(o)::text FROM production_orders o WHERE order_id='ORDER-003'
                UNION ALL SELECT 'task:' || to_jsonb(t)::text FROM production_tasks t WHERE task_id='TASK-003'
                UNION ALL SELECT 'issue:' || to_jsonb(q)::text FROM quality_issues q WHERE task_id='TASK-003'
                UNION ALL SELECT 'rework:' || to_jsonb(w)::text FROM rework_tasks w WHERE task_id='TASK-003'
                UNION ALL SELECT 'review:' || to_jsonb(r)::text FROM review_records r WHERE issue_id='ISSUE-001'
                UNION ALL SELECT 'delivery:' || to_jsonb(d)::text FROM delivery_records d WHERE order_id='ORDER-003' ORDER BY 1
                """, String.class);
    }

    @ParameterizedTest
    @ValueSource(strings = {"results", "inspections"})
    void returnsAllHistoricalMaterialsInSequenceAndOnlyReads(String kind) {
        var before = allFacts();
        var first = page("PAGES", kind, ""); assertThat(first.path("records").size()).isEqualTo(20);
        String field = kind.equals("results") ? "processingRevision" : "inspectionSequence";
        List<Long> sequences = new ArrayList<>(); JsonNode data = first;
        while (true) {
            for (JsonNode record : data.path("records")) sequences.add(record.path(field).asLong());
            if (data.path("nextCursor").isNull()) break;
            data = page("PAGES", kind, "?limit=20&cursor=" + data.path("nextCursor").asText());
        }
        assertThat(sequences).containsExactlyElementsOf(java.util.stream.LongStream.rangeClosed(1, 103).boxed().toList());
        var record = first.path("records").get(0);
        if (kind.equals("results")) {
            assertThat(record.size()).isEqualTo(6);
            assertThat(record.path("artifact").path("artifactVersion").asText()).isEqualTo("v文字2");
            assertThat(record.path("processingComment").asText()).isEqualTo("  人工处理说明🚀  ");
            assertThat(record.path("evidenceReferences").get(0).asText()).isEqualTo("report:原始材料");
            assertThat(record.path("registeredBy").asText()).isEqualTo("handler-test");
            assertThat(record.path("registeredAt").asText()).isEqualTo("2026-11-10T00:02:00Z");
        } else {
            assertThat(record.size()).isEqualTo(8);
            assertThat(record.path("roundNumber").asLong()).isEqualTo(1);
            assertThat(record.path("inspectionId").asText()).isEqualTo("CHECK-T815-PAGES-999");
            assertThat(record.path("result").asText()).isEqualTo("FAILED");
            assertThat(record.path("processingRevision").asLong()).isEqualTo(1);
            assertThat(record.path("inspectorId").asText()).isEqualTo("inspector-test");
            assertThat(record.path("inspectedAt").asText()).isEqualTo("2026-11-10T00:03:00Z");
            assertThat(record.path("items").get(0).path("comment").asText()).isEqualTo("  人工检查意见  ");
        }
        assertThat(allFacts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"results", "inspections"})
    void supportsLimitOneAndHundredAndEmptyLegacyWithoutManufacturingHistory(String kind) {
        assertThat(page("PAGES", kind, "?limit=1").path("records").size()).isEqualTo(1);
        var first = page("PAGES", kind, "?limit=100"); assertThat(first.path("records").size()).isEqualTo(100);
        var last = page("PAGES", kind, "?cursor=" + first.path("nextCursor").asText());
        assertThat(last.path("records").size()).isEqualTo(3); assertThat(last.path("nextCursor").isNull()).isTrue();
        for (String id : List.of("EMPTY", "LEGACY")) {
            var before = allFacts(); var empty = page(id, kind, "");
            assertThat(empty.path("records").isEmpty()).isTrue(); assertThat(empty.path("nextCursor").isNull()).isTrue();
            assertThat(allFacts()).isEqualTo(before);
        }
    }

    static Stream<Arguments> invalidQueries() {
        return Stream.of("results", "inspections").flatMap(k -> Stream.of("limit=", "limit=0", "limit=-1", "limit=101",
                "limit=1000", "limit=1.0", "limit=true", "limit=01", "limit=9007199254740992", "limit=1&limit=2",
                "cursor=", "cursor=null", "cursor=abc.def", "cursor=x&cursor=y", "offset=0", "status=PASSED", "userId=other")
                .map(q -> Arguments.of(k, q)));
    }

    @ParameterizedTest
    @MethodSource("invalidQueries")
    void rejectsAmbiguousOrMalformedParametersWithoutWriting(String kind, String query) {
        var before = allFacts();
        error(get(base("PAGES") + "/" + kind + "?" + query, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        assertThat(allFacts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"results", "inspections"})
    void rechecksIdentityAndOwnershipForEveryPage(String kind) {
        var before = allFacts(); String path = base("PAGES") + "/" + kind;
        error(get(path, null, "REVIEWER"), 401, "PERMISSION_DENIED");
        error(get(path, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        error(get(path, "reviewer-test", null), 403, "PERMISSION_DENIED");
        error(get(path, "x".repeat(129), "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(get(base("MISSING") + "/" + kind, "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        error(get("/api/tasks/" + task("PAGES") + "/reworks/REWORK-MISSING/" + kind, "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        error(get("/api/tasks/" + task("EMPTY") + "/reworks/" + rework("PAGES") + "/" + kind, "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(get("/api/tasks/task-lower/reworks/" + rework("PAGES") + "/" + kind, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        String token = page("PAGES", kind, "?limit=1").path("nextCursor").asText();
        error(get(path + "?cursor=" + token, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        error(get(path + "?cursor=" + token, null, "REVIEWER"), 401, "PERMISSION_DENIED");
        error(get(path + "?cursor=" + token, "other-user", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(get(base("EMPTY") + "/" + kind + "?cursor=" + token, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        String otherKind = kind.equals("results") ? "inspections" : "results";
        error(get(base("PAGES") + "/" + otherKind + "?cursor=" + token, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        assertThat(allFacts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"results", "inspections"})
    void rejectsCursorTamperingAndTokensFromAnotherInstance(String kind) throws Exception {
        String token = page("PAGES", kind, "?limit=1").path("nextCursor").asText();
        String[] parts = token.split("\\.");
        String payload = new String(Base64.getUrlDecoder().decode(parts[0]), StandardCharsets.UTF_8);
        assertThat(payload).doesNotContain("reviewer-test", task("PAGES"), rework("PAGES"));
        var node = (com.fasterxml.jackson.databind.node.ArrayNode) mapper.readTree(payload);
        node.set(3, mapper.getNodeFactory().numberNode(9999));
        String tampered = Base64.getUrlEncoder().withoutPadding().encodeToString(mapper.writeValueAsBytes(node)) + "." + parts[1];
        error(get(base("PAGES") + "/" + kind + "?cursor=" + tampered, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(get(base("PAGES") + "/" + kind + "?cursor=" + "x".repeat(2049), "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        var another = new ReworkHistoryCursor(mapper);
        String foreign = another.encode("reviewer-test", task("PAGES"), rework("PAGES"), kind.toUpperCase(java.util.Locale.ROOT), new ReworkHistoryCursor.Window(1, 103));
        error(get(base("PAGES") + "/" + kind + "?cursor=" + foreign, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
    }

    @ParameterizedTest
    @ValueSource(strings = {"results", "inspections"})
    void excludesLaterAppendsFromContinuationButFreshFirstPageSeesThem(String kind) {
        String id = "APPEND-" + kind.toUpperCase(java.util.Locale.ROOT); fixture(id, true);
        for (int n = 1; n <= 3; n++) { processing(id, n); inspection(id, n, n, "FAILED"); }
        var first = page(id, kind, "?limit=1"); String token = first.path("nextCursor").asText();
        processing(id, 4); inspection(id, 4, 4, "FAILED");
        var last = page(id, kind, "?limit=100&cursor=" + token);
        assertThat(last.path("records").size()).isEqualTo(2); assertThat(last.path("nextCursor").isNull()).isTrue();
        assertThat(page(id, kind, "?limit=100&cursor=" + token)).isEqualTo(last);
        assertThat(page(id, kind, "").path("records").size()).isEqualTo(4);
    }

    @Test
    void usesOwnReadOnlyRepeatableReadSnapshotAcrossUpperAndRows() {
        String id = "SNAPSHOT"; fixture(id, true); processing(id, 1); processing(id, 3);
        var observing = new ReworkHistoryRepository(jdbc, mapper) {
            @Override public long upper(String task, String rework, Kind kind) {
                assertThat(jdbc.queryForObject("SHOW transaction_isolation", String.class)).isEqualTo("repeatable read");
                assertThat(jdbc.queryForObject("SHOW transaction_read_only", String.class)).isEqualTo("on");
                long upper = super.upper(task, rework, kind);
                try (Connection connection = dataSource.getConnection(); var statement = connection.prepareStatement("INSERT INTO rework_processing_revisions VALUES (?,2,'成果-A','v2','独立事务材料','[\"report:new\"]'::jsonb,'other-test',CURRENT_TIMESTAMP)")) {
                    assertThat(connection.getAutoCommit()).isTrue(); statement.setString(1, rework); statement.executeUpdate();
                } catch (java.sql.SQLException exception) { throw new IllegalStateException(exception); }
                return upper;
            }
        };
        var service = new ReworkHistoryService(facts, observing, cursors, manager);
        // 外层是默认读写事务，历史服务仍须创建自己的只读可重复读事务。
        var data = new TransactionTemplate(manager).execute(status -> service.read(task(id), rework(id), "reviewer-test", "REVIEWER", ReworkHistoryRepository.Kind.RESULTS, new LinkedMultiValueMap<>()));
        assertThat(mapper.valueToTree(data).path("records").size()).isEqualTo(2);
        assertThat(page(id, "results", "").path("records").size()).isEqualTo(3);
    }

    private ResponseEntity<JsonNode> post(String id, String action, JsonNode body, String key, String actor, String role) {
        var headers = headers(actor, role); headers.setContentType(MediaType.APPLICATION_JSON); headers.set("Idempotency-Key", key);
        return http.exchange(base(id) + "/" + action, HttpMethod.POST, new HttpEntity<>(body.toString(), headers), JsonNode.class);
    }

    @ParameterizedTest
    @ValueSource(strings = {"results", "inspections"})
    void preservesSafeIntegerSequencesAndRealSuccessorRound(String kind) {
        String id = "ROUND-" + kind.toUpperCase(java.util.Locale.ROOT); fixture(id, true);
        String next = rework(id) + "-NEXT";
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'RUNNING','真实第二轮')", next, task(id), issue(id));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES (?,?,?,2,?,1,'creator-test',CURRENT_TIMESTAMP)", next, task(id), issue(id), rework(id));
        for (long revision : List.of(1L, 9007199254740991L)) {
            jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,?,'成果-A','v2','第二轮材料','[\"report:second\"]'::jsonb,'handler-test',CURRENT_TIMESTAMP)", next, revision);
            jdbc.update("INSERT INTO rework_inspections VALUES (?,?,?,?, 'FAILED','[{\"checkItem\":\"坐标系\",\"result\":\"FAILED\",\"comment\":\"保留失败\",\"evidenceReferences\":[\"report:failed\"]}]'::jsonb,'inspector-test',CURRENT_TIMESTAMP)", "CHECK-T815-" + kind.toUpperCase(java.util.Locale.ROOT) + "-" + revision, next, revision, revision);
        }
        String path = "/api/tasks/" + task(id) + "/reworks/" + next + "/" + kind;
        var first = get(path + "?limit=1", "reviewer-test", "REVIEWER").getBody().path("data");
        var response = get(path + "?cursor=" + first.path("nextCursor").asText(), "reviewer-test", "REVIEWER");
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        var last = response.getBody().path("data"); assertThat(last.path("nextCursor").isNull()).isTrue();
        var record = last.path("records").get(0);
        assertThat(record.path("processingRevision").asLong()).isEqualTo(9007199254740991L);
        if (kind.equals("inspections")) {
            assertThat(record.path("inspectionSequence").asLong()).isEqualTo(9007199254740991L);
            assertThat(record.path("roundNumber").asLong()).isEqualTo(2);
        }
    }

    private JsonNode material(long version) {
        var body = mapper.createObjectNode().put("expectedVersion", version).put("processingComment", "  真实人工登记  ");
        body.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "v2");
        body.putArray("evidenceReferences").add("report:人工处理"); return body;
    }

    private JsonNode check(long version, String result) {
        var body = mapper.createObjectNode().put("expectedVersion", version).put("processingRevision", 1);
        var item = body.putArray("items").addObject().put("checkItem", "坐标系").put("result", result).put("comment", "人工检查");
        item.putArray("evidenceReferences").add("report:人工检查"); return body;
    }

    @Test
    void actualRegistrationFailureThenPassIsImmutableAndReplaysWithoutNewHistory() {
        String id = "CYCLE"; fixture(id, true);
        var input = material(0);
        var registered = post(id, "results", input, "t815-result", "reviewer-test", "REVIEWER");
        assertThat(registered.getStatusCode().value()).isEqualTo(200);
        var failed = post(id, "inspections", check(1, "FAILED"), "t815-check-fail", "reviewer-test", "REVIEWER");
        assertThat(failed.getStatusCode().value()).isEqualTo(200);
        var passed = post(id, "inspections", check(2, "PASSED"), "t815-check-pass", "reviewer-test", "REVIEWER");
        assertThat(passed.getStatusCode().value()).isEqualTo(200);
        var before = allFacts();
        assertThat(post(id, "results", input, "t815-result", "reviewer-test", "REVIEWER").getBody().path("data")).isEqualTo(registered.getBody().path("data"));
        assertThat(post(id, "inspections", check(1, "FAILED"), "t815-check-fail", "reviewer-test", "REVIEWER").getBody().path("data")).isEqualTo(failed.getBody().path("data"));
        assertThat(post(id, "inspections", check(2, "PASSED"), "t815-check-pass", "reviewer-test", "REVIEWER").getBody().path("data")).isEqualTo(passed.getBody().path("data"));
        error(post(id, "results", material(3), "t815-result-new", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(post(id, "inspections", check(3, "PASSED"), "t815-check-new", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        assertThat(page(id, "results", "").path("records").size()).isEqualTo(1);
        var checks = page(id, "inspections", "").path("records"); assertThat(checks.size()).isEqualTo(2);
        assertThat(checks.get(0).path("result").asText()).isEqualTo("FAILED");
        assertThat(checks.get(1).path("result").asText()).isEqualTo("PASSED");
        for (String table : List.of("rework_processing_revisions", "rework_inspections")) {
            assertThatThrownBy(() -> jdbc.update("DELETE FROM " + table + " WHERE rework_task_id=?", rework(id))).isInstanceOf(org.springframework.dao.DataAccessException.class);
            String column = table.equals("rework_inspections") ? "inspector_id" : "registered_by";
            assertThatThrownBy(() -> jdbc.update("UPDATE " + table + " SET " + column + "='changed-test' WHERE rework_task_id=?", rework(id))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        }
        assertThat(allFacts()).isEqualTo(before);
        assertThat(jdbc.queryForMap("SELECT t.status AS task_status,t.version,r.status,q.status AS issue_status FROM production_tasks t JOIN rework_tasks r ON r.task_id=t.task_id JOIN quality_issues q ON q.issue_id=r.source_issue_id WHERE r.rework_task_id=?", rework(id)))
                .containsEntry("task_status", "COMPLETED").containsEntry("version", 3L).containsEntry("status", "COMPLETED").containsEntry("issue_status", "RESOLVED");
    }

    @ParameterizedTest
    @ValueSource(strings = {"results", "inspections"})
    void rejectedWriteIdentityOrKeyConflictsCannotAppendHistoricalEvidence(String action) {
        String id = "WRITE-" + action.toUpperCase(java.util.Locale.ROOT); fixture(id, true);
        JsonNode input = material(0);
        if (action.equals("inspections")) { processing(id, 1); input = check(0, "FAILED"); }
        String key = "t815-write-" + action;
        var before = allFacts();
        error(post(id, action, input, key, null, "REVIEWER"), 401, "PERMISSION_DENIED");
        error(post(id, action, input, key, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        assertThat(allFacts()).isEqualTo(before);
        var original = post(id, action, input, key, "reviewer-test", "REVIEWER"); assertThat(original.getStatusCode().value()).isEqualTo(200);
        before = allFacts();
        error(post(id, action, input, key, "other-user", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        var changed = input.deepCopy(); ((com.fasterxml.jackson.databind.node.ObjectNode) changed).put("expectedVersion", 1);
        error(post(id, action, changed, key, "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        assertThat(post(id, action, input, key, "reviewer-test", "REVIEWER").getBody().path("data")).isEqualTo(original.getBody().path("data"));
        assertThat(allFacts()).isEqualTo(before);
    }
}
