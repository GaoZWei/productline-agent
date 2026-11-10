package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.productline.business.application.EffectiveReviewService;
import com.productline.business.domain.repository.EffectiveReviewRepository;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
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
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.LinkedMultiValueMap;

/** 同一只读快照内选有效绑定，完整历史另读，不让旧通过代替新成果或旧失败永久阻塞。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t816_review", "spring.flyway.default-schema=t816_review",
        "spring.datasource.hikari.schema=t816_review", "spring.jpa.properties.hibernate.default_schema=t816_review"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class EffectiveReviewApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private com.fasterxml.jackson.databind.ObjectMapper mapper;
    @Autowired private DataSource dataSource;
    @Autowired private PlatformTransactionManager manager;
    private List<String> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T816','DOM','QUALITY_CHECKING')");
        jdbc.update("INSERT INTO delivery_records VALUES ('DELIVERY-T816','ORDER-T816','BLOCKED')");
        fixture("HISTORY", true); processing("HISTORY", 1, 1); processing("HISTORY", 1, 2);
        inspection("HISTORY", 1, 1, 1, "PASSED"); inspection("HISTORY", 1, 2, 2, "PASSED");
        for (long sequence = 1; sequence <= 35; sequence++) review("HISTORY", 1, sequence % 2 == 0 ? 2 : 1,
                sequence % 2 == 0 ? 2 : 1, sequence, sequence % 3 == 0 ? "REJECTED" : "APPROVED");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
            assertThat(jdbc.queryForObject("SELECT status FROM production_orders WHERE order_id='ORDER-T816'", String.class)).isEqualTo("QUALITY_CHECKING");
            assertThat(jdbc.queryForObject("SELECT status FROM delivery_records WHERE delivery_id='DELIVERY-T816'", String.class)).isEqualTo("BLOCKED");
        } finally { jdbc.execute("DROP SCHEMA t816_review CASCADE"); }
    }

    private String task(String id) { return "TASK-T816-" + id; }
    private String issue(String id) { return "ISSUE-T816-" + id; }
    private String rework(String id, int round) { return "REWORK-T816-" + id + "-" + round; }
    private String check(String id, int round, long sequence) { return "CHECK-T816-" + id + "-" + round + "-" + sequence; }
    private String reviewId(String id, int round, long sequence) { return "REVIEW-T816-" + id + "-" + round + "-" + (1000 - sequence); }
    private String effective(String id) { return "/api/tasks/" + task(id) + "/effective-reviews"; }
    private String history(String id, int round) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id, round) + "/reviews"; }

    private void fixture(String id, boolean controlled) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status,version) VALUES (?,'ORDER-T816','COMPLETED',7)", task(id));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','RESOLVED','独立有效复核测试')", issue(id), task(id));
        if (controlled) round(id, 1);
    }

    private void round(String id, int number) {
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','原始返工原因')", rework(id, number), task(id), issue(id));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES (?,?,?,?,?,?,'creator-test',TIMESTAMPTZ '2026-11-10 00:00:00+00')",
                rework(id, number), task(id), issue(id), number, number == 1 ? null : rework(id, number - 1), number == 1 ? null : number - 1);
    }

    private void processing(String id, int round, long revision) {
        jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,?,'成果-A','相同版本文本','  人工处理说明  ','[\"report:原始材料\"]'::jsonb,'handler-test',TIMESTAMPTZ '2026-11-10 00:01:00+00')", rework(id, round), revision);
    }

    private void inspection(String id, int round, long revision, long sequence, String result) {
        String items = "[{\"checkItem\":\"坐标系\",\"result\":\"" + result + "\",\"comment\":\"保留人工检查\",\"evidenceReferences\":[\"report:原始检查\"]}]";
        jdbc.update("INSERT INTO rework_inspections VALUES (?,?,?,?,?,?::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-10 00:02:00+00')", check(id, round, sequence), rework(id, round), revision, sequence, result, items);
    }

    private void review(String id, int round, long revision, long inspection, long sequence, String status) {
        jdbc.update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,?,'  实际复核说明🚀  ','reviewer-test',TIMESTAMPTZ '2026-11-10 00:03:00+00')",
                reviewId(id, round, sequence), rework(id, round), revision, check(id, round, inspection), sequence, status);
    }

    private void legacy(String id, String suffix, String status, String comment) {
        jdbc.update("INSERT INTO review_records VALUES (?,?,?,?)", "REVIEW-OLD-T816-" + id + "-" + suffix, issue(id), status, comment);
    }

    private ResponseEntity<JsonNode> get(String path, String actor, String role) {
        var headers = new HttpHeaders(); headers.set("X-Trace-Id", "trace-t816");
        if (actor != null) headers.set("X-User-Id", actor);
        if (role != null) headers.set("X-User-Role", role);
        return http.exchange(path, HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
    }

    private JsonNode success(String path) {
        var response = get(path, "reviewer-test", "REVIEWER");
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t816");
        var envelope = response.getBody(); assertThat(envelope).isNotNull(); assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue();
        assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse();
        return envelope.path("data");
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        assertThat(response.getBody().path("code").asText()).isEqualTo(code);
        assertThat(response.getBody().path("data").isNull()).isTrue();
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
        assertThat(response.getBody().toString()).doesNotContain("原始材料", "实际复核说明", "request_hash");
    }

    private List<String> facts() {
        return Stream.of("production_orders", "production_tasks", "quality_issues", "rework_tasks", "review_records", "delivery_records",
                "rework_lifecycles", "rework_processing_revisions", "rework_inspections", "rework_reviews", "operation_logs", "idempotency_records", "rework_operation_receipts")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(r)::text FROM " + table + " r ORDER BY to_jsonb(r)::text", String.class).stream()).toList();
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

    @ParameterizedTest
    @ValueSource(strings = {"EMPTY", "MATERIAL", "NOREVIEW", "APPROVED", "REJECTED", "REWORK_REQUIRED", "LATESTREJECTED", "LATESTAPPROVED", "NEWREVISION", "FAILED", "NEWCHECK", "OLDLATER", "NEWROUND", "ROUNDREVIEW"})
    void selectsOnlyCurrentRoundRevisionInspectionAndLatestBoundReview(String scenario) {
        String id = "MATRIX-" + scenario.replace('_', '-'); fixture(id, true); legacy(id, "A", "APPROVED", "旧表通过不能混入");
        Long revision = null; String inspection = null; String status = null; long reviewSequence = 0; int currentRound = 1;
        if (!scenario.equals("EMPTY")) { processing(id, 1, 1); revision = 1L; }
        if (!List.of("EMPTY", "MATERIAL").contains(scenario)) { inspection(id, 1, 1, 1, "PASSED"); inspection = check(id, 1, 1); }
        if (!List.of("EMPTY", "MATERIAL", "NOREVIEW").contains(scenario)) {
            status = List.of("REJECTED", "REWORK_REQUIRED").contains(scenario) ? scenario : "APPROVED";
            review(id, 1, 1, 1, 1, status); reviewSequence = 1;
        }
        if (scenario.equals("LATESTREJECTED") || scenario.equals("LATESTAPPROVED")) {
            status = scenario.equals("LATESTREJECTED") ? "REJECTED" : "APPROVED";
            if (scenario.equals("LATESTAPPROVED")) {
                // 同绑定旧失败与新通过并存，不让旧失败永久阻塞。
                review(id, 1, 1, 1, 2, "REJECTED"); reviewSequence = 3;
            } else reviewSequence = 2;
            review(id, 1, 1, 1, reviewSequence, status);
        }
        if (scenario.equals("NEWREVISION")) { processing(id, 1, 2); revision = 2L; inspection = null; status = null; }
        if (scenario.equals("FAILED") || scenario.equals("NEWCHECK") || scenario.equals("OLDLATER")) {
            inspection(id, 1, 1, 2, scenario.equals("FAILED") ? "FAILED" : "PASSED"); inspection = check(id, 1, 2); status = null;
            if (scenario.equals("OLDLATER")) {
                review(id, 1, 1, 2, 2, "REJECTED"); review(id, 1, 1, 1, 3, "APPROVED"); status = "REJECTED"; reviewSequence = 2;
            }
        }
        if (scenario.equals("NEWROUND") || scenario.equals("ROUNDREVIEW")) {
            round(id, 2); currentRound = 2; revision = null; inspection = null; status = null;
            if (scenario.equals("ROUNDREVIEW")) {
                processing(id, 2, 1); inspection(id, 2, 1, 1, "PASSED"); review(id, 2, 1, 1, 1, "REWORK_REQUIRED");
                revision = 1L; inspection = check(id, 2, 1); status = "REWORK_REQUIRED"; reviewSequence = 1;
            }
        }
        var before = facts(); var data = success(effective(id)); assertThat(data.size()).isEqualTo(3);
        assertThat(data.path("taskId").asText()).isEqualTo(task(id)); assertThat(data.path("taskVersion").asLong()).isEqualTo(7);
        assertThat(data.path("issues").size()).isEqualTo(1); var item = data.path("issues").get(0); assertThat(item.size()).isEqualTo(7);
        assertThat(item.path("issueId").asText()).isEqualTo(issue(id));
        assertThat(item.path("reworkTaskId").asText()).isEqualTo(rework(id, currentRound));
        assertThat(item.path("roundNumber").asLong()).isEqualTo(currentRound);
        assertThat(item.path("legacyReviews").isEmpty()).isTrue();
        if (revision == null) assertThat(item.path("processingRevision").isNull()).isTrue();
        else assertThat(item.path("processingRevision").asLong()).isEqualTo(revision);
        if (inspection == null) assertThat(item.path("inspectionId").isNull()).isTrue();
        else assertThat(item.path("inspectionId").asText()).isEqualTo(inspection);
        if (status == null) assertThat(item.path("review").isNull()).isTrue();
        else {
            var review = item.path("review"); assertThat(review.size()).isEqualTo(9);
            assertThat(review.path("status").asText()).isEqualTo(status);
            assertThat(review.path("reviewSequence").asLong()).isEqualTo(reviewSequence);
            assertThat(review.path("reviewId").asText()).isEqualTo(reviewId(id, currentRound, reviewSequence));
            assertThat(review.path("roundNumber").asLong()).isEqualTo(currentRound);
            assertThat(review.path("processingRevision").asLong()).isEqualTo(revision);
            assertThat(review.path("inspectionId").asText()).isEqualTo(inspection);
            assertThat(review.path("reviewComment").asText()).isEqualTo("  实际复核说明🚀  ");
            assertThat(review.path("reviewedBy").asText()).isEqualTo("reviewer-test");
            assertThat(review.path("reviewedAt").asText()).isEqualTo("2026-11-10T00:03:00Z");
        }
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void preservesLegacyRecordsWithoutInventingBindingsAndLeavesOldApiUnchanged() {
        String id = "LEGACY"; fixture(id, false);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'FAILED','未纳管历史')", rework(id, 1), task(id), issue(id));
        legacy(id, "Z", "APPROVED", "原旧复核"); legacy(id, "A", "PENDING", null);
        var old = success("/api/tasks/" + task(id) + "/review"); var before = facts();
        var item = success(effective(id)).path("issues").get(0);
        for (String field : List.of("reworkTaskId", "roundNumber", "processingRevision", "inspectionId", "review")) assertThat(item.path(field).isNull()).as(field).isTrue();
        assertThat(item.path("legacyReviews")).isEqualTo(old.path("reviews"));
        assertThat(item.path("legacyReviews").get(0).path("reviewComment").isNull()).isTrue();
        var empty = success(history(id, 1)); assertThat(empty.path("records").isEmpty()).isTrue(); assertThat(empty.path("nextCursor").isNull()).isTrue();
        assertThat(success("/api/tasks/" + task(id) + "/review")).isEqualTo(old);
        var golden = success("/api/tasks/TASK-003/effective-reviews").path("issues");
        assertThat(golden.get(0).path("legacyReviews").get(0).path("status").asText()).isEqualTo("PENDING");
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void groupsAllIssuesSeparatelyAndReturnsEmptyArrayForTaskWithoutIssues() {
        String id = "MULTIPLE"; fixture(id, true); processing(id, 1, 1); inspection(id, 1, 1, 1, "PASSED"); review(id, 1, 1, 1, 1, "APPROVED");
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','其他问题')", issue("MULTIPLE-OTHER"), task(id));
        jdbc.update("INSERT INTO review_records VALUES (?,?, 'REJECTED','其他问题旧失败')", "REVIEW-OLD-T816-OTHER", issue("MULTIPLE-OTHER"));
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','无复核的问题')", issue("MULTIPLE-PLAIN"), task(id));
        String second = "MULTIPLE-SECOND";
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM','OPEN','另一受控问题')", issue(second), task(id));
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'COMPLETED','另一问题返工')", rework(second, 1), task(id), issue(second));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,?,?,1,'creator-test',CURRENT_TIMESTAMP)", rework(second, 1), task(id), issue(second));
        processing(second, 1, 1); inspection(second, 1, 1, 1, "PASSED"); review(second, 1, 1, 1, 1, "REJECTED");
        round(id, 2); processing(id, 2, 1); inspection(id, 2, 1, 1, "PASSED"); review(id, 2, 1, 1, 1, "APPROVED");
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T816','RUNNING')", task("NOISSUES"));
        var data = success(effective(id)).path("issues"); assertThat(data.size()).isEqualTo(4);
        assertThat(data.get(0).path("review").path("status").asText()).isEqualTo("APPROVED");
        assertThat(data.get(0).path("roundNumber").asLong()).isEqualTo(2);
        assertThat(data.get(1).path("review").isNull()).isTrue(); assertThat(data.get(1).path("legacyReviews").get(0).path("status").asText()).isEqualTo("REJECTED");
        assertThat(data.get(2).path("review").isNull()).isTrue(); assertThat(data.get(2).path("legacyReviews").isEmpty()).isTrue();
        assertThat(data.get(3).path("review").path("status").asText()).isEqualTo("REJECTED");
        assertThat(data.get(3).path("roundNumber").asLong()).isEqualTo(1);
        assertThat(success(effective("NOISSUES")).path("issues").isEmpty()).isTrue();
    }

    @Test
    void preservesMaximumSafeTaskVersionAndReviewSequenceWithoutOverflow() {
        String id = "MAXIMUM"; fixture(id, true); processing(id, 1, 1); inspection(id, 1, 1, 1, "PASSED");
        review(id, 1, 1, 1, 1, "REJECTED"); review(id, 1, 1, 1, 9007199254740991L, "APPROVED");
        jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?", task(id));
        var before = facts(); var current = success(effective(id));
        assertThat(current.path("taskVersion").asLong()).isEqualTo(9007199254740991L);
        assertThat(current.path("issues").get(0).path("review").path("reviewSequence").asLong()).isEqualTo(9007199254740991L);
        String token = success(history(id, 1) + "?limit=1").path("nextCursor").asText();
        var last = success(history(id, 1) + "?cursor=" + token);
        assertThat(last.path("records").get(0).path("reviewSequence").asLong()).isEqualTo(9007199254740991L);
        assertThat(last.path("nextCursor").isNull()).isTrue(); assertThat(facts()).isEqualTo(before);
    }

    @Test
    void historyPaginatesAllBindingsByReviewSequenceAndDoesNotCollapseFailures() {
        var before = facts(); var page = success(history("HISTORY", 1)); assertThat(page.size()).isEqualTo(4);
        assertThat(page.path("records").size()).isEqualTo(20); var record = page.path("records").get(0); assertThat(record.size()).isEqualTo(9);
        assertThat(record.path("reviewId").asText()).isEqualTo(reviewId("HISTORY", 1, 1));
        assertThat(record.path("inspectionId").asText()).isEqualTo(check("HISTORY", 1, 1));
        List<Long> sequences = new ArrayList<>();
        while (true) {
            for (JsonNode row : page.path("records")) sequences.add(row.path("reviewSequence").asLong());
            if (page.path("nextCursor").isNull()) break;
            page = success(history("HISTORY", 1) + "?limit=100&cursor=" + page.path("nextCursor").asText());
        }
        assertThat(sequences).containsExactlyElementsOf(java.util.stream.LongStream.rangeClosed(1, 35).boxed().toList());
        var current = success(effective("HISTORY")).path("issues").get(0).path("review");
        assertThat(current.path("reviewSequence").asLong()).isEqualTo(34); // 35属于旧修订，不是当前有效复核。
        assertThat(facts()).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"limit=", "limit=0", "limit=-1", "limit=101", "limit=1.0", "limit=true", "limit=1&limit=2", "cursor=", "cursor=null", "cursor=abc.def", "cursor=x&cursor=y", "status=APPROVED", "offset=0"})
    void rejectsInvalidHistoryQueryWithoutChangingFacts(String query) {
        var before = facts(); error(get(history("HISTORY", 1) + "?" + query, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR"); assertThat(facts()).isEqualTo(before);
    }

    @Test
    void rechecksHistoryIdentityOwnershipAndCursorScope() {
        var before = facts(); String path = history("HISTORY", 1);
        error(get(path, null, "REVIEWER"), 401, "PERMISSION_DENIED"); error(get(path, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        error(get(history("MISSING", 1), "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        error(get("/api/tasks/TASK-003/reworks/" + rework("HISTORY", 1) + "/reviews", "reviewer-test", "REVIEWER"), 409, "BUSINESS_CONFLICT");
        String token = success(path + "?limit=1").path("nextCursor").asText();
        error(get(path + "?cursor=" + token, "other-user", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(get(path + "?cursor=" + token, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED");
        String results = path.replace("/reviews", "/results");
        error(get(results + "?cursor=" + token, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        String otherToken = success(results + "?limit=1").path("nextCursor").asText();
        error(get(path + "?cursor=" + otherToken, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(get(path + "?cursor=" + token + "x", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void rejectsEffectiveReviewIdentityIdsAndUnknownFiltersWithoutLeakingRecords() {
        var before = facts(); String path = effective("HISTORY");
        error(get(path, null, "REVIEWER"), 401, "PERMISSION_DENIED");
        error(get(path, "reviewer-test", "VIEWER"), 403, "PERMISSION_DENIED"); error(get(path, "reviewer-test", null), 403, "PERMISSION_DENIED");
        error(get(path, "x".repeat(129), "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        error(get(effective("MISSING"), "reviewer-test", "REVIEWER"), 404, "RESOURCE_NOT_FOUND");
        error(get("/api/tasks/task-lower/effective-reviews", "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        for (String query : List.of("limit=1", "cursor=x", "issueId=x", "status=APPROVED", "role=REVIEWER")) error(get(path + "?" + query, "reviewer-test", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void historyUpperExcludesNewAppendsAndPreviouslyCompletedEvidenceRemainsImmutable() {
        String id = "APPEND"; fixture(id, true); processing(id, 1, 1); inspection(id, 1, 1, 1, "PASSED");
        review(id, 1, 1, 1, 1, "REJECTED"); review(id, 1, 1, 1, 2, "APPROVED");
        String token = success(history(id, 1) + "?limit=1").path("nextCursor").asText(); review(id, 1, 1, 1, 3, "REWORK_REQUIRED");
        var last = success(history(id, 1) + "?limit=100&cursor=" + token); assertThat(last.path("records").size()).isEqualTo(1); assertThat(last.path("nextCursor").isNull()).isTrue();
        assertThat(success(history(id, 1)).path("records").size()).isEqualTo(3);
        var before = facts();
        assertThatThrownBy(() -> jdbc.update("UPDATE rework_reviews SET status='APPROVED' WHERE rework_task_id=?", rework(id, 1))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update("DELETE FROM rework_reviews WHERE rework_task_id=?", rework(id, 1))).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(facts()).isEqualTo(before);
    }

    @Test
    void versionAndReviewStayInOneIndependentReadOnlySnapshot() {
        String id = "SNAPSHOT"; fixture(id, true); processing(id, 1, 1); inspection(id, 1, 1, 1, "PASSED"); review(id, 1, 1, 1, 1, "REJECTED");
        var observing = new EffectiveReviewRepository(jdbc, mapper) {
            @Override public Optional<Long> taskVersion(String taskId) {
                assertThat(jdbc.queryForObject("SHOW transaction_isolation", String.class)).isEqualTo("repeatable read");
                assertThat(jdbc.queryForObject("SHOW transaction_read_only", String.class)).isEqualTo("on");
                var version = super.taskVersion(taskId);
                try (Connection connection = dataSource.getConnection()) {
                    assertThat(connection.getAutoCommit()).isTrue(); connection.setAutoCommit(false);
                    try (var update = connection.prepareStatement("UPDATE production_tasks SET version=8 WHERE task_id=?");
                         var insert = connection.prepareStatement("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,1,?,2,'APPROVED','独立事务复核','other-test',CURRENT_TIMESTAMP)")) {
                        update.setString(1, taskId); update.executeUpdate(); insert.setString(1, reviewId(id, 1, 2)); insert.setString(2, rework(id, 1)); insert.setString(3, check(id, 1, 1)); insert.executeUpdate(); connection.commit();
                    }
                } catch (java.sql.SQLException exception) { throw new IllegalStateException(exception); }
                return version;
            }
        };
        var service = new EffectiveReviewService(observing, manager);
        var previous = new TransactionTemplate(manager).execute(status -> service.read(task(id), "reviewer-test", "REVIEWER", new LinkedMultiValueMap<>()));
        assertThat(previous.taskVersion()).isEqualTo(7); assertThat(previous.issues().get(0).review().status().name()).isEqualTo("REJECTED");
        var fresh = success(effective(id)); assertThat(fresh.path("taskVersion").asLong()).isEqualTo(8);
        assertThat(fresh.path("issues").get(0).path("review").path("status").asText()).isEqualTo("APPROVED");
    }
}
