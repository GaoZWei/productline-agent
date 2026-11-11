package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.application.DeliveryConditionsService;
import com.productline.business.domain.repository.DeliveryConditionsRepository;
import com.productline.business.domain.repository.EffectiveReviewRepository;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
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
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.LinkedMultiValueMap;

/** 只读交付条件与关闭并发：当前复核、其他问题及版本必须来自同一快照。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t820_conditions", "spring.flyway.default-schema=t820_conditions",
        "spring.datasource.hikari.schema=t820_conditions", "spring.jpa.properties.hibernate.default_schema=t820_conditions"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class DeliveryConditionsApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    @Autowired private DataSource dataSource;
    @Autowired private PlatformTransactionManager manager;
    @Autowired private EffectiveReviewRepository reviews;
    private List<String> goldenBefore;

    @BeforeAll void prepare() { goldenBefore = golden(); }
    @AfterAll void cleanup() {
        try { assertThat(golden()).isEqualTo(goldenBefore); }
        finally { jdbc.execute("DROP SCHEMA t820_conditions CASCADE"); }
    }

    private String order(String id) { return "ORDER-T820-" + id; }
    private String task(String id) { return "TASK-T820-" + id; }
    private String issue(String id) { return "ISSUE-T820-" + id; }
    private String rework(String id) { return "REWORK-T820-" + id; }
    private String check(String id, int seq) { return "CHECK-T820-" + id + "-" + seq; }
    private String path(String id) { return "/api/orders/" + order(id) + "/delivery-conditions"; }
    private String base(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id); }
    private void fixture(String id) {
        jdbc.update("INSERT INTO production_orders VALUES (?,'DOM','QUALITY_CHECKING')", order(id));
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,?,'COMPLETED')", task(id), order(id));
        jdbc.update("INSERT INTO production_steps VALUES (?,?,'生产处理',1,'COMPLETED')", "STEP-T820-" + id, task(id));
        jdbc.update("INSERT INTO delivery_records VALUES (?,?,'READY')", "DELIVERY-T820-" + id, order(id));
    }
    private void managed(String id, String parentTask) {
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','RESOLVED','人工处理后的来源问题')", issue(id), parentTask);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','独立返工原因')", rework(id), parentTask, issue(id));
        jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at)
                VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-11 00:00:00+00','handler-test',TIMESTAMPTZ '2026-11-11 00:01:00+00')
                """, rework(id), parentTask, issue(id));
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,1,'成果-A','release-1','人工处理说明','[\"report:material\"]','handler-test',now())", rework(id));
        inspection(id, 1, 1, "PASSED");
    }
    private void ready(String id) { fixture(id); managed(id, task(id)); }
    private void inspection(String id, int revision, int seq, String result) {
        String items = "[{\"checkItem\":\"坐标系\",\"result\":\"" + result + "\",\"comment\":\"人工检查\",\"evidenceReferences\":[\"report:check\"]}]";
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,?,?,?,?::jsonb,'inspector-test',now())", check(id, seq), rework(id), revision, seq, result, items);
    }
    private void review(String id, int revision, int checkSequence, int sequence, String status) {
        jdbc.update("""
                INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at)
                VALUES (?,?,?,?,?,?,?,'reviewer-test',now())
                """, "REVIEW-T820-" + id + "-" + sequence, rework(id), revision, check(id, checkSequence), sequence, status, "保留复核意见");
    }
    private ResponseEntity<JsonNode> get(String url, String user, String role) {
        var headers = new HttpHeaders(); headers.set("X-Trace-Id", "trace-t820");
        if (user != null) headers.set("X-User-Id", user); if (role != null) headers.set("X-User-Role", role);
        return http.exchange(url, HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
    }
    private JsonNode read(String id) { return ok(get(path(id), "reviewer-test", "REVIEWER")); }
    private ResponseEntity<JsonNode> post(String url, JsonNode body, String key) {
        var headers = new HttpHeaders(); headers.setContentType(MediaType.APPLICATION_JSON); headers.set("X-Trace-Id", "trace-t820");
        headers.set("X-User-Id", "reviewer-test"); headers.set("X-User-Role", "REVIEWER"); headers.set("Idempotency-Key", key);
        return http.exchange(url, HttpMethod.POST, new HttpEntity<>(body.toString(), headers), JsonNode.class);
    }
    private ResponseEntity<JsonNode> submit(String parentId, String childId, long version, String status, String key) {
        return post("/api/tasks/" + task(parentId) + "/reworks/" + rework(childId) + "/review",
                mapper.createObjectNode().put("expectedVersion", version).put("processingRevision", 1).put("inspectionId", check(childId, 1))
                        .put("status", status).put("reviewComment", "本次人工复核意见"), key);
    }
    private JsonNode ok(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200); var envelope = response.getBody();
        assertThat(envelope.size()).isEqualTo(6); assertThat(envelope.path("success").asBoolean()).isTrue();
        assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS"); assertThat(envelope.path("retryable").asBoolean()).isFalse();
        assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t820");
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t820"); return envelope.path("data");
    }
    private void error(ResponseEntity<JsonNode> response, int status) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(switch (status) {
            case 400 -> "PARAM_VALIDATION_ERROR"; case 401, 403 -> "PERMISSION_DENIED"; case 404 -> "RESOURCE_NOT_FOUND";
            case 409 -> "BUSINESS_CONFLICT"; default -> "INTERNAL_SERVER_ERROR";
        });
        assertThat(response.getBody().path("data").isNull()).isTrue(); assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
    }
    private List<String> codes(JsonNode response) {
        return java.util.stream.StreamSupport.stream(response.path("blockers").spliterator(), false).map(row -> row.path("code").asText()).toList();
    }
    private JsonNode effective(JsonNode response) { return response.path("tasks").get(0).path("issues").get(0).path("effectiveReview"); }
    private List<String> facts() {
        return Stream.of("production_orders", "production_tasks", "production_steps", "quality_issues", "review_records", "rework_tasks", "delivery_records",
                "rework_lifecycles", "rework_processing_revisions", "rework_inspections", "rework_reviews", "idempotency_records", "operation_logs", "rework_operation_receipts")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + table + " r ORDER BY to_jsonb(r)::text", String.class).stream()).toList();
    }
    private void unchangedOrder(String id) {
        assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id=?", String.class, order(id))).isEqualTo("QUALITY_CHECKING");
        assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE order_id=?", String.class, order(id))).isEqualTo("READY");
    }

    @Test
    void currentApprovalIgnoresOldControlledAndLegacyFailuresWithoutDeletingHistory() {
        String id = "CURRENT"; ready(id); review(id, 1, 1, 1, "REWORK_REQUIRED"); review(id, 1, 1, 2, "APPROVED");
        jdbc.update("UPDATE quality_issues SET status='CLOSED' WHERE issue_id=?", issue(id));
        jdbc.update("INSERT INTO review_records VALUES (?,?,'PENDING',NULL)", "REVIEW-T820-LEGACY-CURRENT", issue(id));
        var before = facts(); var response = read(id);
        assertThat(response.size()).isEqualTo(5); assertThat(response.path("hasBlockers").asBoolean()).isFalse(); assertThat(codes(response)).isEmpty();
        assertThat(effective(response).path("review").path("status").asText()).isEqualTo("APPROVED");
        assertThat(effective(response).path("legacyReviews").isEmpty()).isTrue();
        assertThat(read(id)).isEqualTo(response); assertThat(facts()).isEqualTo(before); unchangedOrder(id);
        assertThat(ok(get(base(id) + "/reviews", "reviewer-test", "REVIEWER")).path("records").size()).isEqualTo(2);
        assertThat(ok(get("/api/tasks/" + task(id) + "/review", "reviewer-test", "REVIEWER")).path("reviews").get(0).path("status").asText()).isEqualTo("PENDING");
    }

    @ParameterizedTest
    @ValueSource(strings = {"NO-REVIEW", "REJECTED", "REWORK_REQUIRED", "NEW-REVISION", "NEW-FAILED", "NEW-PASSED", "OLD-BINDING"})
    void historicalApprovalCannotAuthorizeTheCurrentBinding(String condition) {
        String id = "BIND-" + condition; ready(id);
        if (!condition.equals("NO-REVIEW")) review(id, 1, 1, 1, "APPROVED");
        jdbc.update("UPDATE quality_issues SET status='CLOSED' WHERE issue_id=?", issue(id));
        switch (condition) {
            case "REJECTED", "REWORK_REQUIRED" -> review(id, 1, 1, 2, condition);
            case "NEW-REVISION" -> jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,2,'成果-A','release-2','新说明','[\"report:new\"]','handler-test',now())", rework(id));
            case "NEW-FAILED" -> inspection(id, 1, 2, "FAILED");
            case "NEW-PASSED" -> inspection(id, 1, 2, "PASSED");
            case "OLD-BINDING" -> { inspection(id, 1, 2, "PASSED"); review(id, 1, 1, 99, "APPROVED"); }
            default -> { }
        }
        var before = facts(); var response = read(id); assertThat(codes(response)).containsExactly("EFFECTIVE_REVIEW_NOT_APPROVED");
        assertThat(response.path("hasBlockers").asBoolean()).isTrue(); assertThat(facts()).isEqualTo(before);
        if (!List.of("REJECTED", "REWORK_REQUIRED").contains(condition)) assertThat(effective(response).path("review").isNull()).isTrue();
    }

    @ParameterizedTest
    @ValueSource(strings = {"PENDING", "REJECTED", "REWORK_REQUIRED", "NONE", "APPROVED"})
    void legacyIssuesExplicitlyKeepTheirExistingRules(String status) {
        String id = "LEGACY-" + status; fixture(id);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','RESOLVED','旧问题')", issue(id), task(id));
        if (!status.equals("NONE")) jdbc.update("INSERT INTO review_records VALUES (?,?,?,'旧意见')", "REVIEW-T820-" + id, issue(id), status);
        if (List.of("PENDING", "REJECTED", "REWORK_REQUIRED").contains(status)) jdbc.update("INSERT INTO review_records VALUES (?,?,'APPROVED','另有旧通过')", "REVIEW-T820-" + id + "-PASS", issue(id));
        var before = facts(); var response = read(id);
        assertThat(effective(response).path("roundNumber").isNull()).isTrue(); assertThat(effective(response).path("review").isNull()).isTrue();
        assertThat(codes(response)).containsExactlyElementsOf(status.equals("APPROVED") ? List.of() : status.equals("NONE")
                ? List.of("LEGACY_RESOLVED_ISSUE_WITHOUT_APPROVAL") : List.of("LEGACY_REVIEW_NOT_APPROVED"));
        assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"ORDER", "TASK", "STEP", "NO-STEPS", "NO-TASKS", "ISSUE", "DELIVERY", "NO-DELIVERIES", "ACTIVE", "MANAGED-FAILED"})
    void otherKnownConditionsRemainBlockedAfterSourceIssueIsApproved(String condition) {
        String id = "OTHER-" + condition; ready(id); ok(submit(id, id, 0, "APPROVED", "t820-" + id));
        String expected = switch (condition) {
            case "ORDER" -> { jdbc.update("UPDATE production_orders SET status='BLOCKED' WHERE order_id=?", order(id)); yield "ORDER_BLOCKED"; }
            case "TASK" -> { jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,?,'FAILED')", task(id + "-OTHER"), order(id)); yield "PRODUCTION_TASK_NOT_COMPLETED"; }
            case "STEP" -> { jdbc.update("UPDATE production_steps SET status='BLOCKED' WHERE task_id=?", task(id)); yield "PRODUCTION_STEP_NOT_COMPLETED"; }
            case "NO-STEPS" -> { jdbc.update("DELETE FROM production_steps WHERE task_id=?", task(id)); yield "MISSING_PRODUCTION_STEPS"; }
            case "NO-TASKS" -> { jdbc.update("INSERT INTO production_orders VALUES (?,'DOM','CREATED')", order(id + "-EMPTY")); yield "MISSING_PRODUCTION_TASKS"; }
            case "ISSUE" -> { jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','其他问题仍待处理')", issue(id + "-OTHER"), task(id)); yield "QUALITY_ISSUE_UNRESOLVED"; }
            case "DELIVERY" -> { jdbc.update("UPDATE delivery_records SET status='BLOCKED' WHERE order_id=?", order(id)); yield "DELIVERY_NOT_READY"; }
            case "NO-DELIVERIES" -> { jdbc.update("DELETE FROM delivery_records WHERE order_id=?", order(id)); yield "MISSING_DELIVERY_RECORDS"; }
            case "ACTIVE" -> { jdbc.update("INSERT INTO rework_tasks VALUES (?,?,NULL,'PENDING','无来源的旧活动返工')", rework(id + "-OTHER"), task(id)); yield "ACTIVE_REWORK"; }
            default -> { managed(id + "-OTHER", task(id)); jdbc.update("UPDATE rework_tasks SET status='FAILED' WHERE rework_task_id=?", rework(id + "-OTHER")); yield "ACTIVE_REWORK"; }
        };
        var before = facts(); var response = read(condition.equals("NO-TASKS") ? id + "-EMPTY" : id);
        assertThat(codes(response)).contains(expected); assertThat(response.path("hasBlockers").asBoolean()).isTrue(); assertThat(facts()).isEqualTo(before);
        if (!condition.equals("NO-TASKS")) assertThat(effective(response).path("review").path("status").asText()).isEqualTo("APPROVED");
    }

    @ParameterizedTest
    @ValueSource(strings = {"NOT_READY", "BLOCKED", "FAILED", "READY", "DELIVERING", "DELIVERED"})
    void deliveryRecordsAreReportedWithoutAdvancingTheirStatuses(String status) {
        String id = "DELIVERY-" + status; fixture(id); jdbc.update("UPDATE delivery_records SET status=? WHERE order_id=?", status, order(id));
        var before = facts(); var response = read(id);
        assertThat(codes(response)).containsExactlyElementsOf(List.of("NOT_READY", "BLOCKED", "FAILED").contains(status) ? List.of("DELIVERY_NOT_READY") : List.of());
        assertThat(response.path("deliveryRecords").get(0).path("status").asText()).isEqualTo(status); assertThat(facts()).isEqualTo(before);
    }

    @Test
    void allSiblingFactsAreSortedAndForeignOrderBlockersAreExcluded() {
        String id = "ORDER-SCOPE"; fixture(id); String foreign = id + "-FOREIGN"; ready(foreign);
        jdbc.update("UPDATE delivery_records SET status='BLOCKED' WHERE order_id=?", order(foreign));
        for (String suffix : List.of("Z", "A")) {
            jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,?,'COMPLETED')", task(id + "-" + suffix), order(id));
            jdbc.update("INSERT INTO production_steps VALUES (?,?,'同订单其他生产',1,'COMPLETED')", "STEP-T820-" + id + "-" + suffix, task(id + "-" + suffix));
        }
        jdbc.update("INSERT INTO delivery_records VALUES (?,?,'READY')", "DELIVERY-T820-" + id + "-SECOND", order(id));
        var before = facts(); var response = read(id);
        assertThat(java.util.stream.StreamSupport.stream(response.path("tasks").spliterator(), false).map(row -> row.path("taskId").asText()).toList())
                .containsExactly(task(id), task(id + "-A"), task(id + "-Z"));
        assertThat(response.path("deliveryRecords").size()).isEqualTo(2); assertThat(codes(response)).isEmpty();
        assertThat(response.toString()).doesNotContain(task(foreign), issue(foreign)); assertThat(facts()).isEqualTo(before);
    }

    @Test
    void readRejectsUnauthorizedIdentityInvalidIdsAndAllFiltersWithoutWrites() {
        String id = "AUTH"; ready(id); var before = facts();
        error(get(path(id), null, "REVIEWER"), 401); error(get(path(id), "reviewer-test", "VIEWER"), 403);
        error(get(path(id), "reviewer-test", null), 403); error(get(path(id), "x".repeat(129), "REVIEWER"), 400);
        error(get(path("MISSING"), "reviewer-test", "REVIEWER"), 404);
        error(get("/api/orders/order-lower/delivery-conditions", "reviewer-test", "REVIEWER"), 400);
        for (String query : List.of("limit=1", "cursor=x", "status=CLOSED", "issueId=x", "role=REVIEWER", "x=&x=")) error(get(path(id) + "?" + query, "reviewer-test", "REVIEWER"), 400);
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void currentGoldenFactsAreReportedWithoutChangingTheOldDiagnosisOrFixtures() {
        var before = facts(); var response = ok(get("/api/orders/ORDER-003/delivery-conditions", "reviewer-test", "REVIEWER"));
        assertThat(codes(response)).contains("QUALITY_ISSUE_UNRESOLVED", "LEGACY_REVIEW_NOT_APPROVED", "DELIVERY_NOT_READY");
        assertThat(response.path("tasks").get(0).path("productionStatus").asText()).isEqualTo("COMPLETED");
        assertThat(effective(response).path("legacyReviews").get(0).path("status").asText()).isEqualTo("PENDING");
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void orderFactsAndReviewUseOneIndependentReadOnlySnapshotDuringRealHttpClosure() {
        String id = "SNAPSHOT"; ready(id);
        var observing = new DeliveryConditionsRepository(jdbc) {
            @Override public List<TaskFact> tasks(String orderId) {
                assertThat(jdbc.queryForObject("SHOW transaction_isolation", String.class)).isEqualTo("repeatable read");
                assertThat(jdbc.queryForObject("SHOW transaction_read_only", String.class)).isEqualTo("on");
                var previous = super.tasks(orderId);
                ok(submit(id, id, 0, "APPROVED", "t820-snapshot-close"));
                return previous;
            }
        };
        var service = new DeliveryConditionsService(observing, reviews, manager);
        var old = new TransactionTemplate(manager).execute(status -> service.read(order(id), "reviewer-test", "REVIEWER", new LinkedMultiValueMap<>()));
        assertThat(old.tasks().get(0).taskVersion()).isZero();
        assertThat(old.tasks().get(0).issues().get(0).issue().status().name()).isEqualTo("RESOLVED");
        assertThat(old.tasks().get(0).issues().get(0).effectiveReview().review()).isNull(); assertThat(old.hasBlockers()).isTrue();
        var fresh = read(id); assertThat(fresh.path("tasks").get(0).path("taskVersion").asLong()).isEqualTo(1);
        assertThat(codes(fresh)).isEmpty(); assertThat(effective(fresh).path("review").path("status").asText()).isEqualTo("APPROVED"); unchangedOrder(id);
    }

    @Test
    void twoIssueClosuresCompeteForOneVersionAndTheUnclosedIssueRemainsVisible() throws Exception {
        String id = "TWO-ISSUES"; ready(id); String other = id + "-OTHER"; managed(other, task(id));
        try (var pool = Executors.newFixedThreadPool(2); var blocker = dataSource.getConnection()) {
            blocker.setAutoCommit(false);
            try (var statement = blocker.prepareStatement("SELECT task_id FROM production_tasks WHERE task_id=? FOR UPDATE")) {
                statement.setString(1, task(id)); try (var row = statement.executeQuery()) { assertThat(row.next()).isTrue(); }
            }
            var a = pool.submit(() -> submit(id, id, 0, "APPROVED", "t820-close-a"));
            var b = pool.submit(() -> submit(id, other, 0, "APPROVED", "t820-close-b"));
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND wait_event_type='Lock' AND lower(query) LIKE '%production_tasks%'", Integer.class);
                    if (waiting == 2) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).as("both real HTTP reviews must reach the shared parent lock").isEqualTo(2);
            } finally { blocker.rollback(); }
            var first = a.get(30, TimeUnit.SECONDS); var second = b.get(30, TimeUnit.SECONDS);
            assertThat(List.of(first.getStatusCode().value(), second.getStatusCode().value())).containsExactlyInAnyOrder(200, 409);
            String loser = first.getStatusCode().value() == 200 ? "t820-close-b" : "t820-close-a";
            assertThat(jdbc.queryForObject("SELECT count(*) FROM idempotency_records WHERE idempotency_key=?", Integer.class, loser)).isZero();
            var response = read(id); assertThat(response.path("tasks").get(0).path("taskVersion").asLong()).isEqualTo(1);
            assertThat(codes(response)).containsExactly("CONTROLLED_ISSUE_NOT_CLOSED", "EFFECTIVE_REVIEW_NOT_APPROVED");
            assertThat(jdbc.queryForObject("SELECT count(*) FROM quality_issues WHERE task_id=? AND status='CLOSED'", Integer.class, task(id))).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_reviews WHERE rework_task_id IN (?,?)", Integer.class, rework(id), rework(other))).isEqualTo(1);
        }
        unchangedOrder(id);
    }

    @Test
    void outsideHttpReadersCannotSeeClosureWithoutItsReviewAndVersion() throws Exception {
        String id = "UNCOMMITTED"; ready(id); var before = read(id); var all = facts();
        jdbc.execute("CREATE FUNCTION t820_pause() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(820,1); RETURN NEW; END $$");
        jdbc.execute("CREATE TRIGGER t820_pause BEFORE INSERT ON rework_operation_receipts FOR EACH ROW EXECUTE FUNCTION t820_pause()");
        try (var pool = Executors.newSingleThreadExecutor(); var blocker = dataSource.getConnection()) {
            try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_lock(820,1)"); }
            var pending = pool.submit(() -> submit(id, id, 0, "APPROVED", "t820-uncommitted"));
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10); int waiting;
                do {
                    waiting = jdbc.queryForObject("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=820 AND objid=1 AND objsubid=2 AND NOT granted", Integer.class);
                    if (waiting == 1) break; Thread.sleep(10);
                } while (System.nanoTime() < deadline);
                assertThat(waiting).isEqualTo(1); assertThat(pending.isDone()).isFalse(); assertThat(read(id)).isEqualTo(before); assertThat(facts()).isEqualTo(all);
            } finally { try (var statement = blocker.createStatement()) { statement.execute("SELECT pg_advisory_unlock(820,1)"); } }
            ok(pending.get(30, TimeUnit.SECONDS));
        } finally { jdbc.execute("DROP TRIGGER t820_pause ON rework_operation_receipts"); jdbc.execute("DROP FUNCTION t820_pause()"); }
        assertThat(codes(read(id))).isEmpty(); unchangedOrder(id);
    }

    @Test
    void actualReturnedRoundAndSuccessorApprovalRecomputeConditionsWithoutAutomaticDelivery() {
        String id = "TWO-ROUNDS"; ready(id); ok(submit(id, id, 0, "REWORK_REQUIRED", "t820-flow-return"));
        var returned = read(id); assertThat(codes(returned)).contains("CONTROLLED_ISSUE_NOT_CLOSED", "EFFECTIVE_REVIEW_NOT_APPROVED");
        var next = ok(post(base(id) + "/next-round", mapper.createObjectNode().put("expectedVersion", 1).put("reason", "重新确认创建后继"), "t820-flow-next"));
        String nextBase = "/api/tasks/" + task(id) + "/reworks/" + next.path("reworkTaskId").asText();
        var pending = read(id); assertThat(codes(pending)).contains("ACTIVE_REWORK", "EFFECTIVE_REVIEW_NOT_APPROVED");
        assertThat(effective(pending).path("roundNumber").asLong()).isEqualTo(2); assertThat(effective(pending).path("review").isNull()).isTrue();
        ok(post(nextBase + "/start", mapper.createObjectNode().put("expectedVersion", 2), "t820-flow-start"));
        var material = mapper.createObjectNode().put("expectedVersion", 3).put("processingComment", "后继实际处理");
        material.putObject("artifact").put("artifactId", "成果-A").put("artifactVersion", "release-2"); material.putArray("evidenceReferences").add("report:second");
        ok(post(nextBase + "/results", material, "t820-flow-result"));
        var check = mapper.createObjectNode().put("expectedVersion", 4).put("processingRevision", 1);
        check.putArray("items").addObject().put("checkItem", "坐标系").put("result", "PASSED").put("comment", "后继人工检查").putArray("evidenceReferences").add("report:second-check");
        var checked = ok(post(nextBase + "/inspections", check, "t820-flow-check"));
        ok(post(nextBase + "/review", mapper.createObjectNode().put("expectedVersion", 5).put("processingRevision", 1)
                .put("inspectionId", checked.path("inspectionId").asText()).put("status", "APPROVED").put("reviewComment", "后继再次复核通过"), "t820-flow-approve"));
        var closed = read(id); assertThat(codes(closed)).isEmpty(); assertThat(effective(closed).path("review").path("status").asText()).isEqualTo("APPROVED");
        assertThat(closed.path("tasks").get(0).path("taskVersion").asLong()).isEqualTo(6);
        assertThat(ok(get(base(id) + "/reviews", "reviewer-test", "REVIEWER")).path("records").get(0).path("status").asText()).isEqualTo("REWORK_REQUIRED");
        unchangedOrder(id);
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
