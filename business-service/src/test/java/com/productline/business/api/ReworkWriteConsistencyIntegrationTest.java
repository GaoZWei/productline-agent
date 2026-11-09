package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.ArrayList;
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

/** 验证M8.2跨操作的全局幂等、共享版本及事务边界；夹具不纳管固定黄金数据。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t810_rework_consistency", "spring.flyway.default-schema=t810_rework_consistency",
        "spring.datasource.hikari.schema=t810_rework_consistency",
        "spring.jpa.properties.hibernate.default_schema=t810_rework_consistency"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkWriteConsistencyIntegrationTest extends PostgresIntegrationTestSupport {
    private static final List<String> ACTIONS = List.of("start", "block", "fail", "resume");
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T810','DOM','QUALITY_CHECKING')");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
        } finally {
            jdbc.execute("DROP SCHEMA t810_rework_consistency CASCADE");
        }
    }

    private String task(String id) { return "TASK-T810-" + id; }
    private String rework(String id) { return "REWORK-T810-" + id; }
    private String issue(String id) { return "ISSUE-T810-" + id; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }
    private String operation(String action) { return action.toUpperCase(Locale.ROOT) + "_REWORK"; }

    private void fixture(String id, String action) {
        String state = switch (action) {
            case "start" -> "PENDING";
            case "resume" -> "BLOCKED";
            default -> "RUNNING";
        };
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T810','COMPLETED')", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM',?,'隔离一致性测试')",
                issue(id), task(id), action.equals("start") ? "OPEN" : "PROCESSING");
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?,'保留的创建原因')", rework(id), task(id), issue(id), state);
        jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at)
                VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')
                """, rework(id), task(id), issue(id));
        if (!action.equals("start")) {
            jdbc.update("UPDATE rework_lifecycles SET started_by='original-handler',started_at=TIMESTAMPTZ '2026-11-09 00:01:00+00' WHERE rework_task_id=?", rework(id));
        }
    }

    private String body(String action, long version, String reason) throws Exception {
        return mapper.writeValueAsString(action.equals("start")
                ? Map.of("expectedVersion", version)
                : Map.of("expectedVersion", version, "reason", reason));
    }

    private ResponseEntity<JsonNode> post(String path, String body, String key) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-User-Id", "reviewer-test");
        headers.set("X-User-Role", "REVIEWER");
        headers.set("Idempotency-Key", key);
        return http.exchange(path, HttpMethod.POST, new HttpEntity<>(body, headers), JsonNode.class);
    }

    private ResponseEntity<JsonNode> event(String id, String action, long version, String key) throws Exception {
        return post(base(id) + "/" + action, body(action, version, "  人工操作说明  "), key);
    }

    private JsonNode success(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody().path("success").asBoolean()).isTrue();
        return response.getBody().path("data");
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().path("data").isNull()).isTrue();
    }

    private Map<String, Object> state(String id) {
        return jdbc.queryForMap("""
                SELECT t.status AS task_status,t.version,r.status AS rework_status,r.reason,
                       q.status AS issue_status,l.started_by,l.started_at
                FROM production_tasks t JOIN rework_tasks r ON r.task_id=t.task_id
                JOIN quality_issues q ON q.issue_id=r.source_issue_id
                JOIN rework_lifecycles l ON l.rework_task_id=r.rework_task_id WHERE r.rework_task_id=?
                """, rework(id));
    }

    private int count(String table, String key) {
        return jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE idempotency_key=?", Integer.class, key);
    }

    private int auditCount(String key) {
        return jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')", Integer.class, key);
    }

    private void absent(String key) {
        assertThat(count("idempotency_records", key)).isZero();
        assertThat(count("rework_operation_receipts", key)).isZero();
        assertThat(auditCount(key)).isZero();
    }

    private void committed(String key, JsonNode receipt) throws Exception {
        assertThat(receipt.size()).isEqualTo(12);
        assertThat(count("idempotency_records", key)).isEqualTo(1);
        assertThat(count("rework_operation_receipts", key)).isEqualTo(1);
        assertThat(auditCount(key)).isEqualTo(1);
        var stored = jdbc.queryForMap("""
                SELECT p.response_data::text,i.resource_id,i.task_version_after,a.operation_type,a.actor_user_id,
                       a.target_id,a.before_state,a.after_state
                FROM rework_operation_receipts p JOIN idempotency_records i USING(idempotency_key)
                JOIN operation_logs a ON a.operation_id=p.operation_id WHERE p.idempotency_key=?
                """, key);
        assertThat(mapper.readTree(stored.get("response_data").toString())).isEqualTo(receipt);
        assertThat(stored).containsEntry("resource_id", receipt.path("reworkTaskId").asText())
                .containsEntry("task_version_after", receipt.path("taskVersion").asLong())
                .containsEntry("operation_type", receipt.path("operation").asText())
                .containsEntry("target_id", receipt.path("taskId").asText())
                .containsEntry("actor_user_id", "reviewer-test");
        assertThat(mapper.readTree(stored.get("after_state").toString()).path("taskVersion").asLong())
                .isEqualTo(receipt.path("taskVersion").asLong());
        assertThat(stored.get("before_state").toString() + stored.get("after_state")).doesNotContain(key);
    }

    static Stream<Arguments> failurePoints() {
        return ACTIONS.stream().flatMap(action -> Stream.of("reservation", "audit", "receipt")
                .map(point -> Arguments.of(action, point)));
    }

    @ParameterizedTest
    @MethodSource("failurePoints")
    void eachWriteBoundaryRollsBackAndTheOriginalKeyCanBeResubmitted(String action, String point) throws Exception {
        String id = "ROLL-" + action.toUpperCase(Locale.ROOT) + "-" + point.toUpperCase(Locale.ROOT);
        fixture(id, action);
        var before = state(id);
        String key = "t810-" + id;
        String table = switch (point) {
            case "reservation" -> "idempotency_records";
            case "audit" -> "operation_logs";
            default -> "rework_operation_receipts";
        };
        String triggerEvent = point.equals("reservation") ? "UPDATE" : "INSERT";
        jdbc.execute("CREATE FUNCTION t810_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T810 failure'; END $$");
        jdbc.execute("CREATE TRIGGER t810_fail BEFORE " + triggerEvent + " ON " + table + " FOR EACH ROW EXECUTE FUNCTION t810_fail()");
        try {
            error(event(id, action, 0, key), 500, "INTERNAL_SERVER_ERROR");
            assertThat(state(id)).isEqualTo(before);
            absent(key);
        } finally {
            jdbc.execute("DROP TRIGGER t810_fail ON " + table);
            jdbc.execute("DROP FUNCTION t810_fail()");
        }
        var receipt = success(event(id, action, 0, key));
        assertThat(receipt.path("operation").asText()).isEqualTo(operation(action));
        committed(key, receipt);
        assertThat(state(id)).containsEntry("version", 1L).containsEntry("task_status", "COMPLETED");
    }

    static Stream<Arguments> operationPairs() {
        return Stream.iterate(0, i -> i + 1).limit(ACTIONS.size()).flatMap(i ->
                ACTIONS.subList(i + 1, ACTIONS.size()).stream().map(other -> Arguments.of(ACTIONS.get(i), other)));
    }

    @ParameterizedTest
    @MethodSource("operationPairs")
    void aGlobalKeyCannotCommitTwoDifferentActionsOrResources(String first, String second) throws Exception {
        String a = "PAIR-" + first.toUpperCase(Locale.ROOT) + "-" + second.toUpperCase(Locale.ROOT);
        String b = a + "-OTHER";
        fixture(a, first); fixture(b, second);
        var beforeA = state(a); var beforeB = state(b);
        String key = "t810-" + a;
        var results = concurrent(() -> event(a, first, 0, key), () -> event(b, second, 0, key));
        assertThat(results.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        int winner = results.get(0).getStatusCode().value() == 200 ? 0 : 1;
        committed(key, success(results.get(winner)));
        error(results.get(1 - winner), 409, "BUSINESS_CONFLICT");
        assertThat(state(winner == 0 ? b : a)).isEqualTo(winner == 0 ? beforeB : beforeA);
        assertThat(state(winner == 0 ? a : b)).containsEntry("version", 1L);
    }

    @ParameterizedTest
    @ValueSource(strings = {"start", "block", "fail", "resume"})
    void sameKeyWithDifferentBodiesHasOneWinnerWithoutTakingOverTheReservation(String action) throws Exception {
        String id = "BODY-" + action.toUpperCase(Locale.ROOT); fixture(id, action);
        String key = "t810-" + id;
        // start以版本区分；其他动作以原样原因区分，均不能把失败请求接管为另一个写入。
        String firstBody = body(action, 0, "原样说明");
        String secondBody = body(action, action.equals("start") ? 1 : 0, " 原样说明 ");
        var results = concurrent(() -> post(base(id) + "/" + action, firstBody, key),
                () -> post(base(id) + "/" + action, secondBody, key));
        assertThat(results.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        int winner = results.get(0).getStatusCode().value() == 200 ? 0 : 1;
        var receipt = success(results.get(winner)); committed(key, receipt);
        error(results.get(1 - winner), 409, "BUSINESS_CONFLICT");
        assertThat(success(post(base(id) + "/" + action, winner == 0 ? firstBody : secondBody, key))).isEqualTo(receipt);
        error(post(base(id) + "/" + action, winner == 0 ? secondBody : firstBody, key), 409, "BUSINESS_CONFLICT");
        assertThat(state(id)).containsEntry("version", 1L);
    }

    @ParameterizedTest
    @ValueSource(strings = {"start", "block", "fail", "resume"})
    void legacyReviewAndLifecycleWriteShareOneTaskVersion(String action) throws Exception {
        String id = "LEGACY-" + action.toUpperCase(Locale.ROOT); fixture(id, action);
        var before = state(id);
        String key = "t810-" + id; String legacyKey = key + "-review";
        String reviewBody = mapper.writeValueAsString(Map.of("issueId", issue(id), "expectedVersion", 0,
                "status", "REWORK_REQUIRED", "reviewComment", "独立旧复核操作"));
        var results = concurrent(() -> event(id, action, 0, key),
                () -> post("/api/tasks/" + task(id) + "/review", reviewBody, legacyKey));
        assertThat(results.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        assertThat(state(id)).containsEntry("version", 1L).containsEntry("task_status", "COMPLETED");
        if (results.get(0).getStatusCode().value() == 200) {
            committed(key, success(results.get(0))); absent(legacyKey);
            assertThat(jdbc.queryForObject("SELECT count(*) FROM review_records WHERE issue_id=?", Integer.class, issue(id))).isZero();
        } else {
            error(results.get(0), 409, "BUSINESS_CONFLICT"); absent(key);
            assertThat(success(results.get(1)).path("taskVersion").asLong()).isEqualTo(1);
            assertThat(auditCount(legacyKey)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT count(*) FROM review_records WHERE issue_id=?", Integer.class, issue(id))).isEqualTo(1);
            var expected = new java.util.HashMap<>(before); expected.put("version", 1L);
            assertThat(state(id)).isEqualTo(expected);
        }
        error(event(id, action, 0, key + "-stale"), 409, "BUSINESS_CONFLICT"); absent(key + "-stale");
    }

    @ParameterizedTest
    @ValueSource(strings = {"start", "block", "fail", "resume"})
    void anIncompleteReservationIsNotTakenOverOrRetried(String action) throws Exception {
        String id = "PENDING-" + action.toUpperCase(Locale.ROOT); fixture(id, action);
        String key = "t810-" + id; var before = state(id);
        String canonical = mapper.writeValueAsString(action.equals("start")
                ? List.of(operation(action), task(id), rework(id), 0)
                : List.of(operation(action), task(id), rework(id), 0, "  人工操作说明  "));
        jdbc.update("""
                INSERT INTO idempotency_records(idempotency_key,operation_type,request_hash,actor_user_id)
                VALUES (?,?,encode(sha256(convert_to(?,'UTF8')),'hex'),'reviewer-test')
                """, key, operation(action), canonical);
        var reservation = jdbc.queryForMap("SELECT * FROM idempotency_records WHERE idempotency_key=?", key);
        error(event(id, action, 0, key), 409, "BUSINESS_CONFLICT");
        assertThat(state(id)).isEqualTo(before);
        assertThat(jdbc.queryForMap("SELECT * FROM idempotency_records WHERE idempotency_key=?", key)).isEqualTo(reservation);
        assertThat(count("rework_operation_receipts", key)).isZero(); assertThat(auditCount(key)).isZero();
    }

    @Test
    void allOriginalReceiptsRemainStableAfterAFullStartInterruptionAndResumeSequence() throws Exception {
        String id = "CYCLE"; fixture(id, "start");
        var receipts = new ArrayList<JsonNode>();
        List<String> sequence = List.of("start", "block", "resume", "fail");
        for (int i = 0; i < sequence.size(); i++) {
            String action = sequence.get(i); String key = "t810-cycle-" + action;
            var receipt = success(event(id, action, i, key));
            assertThat(receipt.path("taskVersion").asLong()).isEqualTo(i + 1L);
            committed(key, receipt); receipts.add(receipt);
        }
        var current = state(id);
        for (int i = sequence.size() - 1; i >= 0; i--) {
            assertThat(success(event(id, sequence.get(i), i, "t810-cycle-" + sequence.get(i)))).isEqualTo(receipts.get(i));
            committed("t810-cycle-" + sequence.get(i), receipts.get(i));
            assertThat(state(id)).isEqualTo(current);
        }
        assertThat(current).containsEntry("version", 4L).containsEntry("rework_status", "FAILED")
                .containsEntry("issue_status", "PROCESSING").containsEntry("task_status", "COMPLETED");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE target_id=?", Integer.class, task(id))).isEqualTo(4);
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
        // 对固定任务及其关联事实逐行比较，包含版本、待复核和交付阻塞，不只比较记录数量。
        return jdbc.queryForList("""
                SELECT 'task:' || to_jsonb(t)::text FROM production_tasks t WHERE task_id='TASK-003'
                UNION ALL SELECT 'issue:' || to_jsonb(q)::text FROM quality_issues q WHERE task_id='TASK-003'
                UNION ALL SELECT 'review:' || to_jsonb(r)::text FROM review_records r WHERE issue_id='ISSUE-001'
                UNION ALL SELECT 'delivery:' || to_jsonb(d)::text FROM delivery_records d WHERE order_id='ORDER-003'
                ORDER BY 1
                """, String.class);
    }
}
