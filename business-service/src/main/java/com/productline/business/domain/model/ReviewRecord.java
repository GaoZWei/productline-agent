package com.productline.business.domain.model;

import com.productline.business.domain.enums.ReviewStatus;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.util.Objects;

@Entity
@Table(name = "review_records")
public class ReviewRecord {
    // 记录 PENDING、APPROVED、REJECTED 或 REWORK_REQUIRED 等复核结论
    @Id
    @Column(name = "review_id", nullable = false, length = 64)
    private String reviewId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "issue_id", nullable = false)
    private QualityIssue issue;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private ReviewStatus status;

    @Column(name = "review_comment", length = 1000)
    private String reviewComment;

    protected ReviewRecord() {
    }

    public ReviewRecord(String reviewId, ReviewStatus status, String reviewComment) {
        this.reviewId = requireText(reviewId, "reviewId");
        this.status = Objects.requireNonNull(status, "status");
        this.reviewComment = reviewComment;
    }

    void assignTo(QualityIssue issue) {
        QualityIssue requiredIssue = Objects.requireNonNull(issue, "issue");
        if (this.issue != null && this.issue != requiredIssue) {
            throw new IllegalStateException("review is already assigned to another issue");
        }
        this.issue = requiredIssue;
    }

    public String getReviewId() {
        return reviewId;
    }

    public QualityIssue getIssue() {
        return issue;
    }

    public ReviewStatus getStatus() {
        return status;
    }

    public String getReviewComment() {
        return reviewComment;
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
