package com.productline.business.domain.repository;

import com.productline.business.domain.enums.ReviewStatus;
import java.time.Instant;
import java.time.ZoneOffset;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 复核只追加；本轮完成事实和来源问题必须在父任务锁保护下保持至事务提交。 */
@Repository
public class ReworkReviewRepository {
    private final JdbcTemplate jdbc;

    public ReworkReviewRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public boolean lockResolvedIssue(String task, String issue) {
        return !jdbc.query("SELECT issue_id FROM quality_issues WHERE task_id=? AND issue_id=? AND status='RESOLVED' FOR NO KEY UPDATE",
                (rs, row) -> rs.getString(1), task, issue).isEmpty();
    }

    public boolean lockCompleted(String task, String rework) {
        return !jdbc.query("SELECT rework_task_id FROM rework_tasks WHERE task_id=? AND rework_task_id=? AND status='COMPLETED' FOR NO KEY UPDATE",
                (rs, row) -> rs.getString(1), task, rework).isEmpty();
    }

    public long latestSequence(String rework) {
        return jdbc.queryForObject("SELECT coalesce(max(review_sequence),0) FROM rework_reviews WHERE rework_task_id=?", Long.class, rework);
    }

    public int append(String reviewId, String rework, long revision, String inspection, long sequence,
            ReviewStatus status, String comment, String actor, Instant reviewedAt) {
        return jdbc.update("""
                INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,
                    review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,?,?,?,?)
                """, reviewId, rework, revision, inspection, sequence, status.name(), comment, actor, reviewedAt.atOffset(ZoneOffset.UTC));
    }

    public int close(String task, String issue) {
        return jdbc.update("UPDATE quality_issues SET status='CLOSED' WHERE task_id=? AND issue_id=? AND status='RESOLVED'", task, issue);
    }
}
