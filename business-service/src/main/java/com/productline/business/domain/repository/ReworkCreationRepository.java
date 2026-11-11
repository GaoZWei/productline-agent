package com.productline.business.domain.repository;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 受控创建的SQL写集；父任务锁、版本、生命周期、审计及回执由应用层同事务组织。 */
@Repository
public class ReworkCreationRepository {
    private final JdbcTemplate jdbc;

    public ReworkCreationRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Task task(String taskId) {
        return jdbc.queryForObject("SELECT version,status FROM production_tasks WHERE task_id=?",
                (rs, row) -> new Task(rs.getLong("version"), ProductionTaskStatus.valueOf(rs.getString("status"))), taskId);
    }

    public Optional<Issue> lockIssue(String issueId) {
        // 锁住OPEN事实至提交，同时兼容旧写入所需的外键KEY SHARE。
        return jdbc.query("SELECT task_id,status FROM quality_issues WHERE issue_id=? FOR NO KEY UPDATE",
                (rs, row) -> new Issue(rs.getString("task_id"), QualityIssueStatus.valueOf(rs.getString("status"))), issueId)
                .stream().findFirst();
    }

    public boolean hasLifecycle(String taskId, String issueId) {
        return Boolean.TRUE.equals(jdbc.queryForObject("""
                SELECT EXISTS (SELECT 1 FROM rework_lifecycles WHERE task_id=? AND source_issue_id=?)
                """, Boolean.class, taskId, issueId));
    }

    public boolean hasActive(String taskId, String issueId) {
        return Boolean.TRUE.equals(jdbc.queryForObject("""
                SELECT EXISTS (SELECT 1 FROM rework_tasks r
                  LEFT JOIN rework_lifecycles l ON l.rework_task_id=r.rework_task_id
                  WHERE r.task_id=? AND r.source_issue_id=?
                    AND (r.status IN ('PENDING','RUNNING','BLOCKED') OR (r.status='FAILED' AND l.rework_task_id IS NOT NULL)))
                """, Boolean.class, taskId, issueId));
    }

    public boolean lockCompleted(String taskId, String reworkId) {
        return !jdbc.query("SELECT rework_task_id FROM rework_tasks WHERE task_id=? AND rework_task_id=? AND status='COMPLETED' FOR NO KEY UPDATE",
                (rs, row) -> rs.getString(1), taskId, reworkId).isEmpty();
    }

    public int create(String taskId, String issueId, String reworkId, String reason) {
        return jdbc.update("INSERT INTO rework_tasks(rework_task_id,task_id,source_issue_id,status,reason) VALUES (?,?,?,'PENDING',?)",
                reworkId, taskId, issueId, reason);
    }

    public int lifecycle(String taskId, String issueId, String reworkId, long round,
            String previousId, String actor, Instant now) {
        return jdbc.update("""
                INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,
                    previous_rework_task_id,previous_round_number,created_by,created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """, reworkId, taskId, issueId, round, previousId, previousId == null ? null : round - 1,
                actor, now.atOffset(ZoneOffset.UTC));
    }

    public record Task(long version, ProductionTaskStatus status) {}
    public record Issue(String taskId, QualityIssueStatus status) {}
}
