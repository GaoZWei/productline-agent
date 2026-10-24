package com.productline.business.demo;

import static org.assertj.core.api.Assertions.assertThat;

import com.productline.business.support.PostgresIntegrationTestSupport;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;

class DemoMigrationUpgradeIntegrationTest extends PostgresIntegrationTestSupport {
    @Test
    void upgradesDirtyV3WithoutChangingExistingFactsOrWriteHistory() throws Exception {
        String schema = "demo_upgrade_v4";
        Flyway.configure().dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                .schemas(schema).defaultSchema(schema).target("3").load().migrate();
        try (Connection connection = DriverManager.getConnection(
                POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())) {
            connection.setSchema(schema);
            try (Statement statement = connection.createStatement()) {
                statement.executeUpdate("UPDATE production_tasks SET version = 2 WHERE task_id = 'TASK-003'");
                statement.executeUpdate("INSERT INTO review_records VALUES ('REVIEW-WRITE-PRESERVE', 'ISSUE-001', 'REWORK_REQUIRED', '保留人工复核')");
                statement.executeUpdate("INSERT INTO rework_tasks VALUES ('REWORK-WRITE-PRESERVE', 'TASK-003', 'ISSUE-001', 'PENDING', '保留人工返工')");
                statement.executeUpdate("INSERT INTO idempotency_records (idempotency_key,operation_type,request_hash,actor_user_id,resource_id,task_version_after) VALUES ('preserve','CREATE_REWORK','hash','demo','REWORK-WRITE-PRESERVE',2)");
                statement.executeUpdate("INSERT INTO operation_logs (operation_id,operation_type,target_type,target_id,actor_user_id,idempotency_key_hash,before_state,after_state) VALUES ('OP-PRESERVE','CREATE_REWORK','TASK','TASK-003','demo','hash','before','after')");
                Map<String, List<String>> before = snapshot(statement);
                assertThat(Flyway.configure().dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                        .schemas(schema).defaultSchema(schema).load().migrate().migrationsExecuted).isEqualTo(1);
                Map<String, List<String>> after = snapshot(statement);
                before.forEach((table, rows) -> assertThat(after.get(table)).containsAll(rows));
                assertThat(after.get("production_orders")).hasSize(30);
                assertThat(after.get("production_tasks")).hasSize(34);
                assertThat(after.get("review_records")).hasSize(24);
                assertThat(after.get("rework_tasks")).hasSize(4);
                assertThat(after.get("operation_logs")).hasSize(1);
                assertThat(after.get("idempotency_records")).hasSize(1);
                assertThat(Flyway.configure().dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                        .schemas(schema).defaultSchema(schema).load().migrate().migrationsExecuted).isZero();
            }
        }
    }

    private Map<String, List<String>> snapshot(Statement statement) throws Exception {
        Map<String, List<String>> result = new LinkedHashMap<>();
        for (String table : List.of("production_orders", "production_tasks", "production_steps",
                "quality_issues", "review_records", "rework_tasks", "delivery_records",
                "idempotency_records", "operation_logs")) {
            List<String> rows = new ArrayList<>();
            try (var records = statement.executeQuery("SELECT row_to_json(t)::text FROM " + table + " t")) {
                while (records.next()) rows.add(records.getString(1));
            }
            result.put(table, rows);
        }
        return result;
    }
}
