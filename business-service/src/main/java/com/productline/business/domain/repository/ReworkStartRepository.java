package com.productline.business.domain.repository;

import com.productline.business.domain.enums.ProductionTaskStatus;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 开始与异常操作共用的SQL写集，必须由应用服务同一事务调用，不补造存量生命周期。 */
@Repository
public class ReworkStartRepository {
    private final JdbcTemplate jdbc;

    public ReworkStartRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public int reserve(String key, String operation, String requestHash, String actor) {
        return jdbc.update("""
                INSERT INTO idempotency_records(idempotency_key,operation_type,request_hash,actor_user_id)
                VALUES (?,?,?,?) ON CONFLICT (idempotency_key) DO NOTHING
                """, key, operation, requestHash, actor);
    }

    public Reservation reservation(String key) {
        return jdbc.queryForObject("""
                SELECT operation_type,request_hash,actor_user_id,resource_id,task_version_after
                FROM idempotency_records WHERE idempotency_key=?
                """, (rs, row) -> new Reservation(rs.getString("operation_type"), rs.getString("request_hash"),
                rs.getString("actor_user_id"), rs.getString("resource_id"), rs.getObject("task_version_after", Long.class)), key);
    }

    public Optional<String> receipt(String key, String taskId, String reworkId, String actor, String requestHash) {
        return jdbc.query("""
                SELECT response_data::text FROM rework_operation_receipts
                WHERE idempotency_key=? AND task_id=? AND rework_task_id=? AND actor_user_id=? AND request_hash=?
                """, (rs, row) -> rs.getString(1), key, taskId, reworkId, actor, requestHash).stream().findFirst();
    }

    public boolean lockTask(String taskId) {
        return !jdbc.query("SELECT task_id FROM production_tasks WHERE task_id=? FOR UPDATE",
                (rs, row) -> rs.getString(1), taskId).isEmpty();
    }

    public Optional<Lifecycle> lifecycle(String taskId, String reworkId, String issueId) {
        return jdbc.query("""
                SELECT round_number,started_at FROM rework_lifecycles
                WHERE task_id=? AND rework_task_id=? AND source_issue_id=?
                """, (rs, row) -> new Lifecycle(rs.getLong("round_number"), rs.getTimestamp("started_at") != null),
                taskId, reworkId, issueId).stream().findFirst();
    }

    public boolean hasSuccessor(String reworkId) {
        return Boolean.TRUE.equals(jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM rework_lifecycles WHERE previous_rework_task_id=?)",
                Boolean.class, reworkId));
    }

    public int advanceVersion(String taskId, long expected) {
        return jdbc.update("UPDATE production_tasks SET version=version+1 WHERE task_id=? AND version=? AND status='COMPLETED'",
                taskId, expected);
    }

    public int markRunning(String taskId, String reworkId) {
        return jdbc.update("UPDATE rework_tasks SET status='RUNNING' WHERE task_id=? AND rework_task_id=? AND status='PENDING'",
                taskId, reworkId);
    }

    public boolean lockProcessingIssue(String taskId, String issueId) {
        // 保持PROCESSING事实至提交；NO KEY UPDATE仍允许旧复核插入所需的外键KEY SHARE。
        return !jdbc.query("SELECT issue_id FROM quality_issues WHERE task_id=? AND issue_id=? AND status='PROCESSING' FOR NO KEY UPDATE",
                (rs, row) -> rs.getString(1), taskId, issueId).isEmpty();
    }

    public int markInterrupted(String taskId, String reworkId, ProductionTaskStatus status) {
        if (status != ProductionTaskStatus.BLOCKED && status != ProductionTaskStatus.FAILED) {
            throw new IllegalArgumentException("interruption target must be BLOCKED or FAILED");
        }
        // 创建原因、开始信息及历史材料均不覆盖；异常原因另写本次操作审计。
        return jdbc.update("UPDATE rework_tasks SET status=? WHERE task_id=? AND rework_task_id=? AND status='RUNNING'",
                status.name(), taskId, reworkId);
    }

    public int markProcessing(String taskId, String issueId) {
        return jdbc.update("UPDATE quality_issues SET status='PROCESSING' WHERE task_id=? AND issue_id=? AND status='OPEN'",
                taskId, issueId);
    }

    public int markStarted(String reworkId, String actor, Instant startedAt) {
        return jdbc.update("""
                UPDATE rework_lifecycles SET started_by=?,started_at=?
                WHERE rework_task_id=? AND started_by IS NULL AND started_at IS NULL
                """, actor, startedAt.atOffset(ZoneOffset.UTC), reworkId);
    }

    public int completeReservation(String key, String reworkId, long nextVersion) {
        return jdbc.update("""
                UPDATE idempotency_records SET resource_id=?,task_version_after=?
                WHERE idempotency_key=? AND resource_id IS NULL AND task_version_after IS NULL
                """, reworkId, nextVersion, key);
    }

    public void audit(String operationId, String operation, String taskId, String actor,
            String keyHash, String before, String after) {
        jdbc.update("""
                INSERT INTO operation_logs(operation_id,operation_type,target_type,target_id,actor_user_id,
                    idempotency_key_hash,before_state,after_state)
                VALUES (?,?,'PRODUCTION_TASK',?,?,?,?,?)
                """, operationId, operation, taskId, actor, keyHash, before, after);
    }

    public void saveReceipt(String key, String operationId, String operation, String requestHash,
            String actor, String taskId, String reworkId, long round, long nextVersion, String keyHash, String json) {
        jdbc.update("""
                INSERT INTO rework_operation_receipts(idempotency_key,operation_id,operation_type,request_hash,
                    actor_user_id,task_id,rework_task_id,round_number,task_version_after,idempotency_key_hash,response_data)
                VALUES (?,?,?,?,?,?,?,?,?,?,?::jsonb)
                """, key, operationId, operation, requestHash, actor, taskId, reworkId, round, nextVersion, keyHash, json);
    }

    public record Reservation(String operation, String requestHash, String actor, String resourceId, Long version) {}
    public record Lifecycle(long roundNumber, boolean started) {}
}
