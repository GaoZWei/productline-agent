package com.productline.business.domain.repository;

import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 只读不可覆盖的原回执表，不读取后来业务状态或未提交的幂等预留。 */
@Repository
public class ReworkOperationQueryRepository {
    private final JdbcTemplate jdbc;

    public ReworkOperationQueryRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Optional<StoredReceipt> find(String taskId, String actor, String key) {
        return jdbc.query("""
                SELECT operation_type,operation_id,task_id,rework_task_id,round_number,
                       task_version_after,response_data::text
                FROM rework_operation_receipts
                WHERE task_id=? AND actor_user_id=? AND idempotency_key=?
                """, (rs, row) -> new StoredReceipt(rs.getString("operation_type"), rs.getString("operation_id"),
                rs.getString("task_id"), rs.getString("rework_task_id"), rs.getLong("round_number"),
                rs.getLong("task_version_after"), rs.getString("response_data")), taskId, actor, key)
                .stream().findFirst();
    }

    public record StoredReceipt(String operation, String operationId, String taskId, String reworkTaskId,
            long roundNumber, long taskVersion, String json) {}
}
