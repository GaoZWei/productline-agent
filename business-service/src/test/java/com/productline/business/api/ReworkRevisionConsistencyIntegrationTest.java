package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.params.ParameterizedTest;
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

/** 通过真实HTTP验证失败后成果修订和过期检查请求；不冒充尚未接入的Approval验收。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t813_revision_consistency", "spring.flyway.default-schema=t813_revision_consistency",
        "spring.datasource.hikari.schema=t813_revision_consistency",
        "spring.jpa.properties.hibernate.default_schema=t813_revision_consistency"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkRevisionConsistencyIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private DataSource dataSource;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T813','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T813','ORDER-T813','BLOCKED')");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T813'", String.class)).isEqualTo("QUALITY_CHECKING");
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T813'", String.class)).isEqualTo("BLOCKED");
        } finally { jdbc.execute("DROP SCHEMA t813_revision_consistency CASCADE"); }
    }

    private String task(String id) { return "TASK-T813-" + id; }
    private String rework(String id) { return "REWORK-T813-" + id; }
    private String issue(String id) { return "ISSUE-T813-" + id; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }
    private String key(String id, String action) { return "t813-" + id + "-" + action; }

    private ObjectNode material(long version) {
        var body = mapper.createObjectNode(); body.put("expectedVersion", version);
        body.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "release-1");
        body.put("processingComment", "  第一版人工处理说明  ");
        body.putArray("evidenceReferences").add("report:first"); return body;
    }

    private ObjectNode changed(long version, String field) {
        var body = material(version);
        switch (field) {
            case "artifactId", "artifactVersion" -> ((ObjectNode) body.get("artifact")).put(field, "人工更新-2");
            case "processingComment" -> body.put(field, "  补充人工处理说明  ");
            case "evidenceReferences" -> body.putArray(field).add("report:second");
            case "identical" -> { /* 相同材料再次登记也必须新增修订，不能复用旧检查。 */ }
            default -> throw new IllegalArgumentException(field);
        }
        return body;
    }

    private ObjectNode check(long version, long revision, String result) {
        var body = mapper.createObjectNode(); body.put("expectedVersion", version); body.put("processingRevision", revision);
        var item = body.putArray("items").addObject(); item.put("checkItem", "人工坐标系核对").put("result", result).put("comment", "  实际检查意见  ");
        item.putArray("evidenceReferences").add("report:check"); return body;
    }

    private ResponseEntity<JsonNode> post(String id, String action, JsonNode body, String key) {
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER"); headers.set("Idempotency-Key", key);
        return http.exchange(base(id) + "/" + action, HttpMethod.POST, new HttpEntity<>(body.toString(), headers), JsonNode.class);
    }

    private JsonNode success(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody().path("success").asBoolean()).isTrue();
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        var data = response.getBody().path("data"); assertThat(data.size()).isEqualTo(12); return data;
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("data").isNull()).isTrue(); assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("report:first", "实际检查意见", "request_hash");
    }

    private JsonNode detail(String id) {
        HttpHeaders headers = new HttpHeaders(); headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER");
        var response = http.exchange(base(id), HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200); return response.getBody().path("data");
    }

    private List<String> rows(String id, String table, String order) {
        return jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + table + " r WHERE rework_task_id=? ORDER BY " + order, String.class, rework(id));
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

    private void assertFacts(String id, long version, long revision, String status, String issueStatus) {
        var current = detail(id);
        assertThat(current.path("taskVersion").asLong()).isEqualTo(version);
        assertThat(current.path("processing").path("processingRevision").asLong()).isEqualTo(revision);
        assertThat(current.path("reworkTask").path("status").asText()).isEqualTo(status);
        assertThat(current.path("issueStatus").asText()).isEqualTo(issueStatus);
        assertThat(current.path("review").isNull()).isTrue();
        assertThat(jdbc.queryForObject("SELECT status FROM production_tasks WHERE task_id=?", String.class, task(id))).isEqualTo("COMPLETED");
    }

    private record FailedFlow(JsonNode materialReceipt, JsonNode failedReceipt) {}

    private FailedFlow failed(String id) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T813','COMPLETED')", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','隔离修订测试')", issue(id), task(id));
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','原创建原因')", rework(id), task(id), issue(id));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,?,?,1,'creator-test',now())", rework(id), task(id), issue(id));
        success(post(id, "start", mapper.createObjectNode().put("expectedVersion", 0), key(id, "start")));
        var material = success(post(id, "results", material(1), key(id, "material")));
        var failure = success(post(id, "inspections", check(2, 1, "FAILED"), key(id, "failure")));
        assertFacts(id, 3, 1, "RUNNING", "PROCESSING");
        assertThat(detail(id).path("inspection").path("result").asText()).isEqualTo("FAILED");
        return new FailedFlow(material, failure);
    }

    private void stale(String id, long version, long revision, String suffix) {
        var before = detail(id); var checks = rows(id, "rework_inspections", "inspection_sequence");
        String key = key(id, suffix);
        error(post(id, "inspections", check(version, revision, "PASSED"), key), 409, "BUSINESS_CONFLICT"); absent(key);
        assertThat(detail(id)).isEqualTo(before); assertThat(rows(id, "rework_inspections", "inspection_sequence")).isEqualTo(checks);
    }

    @ParameterizedTest
    @ValueSource(strings = {"artifactId", "artifactVersion", "processingComment", "evidenceReferences", "identical"})
    void everyMaterialRegistrationInvalidatesOldCheckParametersAndPreservesHistory(String field) {
        String id = "EDIT-" + field.toUpperCase(Locale.ROOT); var flow = failed(id);
        var oldMaterials = rows(id, "rework_processing_revisions", "processing_revision");
        var oldChecks = rows(id, "rework_inspections", "inspection_sequence");
        var updated = success(post(id, "results", changed(3, field), key(id, "update")));
        assertThat(updated.path("processingRevision").asLong()).isEqualTo(2);
        assertThat(updated.path("inspectionId").isNull()).isTrue(); assertThat(updated.path("reviewId").isNull()).isTrue();
        assertFacts(id, 4, 2, "RUNNING", "PROCESSING"); assertThat(detail(id).path("inspection").isNull()).isTrue();
        assertThat(rows(id, "rework_processing_revisions", "processing_revision")).hasSize(2).startsWith(oldMaterials.toArray(String[]::new));
        assertThat(rows(id, "rework_inspections", "inspection_sequence")).isEqualTo(oldChecks);
        assertThat(detail(id).path("processing").path("artifact")).isEqualTo(changed(3, field).path("artifact"));
        assertThat(detail(id).path("processing").path("processingComment")).isEqualTo(changed(3, field).path("processingComment"));
        assertThat(detail(id).path("processing").path("evidenceReferences")).isEqualTo(changed(3, field).path("evidenceReferences"));
        stale(id, 3, 1, "old-version-and-revision"); stale(id, 4, 1, "old-revision"); stale(id, 3, 2, "old-version");
        var passed = success(post(id, "inspections", check(4, 2, "PASSED"), key(id, "pass")));
        assertFacts(id, 5, 2, "COMPLETED", "RESOLVED");
        assertThat(detail(id).path("inspection").path("inspectionSequence").asLong()).isEqualTo(2);
        assertThat(detail(id).path("inspection").path("inspectionId")).isEqualTo(passed.path("inspectionId"));
        var finalDetail = detail(id);
        assertThat(success(post(id, "results", material(1), key(id, "material")))).isEqualTo(flow.materialReceipt());
        assertThat(success(post(id, "inspections", check(2, 1, "FAILED"), key(id, "failure")))).isEqualTo(flow.failedReceipt());
        assertThat(detail(id)).isEqualTo(finalDetail); assertThat(audits(key(id, "failure"))).isEqualTo(1);
        assertThat(rows(id, "rework_inspections", "inspection_sequence")).hasSize(2).startsWith(oldChecks.toArray(String[]::new));
        String terminalKey = key(id, "terminal-edit");
        error(post(id, "results", changed(5, field), terminalKey), 409, "BUSINESS_CONFLICT"); absent(terminalKey);
        assertThat(detail(id)).isEqualTo(finalDetail);
    }

    @Test
    void aFailedCheckCanBeRepeatedOnTheSameRevisionButRequiresTheLatestVersion() {
        String id = "RECHECK"; var flow = failed(id); var old = rows(id, "rework_inspections", "inspection_sequence");
        var second = success(post(id, "inspections", check(3, 1, "FAILED"), key(id, "failure-2")));
        assertFacts(id, 4, 1, "RUNNING", "PROCESSING");
        assertThat(detail(id).path("inspection").path("inspectionId")).isEqualTo(second.path("inspectionId"));
        assertThat(rows(id, "rework_inspections", "inspection_sequence")).hasSize(2).startsWith(old.toArray(String[]::new));
        stale(id, 3, 1, "stale-recheck");
        success(post(id, "inspections", check(4, 1, "PASSED"), key(id, "pass")));
        assertFacts(id, 5, 1, "COMPLETED", "RESOLVED");
        assertThat(detail(id).path("inspection").path("inspectionSequence").asLong()).isEqualTo(3);
        assertThat(success(post(id, "inspections", check(2, 1, "FAILED"), key(id, "failure")))).isEqualTo(flow.failedReceipt());
        assertFacts(id, 5, 1, "COMPLETED", "RESOLVED");
    }

    @ParameterizedTest
    @ValueSource(strings = {"PASSED", "FAILED"})
    void anInspectionAndAMaterialUpdateReallyContendForTheSameTaskVersion(String result) throws Exception {
        String id = "RACE-" + result; failed(id); var oldChecks = rows(id, "rework_inspections", "inspection_sequence");
        String editKey = key(id, "edit"), checkKey = key(id, "check");
        var responses = contending(id, () -> post(id, "results", changed(3, "processingComment"), editKey),
                () -> post(id, "inspections", check(3, 1, result), checkKey));
        assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        if (responses.get(0).getStatusCode().value() == 200) {
            success(responses.get(0)); error(responses.get(1), 409, "BUSINESS_CONFLICT"); absent(checkKey);
            assertFacts(id, 4, 2, "RUNNING", "PROCESSING");
            assertThat(detail(id).path("inspection").isNull()).isTrue(); assertThat(rows(id, "rework_inspections", "inspection_sequence")).isEqualTo(oldChecks);
            stale(id, 4, 1, "old-revision-after-race");
            // 失败事务未占用键；显式重新读取事实并构造新请求后，才可以用原未提交键执行。
            success(post(id, "inspections", check(4, 2, "PASSED"), checkKey)); assertFacts(id, 5, 2, "COMPLETED", "RESOLVED");
        } else {
            error(responses.get(0), 409, "BUSINESS_CONFLICT"); absent(editKey); success(responses.get(1));
            assertThat(rows(id, "rework_processing_revisions", "processing_revision")).hasSize(1);
            assertThat(rows(id, "rework_inspections", "inspection_sequence")).hasSize(2).startsWith(oldChecks.toArray(String[]::new));
            assertFacts(id, 4, 1, result.equals("PASSED") ? "COMPLETED" : "RUNNING", result.equals("PASSED") ? "RESOLVED" : "PROCESSING");
            if (result.equals("FAILED")) {
                success(post(id, "results", changed(4, "processingComment"), editKey)); assertFacts(id, 5, 2, "RUNNING", "PROCESSING");
                assertThat(detail(id).path("inspection").isNull()).isTrue();
            }
        }
    }

    @Test
    void twoDifferentEditsCannotAllocateTwoRevisionsFromOneVersion() throws Exception {
        String id = "EDITRACE"; failed(id); String a = key(id, "edit-a"), b = key(id, "edit-b");
        var old = rows(id, "rework_processing_revisions", "processing_revision");
        var responses = contending(id, () -> post(id, "results", changed(3, "processingComment"), a),
                () -> post(id, "results", changed(3, "evidenceReferences"), b));
        assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        int winner = responses.get(0).getStatusCode().value() == 200 ? 0 : 1;
        var receipt = success(responses.get(winner)); error(responses.get(1 - winner), 409, "BUSINESS_CONFLICT"); absent(winner == 0 ? b : a);
        assertThat(receipt.path("processingRevision").asLong()).isEqualTo(2); assertThat(audits(winner == 0 ? a : b)).isEqualTo(1);
        assertFacts(id, 4, 2, "RUNNING", "PROCESSING"); assertThat(detail(id).path("inspection").isNull()).isTrue();
        assertThat(rows(id, "rework_processing_revisions", "processing_revision")).hasSize(2).startsWith(old.toArray(String[]::new));
    }

    @ParameterizedTest
    @ValueSource(strings = {"operation_logs", "rework_operation_receipts"})
    void failedMaterialUpdateKeepsThePreviousFailureCurrentUntilTheWholeUpdateCommits(String table) {
        String id = "ROLL-" + table.replace('_', '-').toUpperCase(Locale.ROOT); failed(id);
        var before = detail(id); var materials = rows(id, "rework_processing_revisions", "processing_revision");
        var checks = rows(id, "rework_inspections", "inspection_sequence"); String key = key(id, "edit");
        jdbc.execute("CREATE FUNCTION t813_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T813 failure'; END $$");
        jdbc.execute("CREATE TRIGGER t813_fail BEFORE INSERT ON " + table + " FOR EACH ROW EXECUTE FUNCTION t813_fail()");
        try {
            error(post(id, "results", changed(3, "evidenceReferences"), key), 500, "INTERNAL_SERVER_ERROR"); absent(key);
            assertThat(detail(id)).isEqualTo(before);
            assertThat(rows(id, "rework_processing_revisions", "processing_revision")).isEqualTo(materials);
            assertThat(rows(id, "rework_inspections", "inspection_sequence")).isEqualTo(checks);
        } finally { jdbc.execute("DROP TRIGGER t813_fail ON " + table); jdbc.execute("DROP FUNCTION t813_fail()"); }
        success(post(id, "results", changed(3, "evidenceReferences"), key)); assertFacts(id, 4, 2, "RUNNING", "PROCESSING");
        assertThat(detail(id).path("inspection").isNull()).isTrue(); assertThat(rows(id, "rework_inspections", "inspection_sequence")).isEqualTo(checks);
        assertThat(audits(key)).isEqualTo(1);
    }

    private List<ResponseEntity<JsonNode>> contending(String id, Callable<ResponseEntity<JsonNode>> first,
            Callable<ResponseEntity<JsonNode>> second) throws Exception {
        // 先持有父任务锁，再观察两个HTTP写事务均在等待同一类父任务锁，避免仅凭线程同时启动声称有竞争。
        CountDownLatch ready = new CountDownLatch(2), go = new CountDownLatch(1);
        try (var pool = Executors.newFixedThreadPool(2); var blocker = dataSource.getConnection()) {
            blocker.setAutoCommit(false);
            try (var statement = blocker.prepareStatement("SELECT task_id FROM production_tasks WHERE task_id=? FOR UPDATE")) {
                statement.setString(1, task(id)); try (var row = statement.executeQuery()) { assertThat(row.next()).isTrue(); }
            }
            var a = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return first.call(); });
            var b = pool.submit(() -> { ready.countDown(); assertThat(go.await(10, TimeUnit.SECONDS)).isTrue(); return second.call(); });
            try {
                assertThat(ready.await(10, TimeUnit.SECONDS)).isTrue(); go.countDown();
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("""
                            SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
                            AND wait_event_type='Lock' AND query LIKE 'SELECT task_id FROM production_tasks WHERE task_id=%FOR UPDATE%'
                            """, Integer.class);
                    if (waiting >= 2) break;
                    Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).as("two real HTTP writers must be waiting before releasing the parent task lock").isEqualTo(2);
            } finally { blocker.rollback(); }
            return List.of(a.get(30, TimeUnit.SECONDS), b.get(30, TimeUnit.SECONDS));
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
