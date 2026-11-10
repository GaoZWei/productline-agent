package com.productline.business.domain.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.domain.dto.ReworkLifecycleSnapshot.Inspection;
import com.productline.business.domain.dto.ReworkLifecycleSnapshot.Processing;
import com.productline.business.domain.dto.ReworkLifecycleSnapshot.Review;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.model.ReworkArtifact;
import com.productline.business.domain.model.ReworkInspectionItem;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 按Java序号读取全部真实历史，不用“当前有效”过滤器丢弃旧失败或旧修订。 */
@Repository
public class ReworkHistoryRepository {
    public enum Kind {
        RESULTS("rework_processing_revisions", "processing_revision"),
        INSPECTIONS("rework_inspections", "inspection_sequence"),
        REVIEWS("rework_reviews", "review_sequence");
        final String table;
        final String sequence;
        Kind(String table, String sequence) { this.table = table; this.sequence = sequence; }
    }

    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public ReworkHistoryRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public long upper(String task, String rework, Kind kind) {
        // 动态SQL片段仅来自固定枚举，所有调用方输入仍以参数绑定。
        return jdbc.queryForObject("SELECT coalesce(max(h." + kind.sequence + "),0) FROM " + kind.table
                + " h JOIN rework_tasks r ON r.rework_task_id=h.rework_task_id WHERE r.task_id=? AND r.rework_task_id=?",
                Long.class, task, rework);
    }

    public List<Processing> results(String task, String rework, long after, long upper, int count) {
        return jdbc.query("""
                SELECT h.* FROM rework_processing_revisions h
                JOIN rework_tasks r ON r.rework_task_id=h.rework_task_id
                WHERE r.task_id=? AND r.rework_task_id=? AND h.processing_revision>? AND h.processing_revision<=?
                ORDER BY h.processing_revision ASC LIMIT ?
                """, (rs, row) -> new Processing(rs.getLong("processing_revision"),
                new ReworkArtifact(rs.getString("artifact_id"), rs.getString("artifact_version")),
                rs.getString("processing_comment"), json(rs.getString("evidence_references"), new TypeReference<List<String>>() {}),
                rs.getString("registered_by"), rs.getTimestamp("registered_at").toInstant()), task, rework, after, upper, count);
    }

    public List<Inspection> inspections(String task, String rework, long after, long upper, int count) {
        return jdbc.query("""
                SELECT h.*,l.round_number FROM rework_inspections h
                JOIN rework_lifecycles l ON l.rework_task_id=h.rework_task_id
                WHERE l.task_id=? AND l.rework_task_id=? AND h.inspection_sequence>? AND h.inspection_sequence<=?
                ORDER BY h.inspection_sequence ASC LIMIT ?
                """, (rs, row) -> new Inspection(rs.getString("inspection_id"), rs.getLong("inspection_sequence"),
                rs.getLong("round_number"), rs.getLong("processing_revision"), rs.getString("inspector_id"),
                rs.getTimestamp("inspected_at").toInstant(), ReworkInspectionResult.valueOf(rs.getString("result")),
                json(rs.getString("items"), new TypeReference<List<ReworkInspectionItem>>() {})), task, rework, after, upper, count);
    }

    public List<Review> reviews(String task, String rework, long after, long upper, int count) {
        return jdbc.query("""
                SELECT h.*,l.round_number FROM rework_reviews h
                JOIN rework_lifecycles l ON l.rework_task_id=h.rework_task_id
                WHERE l.task_id=? AND l.rework_task_id=? AND h.review_sequence>? AND h.review_sequence<=?
                ORDER BY h.review_sequence ASC LIMIT ?
                """, (rs, row) -> new Review(rs.getString("review_id"), rs.getLong("review_sequence"),
                rs.getLong("round_number"), rs.getLong("processing_revision"), rs.getString("inspection_id"),
                ReviewStatus.valueOf(rs.getString("status")), rs.getString("review_comment"),
                rs.getString("reviewed_by"), rs.getTimestamp("reviewed_at").toInstant()), task, rework, after, upper, count);
    }

    private <T> T json(String value, TypeReference<T> type) {
        try {
            return mapper.readValue(value, type);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored rework history is invalid");
        }
    }
}
