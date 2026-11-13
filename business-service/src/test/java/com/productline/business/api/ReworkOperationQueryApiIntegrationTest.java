package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productline.business.api.dto.ReworkOperationQueryRequest;
import com.productline.business.application.ReworkOperationQueryService;
import com.productline.business.domain.repository.ReworkOperationQueryRepository;
import com.productline.business.domain.repository.ReworkOperationQueryRepository.StoredReceipt;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
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
import org.springframework.transaction.PlatformTransactionManager;

/** 原回执查询经真实HTTP与独占schema验证，不访问开发/运行库。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t824_operation_query", "spring.flyway.default-schema=t824_operation_query",
        "spring.datasource.hikari.schema=t824_operation_query",
        "spring.jpa.properties.hibernate.default_schema=t824_operation_query"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkOperationQueryApiIntegrationTest extends PostgresIntegrationTestSupport {
    private static final String USER = "reviewer-t824";
    private static final String TRACE = "trace-t824-query";
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private ReworkOperationQueryRepository receipts;
    @Autowired private PlatformTransactionManager manager;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T824','DOM','QUALITY_CHECKING')");
        fixture("SCOPE");
        fixture("OTHER");
        fixture("CHAIN");
        fixture("SNAPSHOT");
        fixture("LEGACY");
        write(base("SCOPE"), Map.of("sourceIssueId", "ISSUE-T824-SCOPE", "expectedVersion", 0,
                "reason", "人工确认的独立返工"), "t824.scope:key-1");
    }

    private void fixture(String suffix) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status,version) VALUES (?,'ORDER-T824','COMPLETED',0)", task(suffix));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','查询夹具')", "ISSUE-T824-" + suffix, task(suffix));
    }

    @AfterAll
    void cleanup() {
        try { assertThat(golden()).isEqualTo(goldenBefore); }
        finally { jdbc.execute("DROP SCHEMA t824_operation_query CASCADE"); }
    }

    private String task(String suffix) { return "TASK-T824-" + suffix; }
    private String base(String suffix) { return "/api/tasks/" + task(suffix) + "/reworks"; }

    private ResponseEntity<JsonNode> post(String path, String body, String user, String role, String contentType, String key) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Trace-Id", TRACE);
        if (user != null) headers.set("X-User-Id", user);
        if (role != null) headers.set("X-User-Role", role);
        if (contentType != null) headers.set("Content-Type", contentType);
        if (key != null) headers.set("Idempotency-Key", key);
        return http.exchange(path, HttpMethod.POST, new HttpEntity<>(body, headers), JsonNode.class);
    }

    private JsonNode data(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo(TRACE);
        JsonNode body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.size()).isEqualTo(6);
        assertThat(body.path("success").asBoolean()).isTrue();
        assertThat(body.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(body.path("retryable").asBoolean()).isFalse();
        assertThat(body.path("trace_id").asText()).isEqualTo(TRACE);
        return body.path("data");
    }

    private JsonNode write(String path, Map<String, Object> request, String key) {
        try { return data(post(path, mapper.writeValueAsString(request), USER, "REVIEWER", "application/json", key)); }
        catch (Exception exception) { throw new AssertionError("isolated write failed", exception); }
    }

    private JsonNode query(String suffix, String key, String user) {
        try {
            JsonNode result = data(post(base(suffix) + "/operations/query",
                    mapper.writeValueAsString(Map.of("idempotencyKey", key)), user, "REVIEWER", "application/json", null));
            assertThat(result.size()).isEqualTo(2);
            return result;
        } catch (Exception exception) { throw new AssertionError("isolated query failed", exception); }
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("data").isNull()).isTrue();
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("request_hash", "response_data", "t824.scope:key-1");
    }

    @Test
    void scopesByActualUserParentAndKeyWithoutRevealingOtherReceipts() {
        JsonNode own = query("SCOPE", "t824.scope:key-1", USER);
        assertThat(own.path("found").asBoolean()).isTrue();
        assertThat(own.path("receipt").size()).isEqualTo(12);
        for (JsonNode absent : List.of(query("SCOPE", "t824.scope:key-1", "reviewer-other"),
                query("OTHER", "t824.scope:key-1", USER), query("SCOPE", "t824.unknown", USER))) {
            assertThat(absent.path("found").asBoolean()).isFalse();
            assertThat(absent.path("receipt").isNull()).isTrue();
            assertThat(absent.toString()).doesNotContain("operationId", "requestHash", "reason");
        }
    }

    @Test
    void queriesNineActionsAndRetainsOriginalResultsAfterLaterBusinessChanges() {
        String b = base("CHAIN");
        List<String> keys = new ArrayList<>();
        List<JsonNode> originals = new ArrayList<>();
        JsonNode first = step(b, Map.of("sourceIssueId", "ISSUE-T824-CHAIN", "expectedVersion", 0,
                "reason", "人工确认首轮"), keys, originals);
        String r = b + "/" + first.path("reworkTaskId").asText();
        step(r + "/start", Map.of("expectedVersion", 1), keys, originals);
        step(r + "/block", Map.of("expectedVersion", 2, "reason", "阻塞"), keys, originals);
        step(r + "/resume", Map.of("expectedVersion", 3, "reason", "恢复"), keys, originals);
        step(r + "/fail", Map.of("expectedVersion", 4, "reason", "失败"), keys, originals);
        step(r + "/resume", Map.of("expectedVersion", 5, "reason", "人工恢复"), keys, originals);
        step(r + "/results", Map.of("expectedVersion", 6, "artifact", Map.of("artifactId", "成果-A", "artifactVersion", "Release-2"),
                "processingComment", "  原样说明🚀  ", "evidenceReferences", List.of("report:manual")), keys, originals);
        step(r + "/inspections", inspection(7, "FAILED"), keys, originals);
        JsonNode checked = step(r + "/inspections", inspection(8, "PASSED"), keys, originals);
        step(r + "/review", Map.of("expectedVersion", 9, "processingRevision", 1,
                "inspectionId", checked.path("inspectionId").asText(), "status", "REWORK_REQUIRED", "reviewComment", "需再次返工"), keys, originals);
        JsonNode next = step(r + "/next-round", Map.of("expectedVersion", 10, "reason", "再次人工确认"), keys, originals);
        assertThat(next.path("roundNumber").asLong()).isEqualTo(2);
        List<Map<String, Object>> before = state();
        for (int i = 0; i < keys.size(); i++) {
            JsonNode result = query("CHAIN", keys.get(i), USER);
            assertThat(result.path("found").asBoolean()).isTrue();
            assertThat(result.path("receipt")).isEqualTo(originals.get(i));
        }
        assertThat(query("CHAIN", keys.get(1), USER).path("receipt").path("status").asText()).isEqualTo("RUNNING");
        assertThat(jdbc.queryForObject("SELECT status FROM rework_tasks WHERE rework_task_id=?", String.class,
                first.path("reworkTaskId").asText())).isEqualTo("COMPLETED");
        assertThat(state()).isEqualTo(before);
    }

    private JsonNode step(String path, Map<String, Object> request, List<String> keys, List<JsonNode> originals) {
        String key = "t824-chain-" + keys.size();
        JsonNode receipt = write(path, request, key);
        keys.add(key);
        originals.add(receipt);
        return receipt;
    }

    private Map<String, Object> inspection(int version, String result) {
        return Map.of("expectedVersion", version, "processingRevision", 1, "items", List.of(Map.of(
                "checkItem", "坐标系", "result", result, "comment", "人工检查", "evidenceReferences", List.of("report:check"))));
    }

    @Test
    void legacyWriteAndFailedWriteDoNotInventLifecycleReceipts() {
        write("/api/tasks/" + task("LEGACY") + "/rework", Map.of("sourceIssueId", "ISSUE-T824-LEGACY",
                "expectedVersion", 0, "reason", "保留旧创建契约"), "t824-legacy");
        assertThat(query("LEGACY", "t824-legacy", USER).path("found").asBoolean()).isFalse();
        error(post(base("OTHER"), "{\"sourceIssueId\":\"ISSUE-T824-OTHER\",\"expectedVersion\":5,\"reason\":\"过期版本\"}",
                USER, "REVIEWER", "application/json", "t824-rolled-back"), 409, "BUSINESS_CONFLICT");
        assertThat(query("OTHER", "t824-rolled-back", USER).path("receipt").isNull()).isTrue();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE idempotency_key='t824-rolled-back'", Integer.class))
                .isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"{}", "null", "[]", "{", "{\"idempotencyKey\":null}", "{\"idempotencyKey\":1}",
            "{\"idempotencyKey\":true}", "{\"idempotencyKey\":\"\"}", "{\"idempotencyKey\":\" x\"}",
            "{\"idempotencyKey\":\"x/y\"}", "{\"idempotencyKey\":\"x\\n\"}",
            "{\"idempotencyKey\":\"x\",\"idempotencyKey\":\"y\"}", "{\"idempotencyKey\":\"x\"} {}",
            "{\"idempotencyKey\":\"x\",\"userId\":\"other\"}", "{\"idempotencyKey\":\"x\",\"confirmed\":true}"})
    void rejectsMalformedOrSelfReportedInputs(String body) {
        error(post(base("SCOPE") + "/operations/query", body, USER, "REVIEWER", "application/json", null), 400, "PARAM_VALIDATION_ERROR");
    }

    @ParameterizedTest
    @CsvSource({"NULL,REVIEWER,401,PERMISSION_DENIED", "reviewer-t824,OPERATOR,403,PERMISSION_DENIED",
            "reviewer-t824,NULL,403,PERMISSION_DENIED"})
    void requiresActualAuthenticatedReviewer(String user, String role, int status, String code) {
        error(post(base("SCOPE") + "/operations/query", "{\"idempotencyKey\":\"t824.scope:key-1\"}",
                user.equals("NULL") ? null : user, role.equals("NULL") ? null : role, "application/json", null), status, code);
    }

    @Test
    void validatesMediaParentQueryParametersAndKeyLength() {
        for (String media : List.of("text/plain", "application/json-invalid")) {
            error(post(base("SCOPE") + "/operations/query", "{}", USER, "REVIEWER", media, null), 400, "PARAM_VALIDATION_ERROR");
        }
        error(post(base("SCOPE") + "/operations/query?userId=other", "{\"idempotencyKey\":\"x\"}", USER,
                "REVIEWER", "application/json", null), 400, "PARAM_VALIDATION_ERROR");
        error(post("/api/tasks/TASK-T824-MISSING/reworks/operations/query", "{\"idempotencyKey\":\"x\"}", USER,
                "REVIEWER", "application/json", null), 404, "RESOURCE_NOT_FOUND");
        error(post("/api/tasks/TASK_bad/reworks/operations/query", "{\"idempotencyKey\":\"x\"}", USER,
                "REVIEWER", "application/json", null), 400, "PARAM_VALIDATION_ERROR");
        error(post(base("SCOPE") + "/operations/query", "{\"idempotencyKey\":\"" + "a".repeat(129) + "\"}", USER,
                "REVIEWER", "application/json", null), 400, "PARAM_VALIDATION_ERROR");
        assertThat(query("SCOPE", "a".repeat(128), USER).path("found").asBoolean()).isFalse();
        error(post(base("SCOPE") + "/operations/query", "{\"idempotencyKey\":\"x\"}", "a".repeat(129),
                "REVIEWER", "application/json", null), 400, "PARAM_VALIDATION_ERROR");
        error(post(base("SCOPE") + "/operations/query", "{\"idempotencyKey\":\"x\"}", "",
                "REVIEWER", "application/json", null), 401, "PERMISSION_DENIED");
    }

    @Test
    void snapshotMayMissAWriteThatCommitsBeforeQueryReturnsAndNextQuerySeesIt() {
        var reads = new ReworkReadRepository(jdbc, mapper) {
            @Override
            public boolean taskExists(String taskId) {
                boolean exists = super.taskExists(taskId);
                assertThat(jdbc.queryForObject("SHOW transaction_isolation", String.class)).isEqualTo("repeatable read");
                assertThat(jdbc.queryForObject("SHOW transaction_read_only", String.class)).isEqualTo("on");
                // 查询已取得快照，再让独立真实HTTP写事务提交；false不是未提交证明。
                try (var executor = Executors.newSingleThreadExecutor()) {
                    executor.submit(() -> write(base("SNAPSHOT"), Map.of("sourceIssueId", "ISSUE-T824-SNAPSHOT",
                            "expectedVersion", 0, "reason", "并发确认"), "t824-snapshot")).get(10, TimeUnit.SECONDS);
                } catch (Exception exception) { throw new AssertionError("independent HTTP write failed", exception); }
                return exists;
            }
        };
        var first = new ReworkOperationQueryService(receipts, reads, mapper, manager).query(
                task("SNAPSHOT"), USER, "REVIEWER", new ReworkOperationQueryRequest("t824-snapshot"));
        assertThat(first.found()).isFalse();
        assertThat(first.receipt()).isNull();
        assertThat(query("SNAPSHOT", "t824-snapshot", USER).path("found").asBoolean()).isTrue();
    }

    @ParameterizedTest
    @ValueSource(strings = {"operationId", "taskId", "taskVersion", "processingRevision", "reviewId", "extra"})
    void rejectsCorruptStoredBindingsWithoutExposingPayload(String field) throws Exception {
        StoredReceipt original = receipts.find(task("SCOPE"), USER, "t824.scope:key-1").orElseThrow();
        ObjectNode altered = (ObjectNode) mapper.readTree(original.json());
        if (field.equals("taskVersion")) altered.put(field, original.taskVersion() + 1);
        else if (field.equals("processingRevision")) altered.put(field, "1");
        else altered.put(field, "SECRET-OTHER");
        var fake = new ReworkOperationQueryRepository(jdbc) {
            @Override
            public Optional<StoredReceipt> find(String task, String actor, String key) {
                return Optional.of(new StoredReceipt(original.operation(), original.operationId(), original.taskId(),
                        original.reworkTaskId(), original.roundNumber(), original.taskVersion(), altered.toString()));
            }
        };
        assertThatThrownBy(() -> new ReworkOperationQueryService(fake, new ReworkReadRepository(jdbc, mapper), mapper, manager)
                .query(task("SCOPE"), USER, "REVIEWER", new ReworkOperationQueryRequest("t824.scope:key-1")))
                .isInstanceOf(IllegalStateException.class).hasMessage("stored rework operation receipt is invalid")
                .hasMessageNotContaining("SECRET");
    }

    private List<Map<String, Object>> state() {
        return jdbc.queryForList("""
                SELECT 'task' AS kind,to_jsonb(t)::text AS value FROM production_tasks t WHERE task_id LIKE 'TASK-T824-%'
                UNION ALL SELECT 'rework',to_jsonb(r)::text FROM rework_tasks r WHERE task_id LIKE 'TASK-T824-%'
                UNION ALL SELECT 'issue',to_jsonb(q)::text FROM quality_issues q WHERE task_id LIKE 'TASK-T824-%'
                UNION ALL SELECT 'receipt',to_jsonb(r)::text FROM rework_operation_receipts r WHERE task_id LIKE 'TASK-T824-%'
                UNION ALL SELECT 'audit',to_jsonb(o)::text FROM operation_logs o WHERE target_id LIKE 'TASK-T824-%'
                UNION ALL SELECT 'key',to_jsonb(i)::text FROM idempotency_records i WHERE actor_user_id='reviewer-t824'
                ORDER BY 1,2
                """);
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
