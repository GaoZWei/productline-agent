package com.productline.business.domain.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.domain.dto.EffectiveReviewSnapshot;
import com.productline.business.domain.dto.ReviewRecordDto;
import com.productline.business.domain.dto.ReworkLifecycleSnapshot.Review;
import com.productline.business.domain.enums.ReviewStatus;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 按同源连续轮次和材料绑定选有效复核，旧review_records从不混入受控结论。 */
@Repository
public class EffectiveReviewRepository {
    private static final TypeReference<List<ReviewRecordDto>> LEGACY = new TypeReference<>() {};
    private static final String ISSUES_SQL = """
            SELECT q.issue_id,l.rework_task_id,l.round_number,p.processing_revision,i.inspection_id,
                   v.review_id,v.review_sequence,v.status AS review_status,
                   v.review_comment,v.reviewed_by,v.reviewed_at,
                   coalesce(old.records,'[]'::jsonb)::text AS legacy_reviews
            FROM quality_issues q
            LEFT JOIN LATERAL (
                SELECT * FROM rework_lifecycles
                WHERE task_id=q.task_id AND source_issue_id=q.issue_id
                ORDER BY round_number DESC LIMIT 1
            ) l ON TRUE
            LEFT JOIN LATERAL (
                SELECT * FROM rework_processing_revisions WHERE rework_task_id=l.rework_task_id
                ORDER BY processing_revision DESC LIMIT 1
            ) p ON TRUE
            LEFT JOIN LATERAL (
                SELECT * FROM rework_inspections
                WHERE rework_task_id=l.rework_task_id AND processing_revision=p.processing_revision
                ORDER BY inspection_sequence DESC LIMIT 1
            ) i ON TRUE
            LEFT JOIN LATERAL (
                SELECT * FROM rework_reviews
                WHERE rework_task_id=l.rework_task_id AND processing_revision=p.processing_revision
                  AND inspection_id=i.inspection_id AND i.result='PASSED'
                ORDER BY review_sequence DESC LIMIT 1
            ) v ON TRUE
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object('reviewId',r.review_id,'issueId',r.issue_id,
                    'status',r.status,'reviewComment',r.review_comment) ORDER BY r.review_id) AS records
                FROM review_records r WHERE r.issue_id=q.issue_id AND l.rework_task_id IS NULL
            ) old ON TRUE
            WHERE q.task_id=? ORDER BY q.issue_id ASC
            """;
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public EffectiveReviewRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public Optional<Long> taskVersion(String task) {
        return jdbc.query("SELECT version FROM production_tasks WHERE task_id=?", (rs, row) -> rs.getLong(1), task)
                .stream().findFirst();
    }

    public List<EffectiveReviewSnapshot> issues(String task) {
        return jdbc.query(ISSUES_SQL, (rs, row) -> {
            Long round = rs.getObject("round_number", Long.class);
            Long revision = rs.getObject("processing_revision", Long.class);
            var review = rs.getString("review_id") == null ? null : new Review(rs.getString("review_id"),
                    rs.getLong("review_sequence"), round, revision, rs.getString("inspection_id"),
                    ReviewStatus.valueOf(rs.getString("review_status")), rs.getString("review_comment"),
                    rs.getString("reviewed_by"), rs.getTimestamp("reviewed_at").toInstant());
            return new EffectiveReviewSnapshot(rs.getString("issue_id"), rs.getString("rework_task_id"),
                    round, revision, rs.getString("inspection_id"), review, legacy(rs.getString("legacy_reviews")));
        }, task);
    }

    private List<ReviewRecordDto> legacy(String json) {
        try {
            return mapper.readValue(json, LEGACY);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored legacy review is invalid");
        }
    }
}
