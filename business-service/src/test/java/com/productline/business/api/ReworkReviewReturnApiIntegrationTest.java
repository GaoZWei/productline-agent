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

/** 未通过复核只追加结论并重开来源问题，不能撤销本轮完成事实或暗中创建下一轮。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t818_review_return", "spring.flyway.default-schema=t818_review_return",
        "spring.datasource.hikari.schema=t818_review_return", "spring.jpa.properties.hibernate.default_schema=t818_review_return"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkReviewReturnApiIntegrationTest extends PostgresIntegrationTestSupport {
    private static final List<String> RETURNS = List.of("REJECTED", "REWORK_REQUIRED");
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private DataSource dataSource;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T818','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T818','ORDER-T818','BLOCKED')");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T818'", String.class)).isEqualTo("QUALITY_CHECKING");
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T818'", String.class)).isEqualTo("BLOCKED");
        } finally { jdbc.execute("DROP SCHEMA t818_review_return CASCADE"); }
    }

    private String tag(String value) { return value.replace('_', '-').toUpperCase(Locale.ROOT); }
    private String task(String id) { return "TASK-T818-" + id; }
    private String issue(String id) { return "ISSUE-T818-" + id; }
    private String rework(String id) { return "REWORK-T818-" + id; }
    private String check(String id, int seq) { return "CHECK-T818-" + id + "-" + seq; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }
    private String key(String id) { return "t818-" + id; }

    private void ready(String id, boolean managed) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T818','COMPLETED')", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','RESOLVED','本轮问题')", issue(id), task(id));
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','原始创建原因')", rework(id), task(id), issue(id));
        if (!managed) return;
        jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at)
                VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-10 00:00:00+00','original-handler',TIMESTAMPTZ '2026-11-10 00:01:00+00')
                """, rework(id), task(id), issue(id));
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,1,'成果-A','release-1','原始处理说明','[\"report:material\"]','handler-test',now())", rework(id));
        inspection(id, 1, "FAILED"); inspection(id, 2, "PASSED");
    }

    private void ready(String id) { ready(id, true); }
    private void inspection(String id, int seq, String result) {
        String items = "[{\"checkItem\":\"坐标系\",\"result\":\"" + result + "\",\"comment\":\"人工检查\",\"evidenceReferences\":[\"report:check\"]}]";
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,1,?,?,?::jsonb,'inspector-test',now())", check(id, seq), rework(id), seq, result, items);
    }

    private ObjectNode body(String id, long version, String status) {
        return mapper.createObjectNode().put("expectedVersion", version).put("processingRevision", 1)
                .put("inspectionId", check(id, 2)).put("status", status).put("reviewComment", "  人工复核退回：需要再次处理🚀  ");
    }

    private ResponseEntity<JsonNode> post(String path, JsonNode body, String key, String actor, String role) {
        var headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON); headers.set("X-Trace-Id", "trace-t818");
        if (key != null) headers.set("Idempotency-Key", key);
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        return http.exchange(path, HttpMethod.POST, new HttpEntity<>(body.toString(), headers), JsonNode.class);
    }
    private ResponseEntity<JsonNode> submit(String id, JsonNode body, String key) { return post(base(id) + "/review", body, key, "reviewer-test", "REVIEWER"); }
    private JsonNode get(String path) {
        var headers = new HttpHeaders(); headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER");
        var response = http.exchange(path, HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
        assertThat(response.getStatusCode().value()).isEqualTo(200); return response.getBody().path("data");
    }
    private JsonNode success(ResponseEntity<JsonNode> response, String status) {
        assertThat(response.getStatusCode().value()).isEqualTo(200); var envelope = response.getBody(); assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue(); assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse(); assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t818");
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t818");
        var receipt = envelope.path("data"); assertThat(receipt.size()).isEqualTo(12);
        assertThat(receipt.path("operation").asText()).isEqualTo("SUBMIT_REWORK_REVIEW");
        assertThat(receipt.path("reviewId").asText()).matches("^REVIEW-[A-Z0-9-]+$");
        assertThat(receipt.path("status").asText()).isEqualTo("COMPLETED");
        assertThat(receipt.path("issueStatus").asText()).isEqualTo(status.equals("APPROVED") ? "CLOSED" : "OPEN"); return receipt;
    }
    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status); assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("data").isNull()).isTrue(); assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("report:material", "request_hash", "原始处理说明");
    }
    private List<String> facts() {
        return Stream.of("production_tasks", "quality_issues", "rework_tasks", "rework_lifecycles", "rework_processing_revisions", "rework_inspections",
                "rework_reviews", "review_records", "idempotency_records", "operation_logs", "rework_operation_receipts")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + table + " r ORDER BY to_jsonb(r)::text", String.class).stream()).toList();
    }
    private List<String> materials(String id) {
        return Stream.of("rework_tasks", "rework_lifecycles", "rework_processing_revisions", "rework_inspections")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + table + " r WHERE rework_task_id=? ORDER BY to_jsonb(r)::text", String.class, rework(id)).stream()).toList();
    }
    private void absent(String key) {
        for (String table : List.of("idempotency_records", "rework_operation_receipts")) assertThat(jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE idempotency_key=?", Integer.class, key)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')", Integer.class, key)).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void savesReturnAndReopensOnlySourceIssueWhileAllCompletedEvidenceIsUnchanged(String status) throws Exception {
        String id = "VALID-" + tag(status); ready(id); var oldMaterials = materials(id);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','CLOSED','其他问题保持关闭')", issue(id + "-OTHER"), task(id));
        jdbc.update("INSERT INTO review_records VALUES (?,?,'REWORK_REQUIRED','原旧表历史')", "REVIEW-LEGACY-T818-" + tag(status), issue(id));
        var legacy = get("/api/tasks/" + task(id) + "/review"); Instant earliest = Instant.now(); var payload = body(id, 0, status);
        var receipt = success(submit(id, payload, key(id)), status); Instant latest = Instant.now();
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(1); assertThat(receipt.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(receipt.path("processingRevision").asLong()).isEqualTo(1); assertThat(receipt.path("inspectionId").asText()).isEqualTo(check(id, 2));
        assertThat(materials(id)).isEqualTo(oldMaterials);
        assertThat(jdbc.queryForObject("SELECT status FROM production_tasks WHERE task_id=?", String.class, task(id))).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("SELECT status FROM quality_issues WHERE issue_id=?", String.class, issue(id + "-OTHER"))).isEqualTo("CLOSED");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_tasks WHERE task_id=?", Integer.class, task(id))).isEqualTo(1);
        var row = jdbc.queryForMap("SELECT * FROM rework_reviews WHERE review_id=?", receipt.path("reviewId").asText());
        assertThat(row).containsEntry("status", status).containsEntry("review_comment", payload.path("reviewComment").asText())
                .containsEntry("reviewed_by", "reviewer-test").containsEntry("review_sequence", 1L);
        assertThat(((java.sql.Timestamp) row.get("reviewed_at")).toInstant()).isBetween(earliest, latest);
        var audit = jdbc.queryForMap("SELECT before_state,after_state,actor_user_id FROM operation_logs WHERE operation_id=?", receipt.path("operationId").asText());
        assertThat(audit).containsEntry("actor_user_id", "reviewer-test");
        assertThat(mapper.readTree(audit.get("before_state").toString()).path("issueStatus").asText()).isEqualTo("RESOLVED");
        var after = mapper.readTree(audit.get("after_state").toString());
        assertThat(after.path("issueStatus").asText()).isEqualTo("OPEN"); assertThat(after.path("reviewStatus").asText()).isEqualTo(status);
        assertThat(after.path("reviewComment")).isEqualTo(payload.path("reviewComment"));
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key=?", String.class, key(id)))).isEqualTo(receipt);
        var detail = get(base(id)); assertThat(detail.path("review").path("status").asText()).isEqualTo(status);
        assertThat(detail.path("allowedActions").toString()).contains("CREATE_NEXT_REWORK");
        var effective = get("/api/tasks/" + task(id) + "/effective-reviews").path("issues");
        JsonNode current = null;
        for (var entry : effective) if (entry.path("issueId").asText().equals(issue(id))) current = entry;
        assertThat(current).isNotNull(); assertThat(current.path("review").path("reviewId")).isEqualTo(receipt.path("reviewId"));
        assertThat(get(base(id) + "/reviews").path("records").get(0).path("status").asText()).isEqualTo(status);
        assertThat(get("/api/tasks/" + task(id) + "/review")).isEqualTo(legacy);
        var before = facts(); error(submit(id, body(id, 1, "APPROVED"), key(id) + "-approve-old-round"), 409, "BUSINESS_CONFLICT");
        absent(key(id) + "-approve-old-round"); assertThat(facts()).isEqualTo(before);
    }

    static Stream<Arguments> invalidContexts() {
        return RETURNS.stream().flatMap(status -> Stream.of("task", "rework", "issue-open", "issue-closed", "revision", "old-check", "latest-failed", "lifecycle")
                .map(kind -> Arguments.of(status, kind)));
    }
    @ParameterizedTest
    @MethodSource("invalidContexts")
    void refusesInvalidStatesAndStaleMaterialForBothConclusions(String status, String kind) {
        String id = "INVALID-" + tag(status) + "-" + tag(kind); ready(id, !kind.equals("lifecycle")); var payload = body(id, 0, status);
        switch (kind) {
            case "task" -> jdbc.update("UPDATE production_tasks SET status='RUNNING' WHERE task_id=?", task(id));
            case "rework" -> jdbc.update("UPDATE rework_tasks SET status='RUNNING' WHERE rework_task_id=?", rework(id));
            case "issue-open" -> jdbc.update("UPDATE quality_issues SET status='OPEN' WHERE issue_id=?", issue(id));
            case "issue-closed" -> jdbc.update("UPDATE quality_issues SET status='CLOSED' WHERE issue_id=?", issue(id));
            case "revision" -> payload.put("processingRevision", 2);
            case "old-check" -> payload.put("inspectionId", check(id, 1));
            case "latest-failed" -> inspection(id, 3, "FAILED");
            default -> { }
        }
        var before = facts(); error(submit(id, payload, key(id)), 409, "BUSINESS_CONFLICT"); absent(key(id)); assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void rechecksIdentityOwnershipVersionAndFullIdempotencyBinding(String status) {
        String id = "BIND-" + tag(status); ready(id); String other = id + "-OTHER"; ready(other); var payload = body(id, 0, status); var before = facts();
        error(post(base(id) + "/review", payload, key(id), null, "REVIEWER"), 401, "PERMISSION_DENIED"); absent(key(id));
        error(post(base(id) + "/review", payload, key(id), "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED"); absent(key(id));
        error(post(base(id).replace(task(id), task(other)) + "/review", payload, key(id), "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT"); absent(key(id));
        error(submit(id, body(id, 1, status), key(id)), 409, "BUSINESS_CONFLICT"); absent(key(id)); assertThat(facts()).isEqualTo(before);
        var original = success(submit(id, payload, key(id)), status);
        for (var changed : List.of(payload.deepCopy().put("status", "APPROVED"), payload.deepCopy().put("expectedVersion", 1),
                payload.deepCopy().put("processingRevision", 2), payload.deepCopy().put("inspectionId", check(id, 1)), payload.deepCopy().put("reviewComment", "另一份说明"))) {
            error(submit(id, changed, key(id)), 409, "BUSINESS_CONFLICT");
        }
        error(post(base(id) + "/review", payload, key(id), "another-user", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        error(post(base(id) + "/review", payload, key(id), "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        error(submit(other, body(other, 0, status), key(id)), 409, "BUSINESS_CONFLICT");
        before = facts(); assertThat(success(submit(id, payload, key(id)), status)).isEqualTo(original); assertThat(facts()).isEqualTo(before);
    }

    static Stream<Arguments> failurePoints() {
        return RETURNS.stream().flatMap(status -> Stream.of("version", "review", "issue", "reservation", "audit", "receipt")
                .flatMap(point -> Stream.of(false, true).map(zero -> Arguments.of(status, point, zero))));
    }
    private String table(String point) { return switch (point) { case "version" -> "production_tasks"; case "review" -> "rework_reviews"; case "issue" -> "quality_issues"; case "reservation" -> "idempotency_records"; case "audit" -> "operation_logs"; default -> "rework_operation_receipts"; }; }
    private void trigger(String table, String event, String code) {
        jdbc.execute("CREATE FUNCTION t818_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN " + code + " END $$");
        jdbc.execute("CREATE TRIGGER t818_fault BEFORE " + event + " ON " + table + " FOR EACH ROW EXECUTE FUNCTION t818_fault()");
    }
    private void removeTrigger(String table) { jdbc.execute("DROP TRIGGER t818_fault ON " + table); jdbc.execute("DROP FUNCTION t818_fault()"); }

    @ParameterizedTest
    @MethodSource("failurePoints")
    void returnReviewAndIssueReopeningRollBackTogether(String status, String point, boolean zero) {
        String id = "ROLL-" + tag(status) + "-" + tag(point) + (zero ? "-ZERO" : "-THROW"); ready(id); var before = facts(); String table = table(point);
        trigger(table, List.of("version", "issue", "reservation").contains(point) ? "UPDATE" : "INSERT", zero ? "RETURN NULL;" : "RAISE EXCEPTION 'forced T818 failure';");
        try {
            error(submit(id, body(id, 0, status), key(id)), zero ? 409 : 500, zero ? "BUSINESS_CONFLICT" : "INTERNAL_SERVER_ERROR");
            absent(key(id)); assertThat(facts()).isEqualTo(before);
        } finally { removeTrigger(table); }
        success(submit(id, body(id, 0, status), key(id)), status);
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void failureAtCommitLeavesNoReviewReopeningOrOperationRecord(String status) {
        String id = "COMMIT-" + tag(status); ready(id); var before = facts();
        jdbc.execute("CREATE FUNCTION t818_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T818 commit failure'; END $$");
        jdbc.execute("CREATE CONSTRAINT TRIGGER t818_commit AFTER INSERT ON rework_operation_receipts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION t818_commit()");
        try {
            error(submit(id, body(id, 0, status), key(id)), 500, "INTERNAL_SERVER_ERROR"); absent(key(id)); assertThat(facts()).isEqualTo(before);
        } finally { jdbc.execute("DROP TRIGGER t818_commit ON rework_operation_receipts"); jdbc.execute("DROP FUNCTION t818_commit()"); }
        success(submit(id, body(id, 0, status), key(id)), status);
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void outsideReadersCannotSeeReopenedIssueWithoutItsReview(String status) throws Exception {
        String id = "OBSERVE-" + tag(status); ready(id); var before = get(base(id)); var all = facts();
        trigger("rework_operation_receipts", "INSERT", "PERFORM pg_advisory_xact_lock(818,1); RETURN NEW;");
        try (var pool = Executors.newSingleThreadExecutor(); var blocker = dataSource.getConnection()) {
            try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_lock(818,1)"); }
            var response = pool.submit(() -> submit(id, body(id, 0, status), key(id)));
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=818 AND objid=1 AND objsubid=2 AND NOT granted", Integer.class);
                    if (waiting == 1) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).isEqualTo(1); assertThat(response.isDone()).isFalse(); assertThat(get(base(id))).isEqualTo(before); assertThat(facts()).isEqualTo(all);
            } finally { try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_unlock(818,1)"); } }
            success(response.get(30, TimeUnit.SECONDS), status);
        } finally { removeTrigger("rework_operation_receipts"); }
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
    static Stream<Arguments> duplicateCases() { return RETURNS.stream().flatMap(status -> Stream.of(true, false).map(same -> Arguments.of(status, same))); }
    @ParameterizedTest
    @MethodSource("duplicateCases")
    void duplicateReturnsCommitOneReviewAndOneVersion(String status, boolean sameKey) throws Exception {
        String id = "DUP-" + tag(status) + (sameKey ? "-SAME" : "-DIFFERENT"); ready(id); String other = sameKey ? key(id) : key(id) + "-other";
        var responses = concurrent(id, () -> submit(id, body(id, 0, status), key(id)), () -> submit(id, body(id, 0, status), other));
        if (sameKey) assertThat(success(responses.get(0), status)).isEqualTo(success(responses.get(1), status));
        else {
            assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
            int winner = responses.get(0).getStatusCode().value() == 200 ? 0 : 1; success(responses.get(winner), status); absent(winner == 0 ? other : key(id));
        }
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_reviews WHERE rework_task_id=?", Integer.class, rework(id))).isEqualTo(1);
        assertThat(get(base(id)).path("taskVersion").asLong()).isEqualTo(1);
    }
    static Stream<Arguments> competingConclusions() { return Stream.of(Arguments.of("APPROVED", "REJECTED"), Arguments.of("APPROVED", "REWORK_REQUIRED"), Arguments.of("REJECTED", "REWORK_REQUIRED")); }
    @ParameterizedTest
    @MethodSource("competingConclusions")
    void differentFinalConclusionsCannotBothCommit(String first, String second) throws Exception {
        String id = "RACE-" + tag(first) + "-" + tag(second); ready(id); String other = key(id) + "-other";
        var responses = concurrent(id, () -> submit(id, body(id, 0, first), key(id)), () -> submit(id, body(id, 0, second), other));
        assertThat(responses.stream().map(r -> r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200, 409);
        int winner = responses.get(0).getStatusCode().value() == 200 ? 0 : 1; String conclusion = winner == 0 ? first : second;
        success(responses.get(winner), conclusion); error(responses.get(1 - winner), 409, "BUSINESS_CONFLICT"); absent(winner == 0 ? other : key(id));
        assertThat(get(base(id)).path("review").path("status").asText()).isEqualTo(conclusion);
        assertThat(get(base(id)).path("taskVersion").asLong()).isEqualTo(1);
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void originalReturnReplayCannotReopenAnIssueClosedByALaterRound(String status) {
        String id = "LATER-" + tag(status); ready(id); var payload = body(id, 0, status); var original = success(submit(id, payload, key(id)), status);
        String next = rework(id + "-NEXT"), nextCheck = check(id + "-NEXT", 1);
        // T819创建接口尚未实现；用明确的第二轮SQL夹具模拟未来已完成轮次，复核与旧回执重放仍经真实HTTP。
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','下一轮人工处理')", next, task(id), issue(id));
        jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at,started_by,started_at)
                VALUES (?,?,?,2,?,1,'creator-test',now(),'handler-test',now())
                """, next, task(id), issue(id), rework(id));
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,1,'成果-A','release-2','后继处理','[\"report:next\"]','handler-test',now())", next);
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,1,1,'PASSED','[{\"checkItem\":\"坐标系\",\"result\":\"PASSED\",\"comment\":\"再次检查\",\"evidenceReferences\":[\"report:next-check\"]}]','inspector-test',now())", nextCheck, next);
        jdbc.update("UPDATE quality_issues SET status='RESOLVED' WHERE issue_id=?", issue(id));
        var approved = body(id, 1, "APPROVED").put("inspectionId", nextCheck);
        success(post("/api/tasks/" + task(id) + "/reworks/" + next + "/review", approved, key(id) + "-next", "reviewer-test", "REVIEWER"), "APPROVED");
        var before = facts(); assertThat(success(submit(id, payload, key(id)), status)).isEqualTo(original); assertThat(facts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT status FROM quality_issues WHERE issue_id=?", String.class, issue(id))).isEqualTo("CLOSED");
        var effective = get("/api/tasks/" + task(id) + "/effective-reviews").path("issues").get(0);
        assertThat(effective.path("roundNumber").asLong()).isEqualTo(2); assertThat(effective.path("review").path("status").asText()).isEqualTo("APPROVED");
        assertThat(get(base(id) + "/reviews").path("records").get(0).path("status").asText()).isEqualTo(status);
    }

    @ParameterizedTest
    @ValueSource(strings = {"REJECTED", "REWORK_REQUIRED"})
    void actualStartMaterialAndPassedInspectionCanBeReturnedWithoutRestartingCompletedProduction(String status) {
        String id = "FLOW-" + tag(status);
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T818','COMPLETED')", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','完整HTTP退回链路')", issue(id), task(id));
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','原始创建原因')", rework(id), task(id), issue(id));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,?,?,1,'creator-test',now())", rework(id), task(id), issue(id));
        assertThat(post(base(id) + "/start", mapper.createObjectNode().put("expectedVersion", 0), key(id) + "-start", "reviewer-test", "REVIEWER").getStatusCode().value()).isEqualTo(200);
        var material = mapper.createObjectNode().put("expectedVersion", 1).put("processingComment", "实际人工处理说明");
        material.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "release-1"); material.putArray("evidenceReferences").add("report:material");
        assertThat(post(base(id) + "/results", material, key(id) + "-material", "reviewer-test", "REVIEWER").getStatusCode().value()).isEqualTo(200);
        var check = mapper.createObjectNode().put("expectedVersion", 2).put("processingRevision", 1);
        var item = check.putArray("items").addObject().put("checkItem", "坐标系").put("result", "PASSED").put("comment", "实际人工检查");
        item.putArray("evidenceReferences").add("report:check");
        var checked = post(base(id) + "/inspections", check, key(id) + "-check", "reviewer-test", "REVIEWER");
        assertThat(checked.getStatusCode().value()).isEqualTo(200); var oldMaterials = materials(id);
        var payload = body(id, 3, status).put("inspectionId", checked.getBody().path("data").path("inspectionId").asText());
        var receipt = success(submit(id, payload, key(id)), status); assertThat(receipt.path("taskVersion").asLong()).isEqualTo(4);
        assertThat(materials(id)).isEqualTo(oldMaterials); assertThat(jdbc.queryForObject("SELECT status FROM production_tasks WHERE task_id=?", String.class, task(id))).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_tasks WHERE task_id=?", Integer.class, task(id))).isEqualTo(1);
        var before = facts(); error(post(base(id) + "/start", mapper.createObjectNode().put("expectedVersion", 4), key(id) + "-restart", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        absent(key(id) + "-restart"); assertThat(facts()).isEqualTo(before);
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
