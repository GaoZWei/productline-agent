package com.productline.business.domain.repository;

import java.time.Instant;
import java.time.ZoneOffset;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 处理修订只追加；序号分配和写入必须处于持有父任务锁的同一应用事务。 */
@Repository
public class ReworkResultRepository {
    private final JdbcTemplate jdbc;

    public ReworkResultRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public boolean lockRunning(String taskId, String reworkId) {
        return !jdbc.query("SELECT rework_task_id FROM rework_tasks WHERE task_id=? AND rework_task_id=? AND status='RUNNING' FOR NO KEY UPDATE",
                (rs, row) -> rs.getString(1), taskId, reworkId).isEmpty();
    }

    public long latestRevision(String reworkId) {
        return jdbc.queryForObject("SELECT COALESCE(MAX(processing_revision),0) FROM rework_processing_revisions WHERE rework_task_id=?",
                Long.class, reworkId);
    }

    public int append(String reworkId, long revision, String artifactId, String artifactVersion,
            String comment, String referencesJson, String actor, Instant registeredAt) {
        return jdbc.update("""
                INSERT INTO rework_processing_revisions(rework_task_id,processing_revision,artifact_id,
                    artifact_version,processing_comment,evidence_references,registered_by,registered_at)
                VALUES (?,?,?,?,?,?::jsonb,?,?)
                """, reworkId, revision, artifactId, artifactVersion, comment, referencesJson,
                actor, registeredAt.atOffset(ZoneOffset.UTC));
    }
}
