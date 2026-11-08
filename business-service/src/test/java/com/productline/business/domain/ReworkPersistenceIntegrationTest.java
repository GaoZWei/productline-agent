package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Savepoint;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import java.util.stream.Collectors;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class ReworkPersistenceIntegrationTest extends PostgresIntegrationTestSupport {
    private static final String SCHEMA = "rework_storage_v5";
    private static final String REWORK = "REWORK-STORAGE-A";
    private static final List<String> NEW_TABLES = List.of("rework_lifecycles", "rework_processing_revisions",
            "rework_inspections", "rework_reviews", "rework_operation_receipts");
    private static final String PASSED_ITEMS = "[{\"checkItem\":\"坐标系\",\"result\":\"PASSED\",\"comment\":\"人工检查说明\",\"evidenceReferences\":[\"check:report\"]}]";
    private Connection connection;

    @BeforeAll
    static void migrateLatest() {
        flyway(SCHEMA, null).migrate();
    }

    @BeforeEach
    void openIsolatedTransaction() throws Exception {
        connection = open(SCHEMA);
        connection.setAutoCommit(false);
        base(connection, "A");
        lifecycle(connection, REWORK, "TASK-STORAGE-A", "ISSUE-STORAGE-A", 1, null, null);
    }

    @AfterEach
    void rollbackFixture() throws Exception {
        if (connection != null) {
            connection.rollback();
            connection.close();
        }
    }

    @Test
    void upgradesDirtyV4WithoutChangingLegacyFactsOrBackfillingEvidence() throws Exception {
        String schema = "rework_dirty_v4_upgrade";
        flyway(schema, "4").migrate();
        try (Connection old = open(schema); Statement statement = old.createStatement()) {
            statement.executeUpdate("UPDATE production_tasks SET version=2 WHERE task_id='TASK-003'");
            statement.executeUpdate("INSERT INTO review_records VALUES ('REVIEW-PRESERVE-V5','ISSUE-001','REWORK_REQUIRED','保留人工复核')");
            statement.executeUpdate("INSERT INTO rework_tasks VALUES ('REWORK-PRESERVE-V5','TASK-003','ISSUE-001','PENDING','保留人工返工')");
            statement.executeUpdate("INSERT INTO rework_tasks VALUES ('REWORK-NOSOURCE-V5','TASK-003',NULL,'FAILED','无来源历史记录')");
            statement.executeUpdate("INSERT INTO idempotency_records(idempotency_key,operation_type,request_hash,actor_user_id,resource_id,task_version_after) VALUES ('legacy-key','CREATE_REWORK','legacy-hash','legacy-user','REWORK-PRESERVE-V5',2)");
            statement.executeUpdate("INSERT INTO operation_logs(operation_id,operation_type,target_type,target_id,actor_user_id,idempotency_key_hash,before_state,after_state) VALUES ('OPERATION-PRESERVE-V5','CREATE_REWORK','TASK','TASK-003','legacy-user','legacy-hash','before','after')");
            Map<String, List<String>> before = legacySnapshot(old);

            assertThat(flyway(schema, null).migrate().migrationsExecuted).isEqualTo(1);

            assertThat(legacySnapshot(old)).isEqualTo(before);
            for (String table : NEW_TABLES) {
                assertThat(count(old, table)).as(table).isZero();
            }
            assertThat(flyway(schema, null).migrate().migrationsExecuted).isZero();
            flyway(schema, null).validate();
        }
    }

    @Test
    void persistsRevisionsChecksAndReviewBindingsWithoutChangingGoldenSeedData() throws Exception {
        revision(REWORK, 1, "product-A", "release-2", "重新生成成果", "[\"report:processing\"]");
        inspection("CHECK-STORAGE-A", REWORK, 1, 1, "PASSED", PASSED_ITEMS);
        review("REVIEW-STORAGE-A", REWORK, 1, "CHECK-STORAGE-A", 1, "APPROVED");
        String failed = PASSED_ITEMS.replace("PASSED", "FAILED");
        inspection("CHECK-STORAGE-B", REWORK, 1, 2, "FAILED", failed);
        revision(REWORK, 2, "product-A", "release-3", "再次处理", "[\"report:next\"]");

        assertThat(scalar("SELECT artifact_version FROM rework_processing_revisions WHERE rework_task_id='" + REWORK + "' AND processing_revision=1"))
                .isEqualTo("release-2");
        assertThat(scalar("SELECT result FROM rework_inspections WHERE rework_task_id='" + REWORK + "' ORDER BY inspection_sequence DESC LIMIT 1"))
                .isEqualTo("FAILED");
        assertThat(scalar("SELECT inspection_id FROM rework_reviews WHERE review_id='REVIEW-STORAGE-A'"))
                .isEqualTo("CHECK-STORAGE-A");
        assertThat(scalar("SELECT status FROM production_tasks WHERE task_id='TASK-003'")).isEqualTo("COMPLETED");
        assertThat(scalar("SELECT status FROM quality_issues WHERE issue_id='ISSUE-001'")).isEqualTo("OPEN");
        assertThat(scalar("SELECT status FROM review_records WHERE review_id='REVIEW-003'")).isEqualTo("PENDING");
        assertThat(scalar("SELECT status FROM delivery_records WHERE order_id='ORDER-003'")).isEqualTo("BLOCKED");
    }

    @Test
    void rejectsCrossTaskAndCrossIssueLifecycles() throws Exception {
        base(connection, "B");
        rejected("23503", () -> lifecycle(connection, "REWORK-STORAGE-B", "TASK-STORAGE-A", "ISSUE-STORAGE-B", 1, null, null));
        rejected("23503", () -> lifecycle(connection, "REWORK-STORAGE-B", "TASK-STORAGE-B", "ISSUE-STORAGE-A", 1, null, null));
    }

    @Test
    void requiresAContiguousSameIssuePredecessorAndRejectsForks() throws Exception {
        child("REWORK-ROUND-B", "TASK-STORAGE-A", "ISSUE-STORAGE-A");
        child("REWORK-ROUND-C", "TASK-STORAGE-A", "ISSUE-STORAGE-A");
        rejected("23514", () -> lifecycle(connection, "REWORK-ROUND-B", "TASK-STORAGE-A", "ISSUE-STORAGE-A", 3, REWORK, 1L));
        rejected("23514", () -> lifecycle(connection, "REWORK-ROUND-B", "TASK-STORAGE-A", "ISSUE-STORAGE-A", 1, REWORK, 1L));
        base(connection, "B");
        rejected("23503", () -> lifecycle(connection, "REWORK-STORAGE-B", "TASK-STORAGE-B", "ISSUE-STORAGE-B", 2, REWORK, 1L));
        lifecycle(connection, "REWORK-ROUND-B", "TASK-STORAGE-A", "ISSUE-STORAGE-A", 2, REWORK, 1L);
        rejected("23505", () -> lifecycle(connection, "REWORK-ROUND-C", "TASK-STORAGE-A", "ISSUE-STORAGE-A", 2, REWORK, 1L));
    }

    @ParameterizedTest
    @MethodSource("invalidRevisions")
    void enforcesRevisionMaterialsAndUtf16Limits(long number, String artifact, String version, String comment, String references) throws Exception {
        rejected("23514", () -> revision(REWORK, number, artifact, version, comment, references));
    }

    @Test
    void acceptsExactNonBmpUtf16BoundaryAndRejectsUnknownRevisionOwnership() throws Exception {
        revision(REWORK, 1, "product-A", "😀".repeat(64), "中文说明", "[\"report:unicode\"]");
        rejected("23503", () -> revision("REWORK-UNKNOWN", 1, "product-A", "v1", "处理说明", "[\"report:a\"]"));
        rejected("23505", () -> revision(REWORK, 1, "product-A", "v2", "重复修订", "[\"report:b\"]"));
    }

    @Test
    void usesJavaWhitespaceAndUtf16RulesWithoutStrippingTheLetterV() throws Exception {
        for (String value : List.of("", "\t", "\u000B", "\u001C", "\u1680", "\u2003", "\u3000", "v1", "😀")) {
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT rework_valid_text(?,128,FALSE), rework_utf16_length(?)")) {
                statement.setString(1, value);
                statement.setString(2, value);
                try (ResultSet result = statement.executeQuery()) {
                    assertThat(result.next()).isTrue();
                    assertThat(result.getBoolean(1)).as("blank parity").isEqualTo(!value.isBlank());
                    assertThat(result.getInt(2)).as("UTF-16 parity").isEqualTo(value.length());
                }
            }
        }
    }

    @ParameterizedTest
    @MethodSource("invalidChecks")
    void enforcesInspectionShapeAndHumanResultSummary(String result, String items) throws Exception {
        revision(REWORK, 1, "product-A", "v1", "处理说明", "[\"report:a\"]");
        rejected("23514", () -> inspection("CHECK-STORAGE-A", REWORK, 1, 1, result, items));
    }

    @Test
    void rejectsMissingRevisionsDuplicateCheckSequencesAndInvalidReviewBindings() throws Exception {
        revision(REWORK, 1, "product-A", "v1", "处理说明", "[\"report:a\"]");
        revision(REWORK, 2, "product-A", "v2", "新处理说明", "[\"report:b\"]");
        rejected("23503", () -> inspection("CHECK-MISSING", REWORK, 3, 1, "PASSED", PASSED_ITEMS));
        inspection("CHECK-PASSED", REWORK, 1, 1, "PASSED", PASSED_ITEMS);
        inspection("CHECK-FAILED", REWORK, 2, 2, "FAILED", PASSED_ITEMS.replace("PASSED", "FAILED"));
        rejected("23505", () -> inspection("CHECK-DUPLICATE", REWORK, 1, 1, "PASSED", PASSED_ITEMS));
        rejected("23503", () -> review("REVIEW-WRONG-REV", REWORK, 2, "CHECK-PASSED", 1, "APPROVED"));
        rejected("23503", () -> review("REVIEW-FAILED", REWORK, 2, "CHECK-FAILED", 1, "APPROVED"));
        rejected("23514", () -> review("REVIEW-PENDING", REWORK, 1, "CHECK-PASSED", 1, "PENDING"));
        review("REVIEW-VALID", REWORK, 1, "CHECK-PASSED", 1, "REWORK_REQUIRED");
        rejected("23505", () -> review("REVIEW-DUPLICATE", REWORK, 1, "CHECK-PASSED", 1, "APPROVED"));
    }

    @Test
    void preservesOriginalReceiptAfterBusinessStateChangesAndRejectsBindingMismatch() throws Exception {
        receipt("storage-key", "storage-reviewer", receiptJson("storage-key", 1));
        sql("UPDATE rework_tasks SET status='RUNNING' WHERE rework_task_id='" + REWORK + "'");
        sql("UPDATE production_tasks SET version=2 WHERE task_id='TASK-STORAGE-A'");

        assertThat(scalar("SELECT response_data->>'status' FROM rework_operation_receipts WHERE idempotency_key='storage-key'"))
                .isEqualTo("PENDING");
        assertThat(scalar("SELECT response_data->>'taskVersion' FROM rework_operation_receipts WHERE idempotency_key='storage-key'"))
                .isEqualTo("1");
        rejected("23514", () -> sql("UPDATE rework_operation_receipts SET response_data='{}' WHERE idempotency_key='storage-key'"));
        rejected("23503", () -> receipt("mismatched-actor", "other-user", receiptJson("mismatched-actor", 1)));
        rejected("23514", () -> receipt("mismatched-receipt", "storage-reviewer", receiptJson("mismatched-receipt", 2)));
    }

    @Test
    void keepsHistoryAppendOnlyAndAllowsOneTimeStartMetadata() throws Exception {
        revision(REWORK, 1, "product-A", "v1", "处理说明", "[\"report:a\"]");
        inspection("CHECK-STORAGE-A", REWORK, 1, 1, "PASSED", PASSED_ITEMS);
        review("REVIEW-STORAGE-A", REWORK, 1, "CHECK-STORAGE-A", 1, "APPROVED");
        sql("UPDATE rework_lifecycles SET started_by='storage-reviewer', started_at=CURRENT_TIMESTAMP WHERE rework_task_id='" + REWORK + "'");
        rejected("23514", () -> sql("UPDATE rework_lifecycles SET started_by='other-user' WHERE rework_task_id='" + REWORK + "'"));
        rejected("23514", () -> sql("UPDATE rework_lifecycles SET created_by='other-user' WHERE rework_task_id='" + REWORK + "'"));
        for (String table : List.of("rework_processing_revisions", "rework_inspections", "rework_reviews")) {
            rejected("23514", () -> sql("DELETE FROM " + table + " WHERE rework_task_id='" + REWORK + "'"));
            rejected("23514", () -> sql("UPDATE " + table + " SET rework_task_id=rework_task_id WHERE rework_task_id='" + REWORK + "'"));
        }
    }

    @Test
    void rollsBackMaterialsAndAuditReceiptAsOneTransaction() throws Exception {
        Savepoint start = connection.setSavepoint();
        revision(REWORK, 1, "product-A", "v1", "处理说明", "[\"report:a\"]");
        inspection("CHECK-STORAGE-A", REWORK, 1, 1, "PASSED", PASSED_ITEMS);
        review("REVIEW-STORAGE-A", REWORK, 1, "CHECK-STORAGE-A", 1, "APPROVED");
        receipt("rollback-key", "storage-reviewer", receiptJson("rollback-key", 1));

        connection.rollback(start);

        for (String table : NEW_TABLES.subList(1, NEW_TABLES.size())) {
            assertThat(count(connection, table)).as(table).isZero();
        }
        assertThat(scalar("SELECT count(*) FROM idempotency_records WHERE idempotency_key='rollback-key'")).isEqualTo("0");
        assertThat(scalar("SELECT count(*) FROM operation_logs WHERE operation_id='" + operationId("rollback-key") + "'")).isEqualTo("0");
    }

    @Test
    void independentTransactionsCannotForkTheSameRound() throws Exception {
        try (Connection setup = open(SCHEMA)) {
            base(setup, "CONCURRENT");
            lifecycle(setup, "REWORK-STORAGE-CONCURRENT", "TASK-STORAGE-CONCURRENT", "ISSUE-STORAGE-CONCURRENT", 1, null, null);
            try (Statement s = setup.createStatement()) {
                s.executeUpdate("INSERT INTO rework_tasks VALUES ('REWORK-CONCURRENT-A','TASK-STORAGE-CONCURRENT','ISSUE-STORAGE-CONCURRENT','PENDING','测试下一轮')");
                s.executeUpdate("INSERT INTO rework_tasks VALUES ('REWORK-CONCURRENT-B','TASK-STORAGE-CONCURRENT','ISSUE-STORAGE-CONCURRENT','PENDING','测试下一轮')");
            }
        }
        try (Connection first = open(SCHEMA); Connection second = open(SCHEMA);
                var executor = Executors.newSingleThreadExecutor()) {
            first.setAutoCommit(false);
            second.setAutoCommit(false);
            second.createStatement().execute("SET statement_timeout='5s'");
            lifecycle(first, "REWORK-CONCURRENT-A", "TASK-STORAGE-CONCURRENT", "ISSUE-STORAGE-CONCURRENT", 2, "REWORK-STORAGE-CONCURRENT", 1L);
            CountDownLatch submitted = new CountDownLatch(1);
            var loser = executor.submit(() -> {
                submitted.countDown();
                SQLException error = catchThrowableOfType(() -> lifecycle(second, "REWORK-CONCURRENT-B",
                        "TASK-STORAGE-CONCURRENT", "ISSUE-STORAGE-CONCURRENT", 2, "REWORK-STORAGE-CONCURRENT", 1L), SQLException.class);
                second.rollback();
                return error;
            });
            assertThat(submitted.await(5, TimeUnit.SECONDS)).isTrue();
            first.commit();
            SQLException error = loser.get(8, TimeUnit.SECONDS);
            assertThat((Throwable) error).isNotNull();
            assertThat(error.getSQLState()).isEqualTo("23505");
        }
    }

    private void rejected(String state, ThrowingCallable operation) throws Exception {
        Savepoint before = connection.setSavepoint();
        SQLException error = catchThrowableOfType(operation, SQLException.class);
        assertThat((Throwable) error).isNotNull();
        assertThat(error.getSQLState()).isEqualTo(state);
        connection.rollback(before);
    }

    private void revision(String id, long revision, String artifact, String version, String comment, String refs) throws Exception {
        update("INSERT INTO rework_processing_revisions(rework_task_id,processing_revision,artifact_id,artifact_version,processing_comment,evidence_references,registered_by,registered_at) VALUES (?,?,?,?,?,?::jsonb,'storage-reviewer',CURRENT_TIMESTAMP)", id, revision, artifact, version, comment, refs);
    }

    private void inspection(String id, String rework, long revision, long sequence, String result, String items) throws Exception {
        update("INSERT INTO rework_inspections(inspection_id,rework_task_id,processing_revision,inspection_sequence,result,items,inspector_id,inspected_at) VALUES (?,?,?,?,?,?::jsonb,'storage-reviewer',CURRENT_TIMESTAMP)", id, rework, revision, sequence, result, items);
    }

    private void review(String id, String rework, long revision, String inspection, long sequence, String status) throws Exception {
        update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,?,'人工复核说明','storage-reviewer',CURRENT_TIMESTAMP)", id, rework, revision, inspection, sequence, status);
    }

    private void receipt(String key, String actor, String json) throws Exception {
        String operation = "CREATE_LIFECYCLE_REWORK";
        update("INSERT INTO idempotency_records(idempotency_key,operation_type,request_hash,actor_user_id,resource_id,task_version_after) VALUES (?,? ,?,'storage-reviewer',?,1)", key, operation, "a".repeat(64), REWORK);
        update("INSERT INTO operation_logs(operation_id,operation_type,target_type,target_id,actor_user_id,idempotency_key_hash,before_state,after_state) VALUES (?,?,'PRODUCTION_TASK','TASK-STORAGE-A','storage-reviewer',encode(sha256(convert_to(?,'UTF8')),'hex'),'before','after')", operationId(key), operation, key);
        update("INSERT INTO rework_operation_receipts(idempotency_key,operation_id,operation_type,request_hash,actor_user_id,task_id,rework_task_id,round_number,task_version_after,idempotency_key_hash,response_data) VALUES (?,?,?,?,?,'TASK-STORAGE-A',?,1,1,encode(sha256(convert_to(?,'UTF8')),'hex'),?::jsonb)", key, operationId(key), operation, "a".repeat(64), actor, REWORK, key, json);
    }

    private String receiptJson(String key, long version) throws Exception {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("operation", "CREATE_LIFECYCLE_REWORK");
        data.put("operationId", operationId(key));
        data.put("taskId", "TASK-STORAGE-A");
        data.put("reworkTaskId", REWORK);
        data.put("taskVersion", version);
        data.put("status", "PENDING");
        data.put("issueStatus", "OPEN");
        data.put("roundNumber", 1);
        data.put("previousReworkTaskId", null);
        data.put("processingRevision", null);
        data.put("inspectionId", null);
        data.put("reviewId", null);
        return new ObjectMapper().writeValueAsString(data);
    }

    private String operationId(String key) {
        return "OPERATION-STORAGE-" + Integer.toUnsignedString(key.hashCode(), 16).toUpperCase(Locale.ROOT);
    }

    private void update(String statement, Object... values) throws Exception {
        try (PreparedStatement query = connection.prepareStatement(statement)) {
            for (int i = 0; i < values.length; i++) query.setObject(i + 1, values[i]);
            query.executeUpdate();
        }
    }

    private void child(String id, String task, String issue) throws Exception {
        update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','测试返工')", id, task, issue);
    }

    private void sql(String statement) throws Exception {
        try (Statement query = connection.createStatement()) { query.executeUpdate(statement); }
    }

    private String scalar(String statement) throws Exception {
        try (Statement query = connection.createStatement(); ResultSet rows = query.executeQuery(statement)) {
            assertThat(rows.next()).isTrue();
            return rows.getString(1);
        }
    }

    private static Connection open(String schema) throws Exception {
        Connection opened = DriverManager.getConnection(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword());
        opened.setSchema(schema);
        return opened;
    }

    private static Flyway flyway(String schema, String target) {
        var config = Flyway.configure().dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                .schemas(schema).defaultSchema(schema);
        if (target != null) config.target(target);
        return config.load();
    }

    private static void base(Connection connection, String suffix) throws Exception {
        try (Statement s = connection.createStatement()) {
            s.executeUpdate("INSERT INTO production_orders VALUES ('ORDER-STORAGE-" + suffix + "','DOM','BLOCKED')");
            s.executeUpdate("INSERT INTO production_tasks(task_id,order_id,status) VALUES ('TASK-STORAGE-" + suffix + "','ORDER-STORAGE-" + suffix + "','COMPLETED')");
            s.executeUpdate("INSERT INTO quality_issues VALUES ('ISSUE-STORAGE-" + suffix + "','TASK-STORAGE-" + suffix + "','COORDINATE_SYSTEM','OPEN','隔离测试问题')");
            s.executeUpdate("INSERT INTO rework_tasks VALUES ('REWORK-STORAGE-" + suffix + "','TASK-STORAGE-" + suffix + "','ISSUE-STORAGE-" + suffix + "','PENDING','隔离测试返工')");
        }
    }

    private static void lifecycle(Connection connection, String rework, String task, String issue, long round, String previous, Long previousRound) throws Exception {
        try (PreparedStatement s = connection.prepareStatement("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES (?,?,?,?,?,?,'storage-reviewer',CURRENT_TIMESTAMP)")) {
            s.setString(1, rework); s.setString(2, task); s.setString(3, issue); s.setLong(4, round);
            s.setString(5, previous); s.setObject(6, previousRound); s.executeUpdate();
        }
    }

    private static long count(Connection c, String table) throws Exception {
        try (Statement s = c.createStatement(); ResultSet r = s.executeQuery("SELECT count(*) FROM " + table)) {
            r.next(); return r.getLong(1);
        }
    }

    private static Map<String, List<String>> legacySnapshot(Connection c) throws Exception {
        Map<String, List<String>> result = new LinkedHashMap<>();
        for (String table : List.of("production_orders", "production_tasks", "production_steps", "quality_issues", "review_records", "rework_tasks", "delivery_records", "operation_logs", "idempotency_records")) {
            List<String> rows = new ArrayList<>();
            try (Statement s = c.createStatement(); ResultSet r = s.executeQuery("SELECT row_to_json(t)::text FROM " + table + " t ORDER BY row_to_json(t)::text")) {
                while (r.next()) rows.add(r.getString(1));
            }
            result.put(table, rows);
        }
        return result;
    }

    private static Stream<Arguments> invalidRevisions() {
        return Stream.of(
                Arguments.of(0, "product-A", "v1", "说明", "[\"report:a\"]"),
                Arguments.of(9007199254740992L, "product-A", "v1", "说明", "[\"report:a\"]"),
                Arguments.of(1, " ", "v1", "说明", "[\"report:a\"]"),
                Arguments.of(1, "product-A", "😀".repeat(65), "说明", "[\"report:a\"]"),
                Arguments.of(1, "product-A", "v1", "　", "[\"report:a\"]"),
                Arguments.of(1, "product-A", "v1", "说明", "[]"),
                Arguments.of(1, "product-A", "v1", "说明", "{}"),
                Arguments.of(1, "product-A", "v1", "说明", "[null]"),
                Arguments.of(1, "product-A", "v1", "说明", "[\" report:a\"]"),
                Arguments.of(1, "product-A", "v1", "说明", Stream.generate(() -> "\"report:a\"").limit(21).collect(Collectors.joining(",", "[", "]"))),
                Arguments.of(1, "product-A", "v1", "说明", "[\"" + "x".repeat(1025) + "\"]"),
                Arguments.of(1, "product-A", "v1", "x".repeat(1001), "[\"report:a\"]"));
    }

    private static Stream<Arguments> invalidChecks() {
        return Stream.of(Arguments.of("PASSED", "[]"), Arguments.of("PASSED", "{}"),
                Arguments.of("PASSED", "[null]"), Arguments.of("PASSED", PASSED_ITEMS.replace("PASSED", "FAILED")),
                Arguments.of("FAILED", PASSED_ITEMS), Arguments.of("PASSED", PASSED_ITEMS.replace("\"坐标系\"", "3")),
                Arguments.of("PASSED", PASSED_ITEMS.replace("\"check:report\"", "null")),
                Arguments.of("PASSED", PASSED_ITEMS.replace("\"comment\":", "\"unknown\":0,\"comment\":")),
                Arguments.of("PASSED", Stream.generate(() -> PASSED_ITEMS.substring(1, PASSED_ITEMS.length() - 1))
                        .limit(51).collect(Collectors.joining(",", "[", "]"))));
    }
}
