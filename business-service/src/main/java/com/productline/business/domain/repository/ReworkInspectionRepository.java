package com.productline.business.domain.repository;

import com.productline.business.domain.model.ReworkInspection;
import java.time.ZoneOffset;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 人工检查只追加，必须在持有父任务及本轮/问题状态锁的应用事务内调用。 */
@Repository
public class ReworkInspectionRepository {
    private final JdbcTemplate jdbc;

    public ReworkInspectionRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public long latestSequence(String reworkId) {
        return jdbc.queryForObject("SELECT COALESCE(MAX(inspection_sequence),0) FROM rework_inspections WHERE rework_task_id=?", Long.class, reworkId);
    }

    public int append(ReworkInspection inspection, long revision, long sequence, String itemsJson) {
        return jdbc.update("""
                INSERT INTO rework_inspections(inspection_id,rework_task_id,processing_revision,
                    inspection_sequence,result,items,inspector_id,inspected_at) VALUES (?,?,?,?,?,?::jsonb,?,?)
                """, inspection.getInspectionId(), inspection.getRound().reworkTaskId(), revision, sequence,
                inspection.getResult().name(), itemsJson, inspection.getInspectorId(), inspection.getInspectedAt().atOffset(ZoneOffset.UTC));
    }

    public int complete(String taskId, String reworkId) {
        return jdbc.update("UPDATE rework_tasks SET status='COMPLETED' WHERE task_id=? AND rework_task_id=? AND status='RUNNING'", taskId, reworkId);
    }

    public int resolve(String taskId, String issueId) {
        return jdbc.update("UPDATE quality_issues SET status='RESOLVED' WHERE task_id=? AND issue_id=? AND status='PROCESSING'", taskId, issueId);
    }
}
