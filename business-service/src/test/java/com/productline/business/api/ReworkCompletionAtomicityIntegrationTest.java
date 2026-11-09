package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.List;
import java.util.Locale;
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

/** 真实HTTP通过分支的逐写入点、提交失败及事务外观察验收，不接入或冒充人工Approval。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t814_completion_atomicity", "spring.flyway.default-schema=t814_completion_atomicity",
        "spring.datasource.hikari.schema=t814_completion_atomicity",
        "spring.jpa.properties.hibernate.default_schema=t814_completion_atomicity"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkCompletionAtomicityIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private DataSource dataSource;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T814','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T814','ORDER-T814','BLOCKED')");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T814'", String.class)).isEqualTo("QUALITY_CHECKING");
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T814'", String.class)).isEqualTo("BLOCKED");
        } finally { jdbc.execute("DROP SCHEMA t814_completion_atomicity CASCADE"); }
    }

    private String task(String id) { return "TASK-T814-" + id; }
    private String rework(String id) { return "REWORK-T814-" + id; }
    private String issue(String id) { return "ISSUE-T814-" + id; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }
    private String key(String id) { return "t814-" + id + "-pass"; }

    private ObjectNode check(long version, String result) {
        var body = mapper.createObjectNode(); body.put("expectedVersion", version); body.put("processingRevision", 1);
        var item = body.putArray("items").addObject(); item.put("checkItem", "坐标系人工核对").put("result", result).put("comment", "人工检查说明");
        item.putArray("evidenceReferences").add("report:manual-check"); return body;
    }

    private ResponseEntity<JsonNode> post(String id, String action, JsonNode body, String key) {
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER"); headers.set("Idempotency-Key", key);
        return http.exchange(base(id) + "/" + action, HttpMethod.POST, new HttpEntity<>(body.toString(), headers), JsonNode.class);
    }

    private JsonNode success(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200); assertThat(response.getBody().path("success").asBoolean()).isTrue();
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse(); return response.getBody().path("data");
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("data").isNull()).isTrue(); assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("report:manual-check", "request_hash", "人工检查说明");
    }

    private JsonNode detail(String id) {
        HttpHeaders headers = new HttpHeaders(); headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER");
        var response = http.exchange(base(id), HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200); return response.getBody().path("data");
    }

    private void seed(String id) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T814','COMPLETED')", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','隔离原子性问题')", issue(id), task(id));
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','保留创建原因')", rework(id), task(id), issue(id));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,?,?,1,'creator-test',now())", rework(id), task(id), issue(id));
    }

    private void fixture(String id) {
        seed(id);
        success(post(id, "start", mapper.createObjectNode().put("expectedVersion", 0), "t814-" + id + "-start"));
        var material = mapper.createObjectNode(); material.put("expectedVersion", 1);
        material.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "release-1");
        material.put("processingComment", "已人工处理"); material.putArray("evidenceReferences").add("report:material");
        success(post(id, "results", material, "t814-" + id + "-material"));
        success(post(id, "inspections", check(2, "FAILED"), "t814-" + id + "-failure"));
    }

    private List<String> snapshot(String id) {
        return jdbc.queryForList("""
                SELECT 'task:' || to_jsonb(t)::text FROM production_tasks t WHERE task_id=?
                UNION ALL SELECT 'issue:' || to_jsonb(q)::text FROM quality_issues q WHERE issue_id=?
                UNION ALL SELECT 'rework:' || to_jsonb(r)::text FROM rework_tasks r WHERE rework_task_id=?
                UNION ALL SELECT 'lifecycle:' || to_jsonb(l)::text FROM rework_lifecycles l WHERE rework_task_id=?
                UNION ALL SELECT 'material:' || to_jsonb(p)::text FROM rework_processing_revisions p WHERE rework_task_id=?
                UNION ALL SELECT 'check:' || to_jsonb(i)::text FROM rework_inspections i WHERE rework_task_id=?
                UNION ALL SELECT 'review:' || to_jsonb(v)::text FROM rework_reviews v WHERE rework_task_id=?
                UNION ALL SELECT 'receipt:' || to_jsonb(p)::text FROM rework_operation_receipts p WHERE rework_task_id=?
                UNION ALL SELECT 'idempotency:' || to_jsonb(i)::text FROM idempotency_records i WHERE resource_id=?
                UNION ALL SELECT 'audit:' || to_jsonb(a)::text FROM operation_logs a WHERE target_id=? ORDER BY 1
                """, String.class, task(id), issue(id), rework(id), rework(id), rework(id), rework(id), rework(id), rework(id), rework(id), task(id));
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

    private JsonNode completed(String id) throws Exception {
        var receipt = success(post(id, "inspections", check(3, "PASSED"), key(id)));
        assertThat(receipt.size()).isEqualTo(12); assertThat(receipt.path("taskVersion").asLong()).isEqualTo(4);
        assertThat(receipt.path("status").asText()).isEqualTo("COMPLETED"); assertThat(receipt.path("issueStatus").asText()).isEqualTo("RESOLVED");
        assertThat(receipt.path("processingRevision").asLong()).isEqualTo(1); assertThat(receipt.path("reviewId").isNull()).isTrue();
        var current = detail(id); assertThat(current.path("taskVersion").asLong()).isEqualTo(4);
        assertThat(current.path("inspection").path("inspectionId")).isEqualTo(receipt.path("inspectionId"));
        assertThat(current.path("inspection").path("inspectionSequence").asLong()).isEqualTo(2);
        assertThat(current.path("inspection").path("result").asText()).isEqualTo("PASSED"); assertThat(current.path("review").isNull()).isTrue();
        assertThat(jdbc.queryForObject("SELECT status FROM production_tasks WHERE task_id=?", String.class, task(id))).isEqualTo("COMPLETED");
        assertThat(audits(key(id))).isEqualTo(1);
        var stored = jdbc.queryForMap("""
                SELECT p.response_data::text,i.resource_id,i.task_version_after,a.operation_type,a.actor_user_id,a.target_id,a.before_state,a.after_state
                FROM rework_operation_receipts p JOIN idempotency_records i USING(idempotency_key)
                JOIN operation_logs a ON a.operation_id=p.operation_id WHERE p.idempotency_key=?
                """, key(id));
        assertThat(mapper.readTree(stored.get("response_data").toString())).isEqualTo(receipt);
        assertThat(stored).containsEntry("resource_id", rework(id)).containsEntry("task_version_after", 4L)
                .containsEntry("operation_type", "REGISTER_REWORK_INSPECTION").containsEntry("actor_user_id", "reviewer-test").containsEntry("target_id", task(id));
        assertThat(mapper.readTree(stored.get("before_state").toString()).path("status").asText()).isEqualTo("RUNNING");
        assertThat(mapper.readTree(stored.get("after_state").toString()).path("issueStatus").asText()).isEqualTo("RESOLVED");
        return receipt;
    }

    static Stream<Arguments> writePoints() {
        return Stream.of(Arguments.of("version", "production_tasks", "UPDATE"), Arguments.of("inspection", "rework_inspections", "INSERT"),
                Arguments.of("completion", "rework_tasks", "UPDATE"), Arguments.of("resolution", "quality_issues", "UPDATE"),
                Arguments.of("reservation", "idempotency_records", "UPDATE"), Arguments.of("audit", "operation_logs", "INSERT"),
                Arguments.of("receipt", "rework_operation_receipts", "INSERT"));
    }

    private void trigger(String table, String event, String code) {
        jdbc.execute("CREATE FUNCTION t814_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN " + code + " END $$");
        jdbc.execute("CREATE TRIGGER t814_fault BEFORE " + event + " ON " + table + " FOR EACH ROW EXECUTE FUNCTION t814_fault()");
    }

    private void removeTrigger(String table) {
        jdbc.execute("DROP TRIGGER t814_fault ON " + table); jdbc.execute("DROP FUNCTION t814_fault()");
    }

    @ParameterizedTest
    @MethodSource("writePoints")
    void anyWriteExceptionRollsBackAllFactsAndAllowsExplicitResubmission(String point, String table, String event) throws Exception {
        String id = "THROW-" + point.toUpperCase(Locale.ROOT); fixture(id); var before = snapshot(id); var current = detail(id);
        trigger(table, event, "RAISE EXCEPTION 'forced T814 write failure';");
        try {
            error(post(id, "inspections", check(3, "PASSED"), key(id)), 500, "INTERNAL_SERVER_ERROR");
            absent(key(id)); assertThat(snapshot(id)).isEqualTo(before); assertThat(detail(id)).isEqualTo(current);
        } finally { removeTrigger(table); }
        completed(id);
    }

    @ParameterizedTest
    @MethodSource("writePoints")
    void silentlySkippedWritesAreNotReportedAsSuccessfulCompletion(String point, String table, String event) throws Exception {
        String id = "ZERO-" + point.toUpperCase(Locale.ROOT); fixture(id); var before = snapshot(id);
        trigger(table, event, "RETURN NULL;");
        try {
            error(post(id, "inspections", check(3, "PASSED"), key(id)), 409, "BUSINESS_CONFLICT");
            absent(key(id)); assertThat(snapshot(id)).isEqualTo(before);
        } finally { removeTrigger(table); }
        completed(id);
    }

    static Stream<Arguments> sharedWriteCallers() {
        return Stream.of("start", "block", "fail", "resume", "results").flatMap(action -> Stream.of("operation_logs", "rework_operation_receipts")
                .map(table -> Arguments.of(action, table)));
    }

    @ParameterizedTest
    @MethodSource("sharedWriteCallers")
    void everySharedWriteCallerRejectsMissingAuditOrReceiptRows(String action, String table) {
        String id = "SHARED-" + action.toUpperCase(Locale.ROOT) + (table.equals("operation_logs") ? "-AUDIT" : "-RECEIPT");
        long version;
        if (action.equals("start")) { seed(id); version = 0; }
        else {
            fixture(id); version = 3;
            if (action.equals("resume")) {
                success(post(id, "block", mapper.createObjectNode().put("expectedVersion", 3).put("reason", "人工阻塞"), "t814-" + id + "-block"));
                version = 4;
            }
        }
        var payload = mapper.createObjectNode().put("expectedVersion", version);
        if (action.equals("results")) {
            payload.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "release-2");
            payload.put("processingComment", "补充人工处理"); payload.putArray("evidenceReferences").add("report:material-2");
        } else if (!action.equals("start")) payload.put("reason", "本次人工处理说明");
        var before = snapshot(id); trigger(table, "INSERT", "RETURN NULL;");
        try {
            error(post(id, action, payload, key(id)), 409, "BUSINESS_CONFLICT"); absent(key(id));
            assertThat(snapshot(id)).isEqualTo(before);
        } finally { removeTrigger(table); }
        success(post(id, action, payload, key(id))); assertThat(audits(key(id))).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_operation_receipts WHERE idempotency_key=?", Integer.class, key(id))).isEqualTo(1);
    }

    @Test
    void aDeferredFailureAtCommitDoesNotReturnSuccessOrLeaveAnyWrite() throws Exception {
        String id = "COMMIT"; fixture(id); var before = snapshot(id); var current = detail(id);
        jdbc.execute("CREATE FUNCTION t814_commit_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T814 commit failure'; END $$");
        jdbc.execute("CREATE CONSTRAINT TRIGGER t814_commit_fault AFTER INSERT ON rework_operation_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION t814_commit_fault()");
        try {
            error(post(id, "inspections", check(3, "PASSED"), key(id)), 500, "INTERNAL_SERVER_ERROR");
            absent(key(id)); assertThat(snapshot(id)).isEqualTo(before); assertThat(detail(id)).isEqualTo(current);
        } finally { jdbc.execute("DROP TRIGGER t814_commit_fault ON rework_operation_receipts"); jdbc.execute("DROP FUNCTION t814_commit_fault()"); }
        completed(id);
    }

    @ParameterizedTest
    @ValueSource(strings = {"resolution", "reservation", "receipt"})
    void outsideReadersOnlySeeCommittedFactsDuringCompletion(String point) throws Exception {
        String id = "PAUSE-" + point.toUpperCase(Locale.ROOT); fixture(id); var before = snapshot(id); var current = detail(id);
        String table = switch (point) { case "resolution" -> "quality_issues"; case "reservation" -> "idempotency_records"; default -> "rework_operation_receipts"; };
        String event = point.equals("receipt") ? "INSERT" : "UPDATE";
        trigger(table, event, "PERFORM pg_advisory_xact_lock(814,1); RETURN NEW;");
        try (var pool = Executors.newSingleThreadExecutor(); var blocker = dataSource.getConnection()) {
            try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_lock(814,1)"); }
            var response = pool.submit(() -> post(id, "inspections", check(3, "PASSED"), key(id)));
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=814 AND objid=1 AND objsubid=2 AND NOT granted", Integer.class);
                    if (waiting == 1) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).as("completion must reach the selected write boundary before observation").isEqualTo(1);
                assertThat(response.isDone()).isFalse(); assertThat(snapshot(id)).isEqualTo(before);
                // 真实详情GET独立读取，不能看到新PASSED或部分完成状态。
                assertThat(detail(id)).isEqualTo(current);
            } finally {
                try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_unlock(814,1)"); }
            }
            success(response.get(30, TimeUnit.SECONDS)); completed(id);
        } finally { removeTrigger(table); }
    }

    @Test
    void replayIsStableAndNewRequestsCannotCompleteTheRoundAgain() throws Exception {
        String id = "REPLAY"; fixture(id); var original = completed(id); var before = snapshot(id);
        assertThat(success(post(id, "inspections", check(3, "PASSED"), key(id)))).isEqualTo(original);
        for (long version : List.of(3L, 4L)) {
            String key = "t814-replay-new-" + version;
            error(post(id, "inspections", check(version, "PASSED"), key), 409, "BUSINESS_CONFLICT"); absent(key);
        }
        assertThat(snapshot(id)).isEqualTo(before);
    }

    @Test
    void callersCannotCompleteWithoutManualInspectionItems() {
        String id = "NO-CHECK"; fixture(id); var before = snapshot(id);
        var forged = mapper.createObjectNode().put("expectedVersion", 3).put("processingRevision", 1).put("result", "PASSED");
        error(post(id, "inspections", forged, key(id)), 400, "PARAM_VALIDATION_ERROR"); absent(key(id));
        var empty = check(3, "PASSED"); empty.putArray("items");
        error(post(id, "inspections", empty, key(id)), 400, "PARAM_VALIDATION_ERROR"); absent(key(id));
        assertThat(post(id, "complete", forged, key(id)).getStatusCode().value()).isEqualTo(404); absent(key(id));
        assertThat(snapshot(id)).isEqualTo(before);
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
