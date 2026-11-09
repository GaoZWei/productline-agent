package com.productline.business.domain.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.domain.dto.ReworkLifecycleSnapshot;
import com.productline.business.domain.dto.ReworkTaskDto;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.model.ReworkArtifact;
import com.productline.business.domain.model.ReworkInspectionItem;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 读取V5材料表，不改变既有JPA实体或将历史缺失自动纳管。 */
@Repository
public class ReworkReadRepository {
    private static final TypeReference<List<String>> REFERENCES = new TypeReference<>() {};
    private static final TypeReference<List<ReworkInspectionItem>> ITEMS = new TypeReference<>() {};
    private static final String DETAIL_SQL = """
            SELECT rw.rework_task_id, rw.task_id, rw.source_issue_id, rw.status, rw.reason,
                   t.status AS task_status, t.version AS task_version, q.status AS issue_status,
                   l.round_number, l.previous_rework_task_id,
                   p.processing_revision, p.artifact_id, p.artifact_version, p.processing_comment,
                   p.evidence_references::text, p.registered_by, p.registered_at,
                   i.inspection_id, i.inspection_sequence, i.inspector_id, i.inspected_at,
                   i.result AS inspection_result, i.items::text,
                   v.review_id, v.review_sequence, v.status AS review_status,
                   v.review_comment, v.reviewed_by, v.reviewed_at,
                   EXISTS (SELECT 1 FROM rework_lifecycles n
                           WHERE n.previous_rework_task_id = rw.rework_task_id) AS has_successor,
                   EXISTS (SELECT 1 FROM rework_tasks a
                           LEFT JOIN rework_lifecycles al ON al.rework_task_id = a.rework_task_id
                           WHERE a.task_id = rw.task_id AND a.source_issue_id = rw.source_issue_id
                             AND a.rework_task_id <> rw.rework_task_id
                             AND (a.status IN ('PENDING', 'RUNNING', 'BLOCKED')
                                  OR (a.status = 'FAILED' AND al.rework_task_id IS NOT NULL)))
                       AS has_other_active_rework
            FROM rework_tasks rw
            JOIN production_tasks t ON t.task_id = rw.task_id
            LEFT JOIN quality_issues q ON q.issue_id = rw.source_issue_id AND q.task_id = rw.task_id
            LEFT JOIN rework_lifecycles l ON l.rework_task_id = rw.rework_task_id
            LEFT JOIN LATERAL (
                SELECT * FROM rework_processing_revisions
                WHERE rework_task_id = rw.rework_task_id ORDER BY processing_revision DESC LIMIT 1
            ) p ON TRUE
            LEFT JOIN LATERAL (
                SELECT * FROM rework_inspections
                WHERE rework_task_id = rw.rework_task_id AND processing_revision = p.processing_revision
                ORDER BY inspection_sequence DESC LIMIT 1
            ) i ON TRUE
            LEFT JOIN LATERAL (
                SELECT * FROM rework_reviews
                WHERE rework_task_id = rw.rework_task_id AND processing_revision = p.processing_revision
                  AND inspection_id = i.inspection_id AND i.result = 'PASSED'
                ORDER BY review_sequence DESC LIMIT 1
            ) v ON TRUE
            WHERE rw.task_id = ? AND rw.rework_task_id = ?
            """;

    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public ReworkReadRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public boolean taskExists(String taskId) {
        return Boolean.TRUE.equals(jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM production_tasks WHERE task_id = ?)", Boolean.class, taskId));
    }

    public Optional<String> findOwner(String reworkTaskId) {
        return jdbc.query("SELECT task_id FROM rework_tasks WHERE rework_task_id = ?",
                (rs, row) -> rs.getString("task_id"), reworkTaskId).stream().findFirst();
    }

    public Optional<ReworkLifecycleSnapshot> findDetail(String taskId, String reworkTaskId) {
        return jdbc.query(DETAIL_SQL, (rs, row) -> map(rs), taskId, reworkTaskId).stream().findFirst();
    }

    private ReworkLifecycleSnapshot map(ResultSet rs) throws SQLException {
        Long round = rs.getObject("round_number", Long.class);
        Long revision = rs.getObject("processing_revision", Long.class);
        var processing = revision == null ? null : new ReworkLifecycleSnapshot.Processing(
                revision, new ReworkArtifact(rs.getString("artifact_id"), rs.getString("artifact_version")),
                rs.getString("processing_comment"), json(rs.getString("evidence_references"), REFERENCES),
                rs.getString("registered_by"), rs.getTimestamp("registered_at").toInstant());
        var inspection = rs.getString("inspection_id") == null ? null : new ReworkLifecycleSnapshot.Inspection(
                rs.getString("inspection_id"), rs.getLong("inspection_sequence"), round, revision,
                rs.getString("inspector_id"), rs.getTimestamp("inspected_at").toInstant(),
                ReworkInspectionResult.valueOf(rs.getString("inspection_result")),
                json(rs.getString("items"), ITEMS));
        var review = rs.getString("review_id") == null ? null : new ReworkLifecycleSnapshot.Review(
                rs.getString("review_id"), rs.getLong("review_sequence"), round, revision,
                rs.getString("inspection_id"), ReviewStatus.valueOf(rs.getString("review_status")),
                rs.getString("review_comment"), rs.getString("reviewed_by"),
                rs.getTimestamp("reviewed_at").toInstant());
        String issueStatus = rs.getString("issue_status");
        return new ReworkLifecycleSnapshot(
                new ReworkTaskDto(rs.getString("rework_task_id"), rs.getString("task_id"),
                        rs.getString("source_issue_id"), ProductionTaskStatus.valueOf(rs.getString("status")),
                        rs.getString("reason")),
                ProductionTaskStatus.valueOf(rs.getString("task_status")), rs.getLong("task_version"),
                issueStatus == null ? null : QualityIssueStatus.valueOf(issueStatus),
                round, rs.getString("previous_rework_task_id"), processing, inspection, review,
                rs.getBoolean("has_successor"), rs.getBoolean("has_other_active_rework"));
    }

    private <T> T json(String value, TypeReference<T> type) {
        try {
            return mapper.readValue(value, type);
        } catch (JsonProcessingException exception) {
            // 不将数据库材料或原件引用写入错误文案。
            throw new IllegalStateException("stored rework material is invalid");
        }
    }
}
