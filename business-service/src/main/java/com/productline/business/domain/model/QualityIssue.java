package com.productline.business.domain.model;

import com.productline.business.domain.enums.QualityIssueStatus;
import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

@Entity
@Table(name = "quality_issues")
public class QualityIssue {
    // 保存问题类型、状态和描述，并通过 addReviewRecord 管理复核历史
    @Id
    @Column(name = "issue_id", nullable = false, length = 64)
    private String issueId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "task_id", nullable = false)
    private ProductionTask task;

    @Column(name = "issue_type", nullable = false, length = 64)
    private String issueType;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private QualityIssueStatus status;

    @Column(name = "description", nullable = false, length = 1000)
    private String description;

    @OneToMany(mappedBy = "issue", cascade = CascadeType.ALL, orphanRemoval = true)
    private final List<ReviewRecord> reviewRecords = new ArrayList<>();

    protected QualityIssue() {
    }

    public QualityIssue(
            String issueId,
            String issueType,
            QualityIssueStatus status,
            String description) {
        this.issueId = requireText(issueId, "issueId");
        this.issueType = requireText(issueType, "issueType");
        this.status = Objects.requireNonNull(status, "status");
        this.description = requireText(description, "description");
    }

    void assignTo(ProductionTask task) {
        ProductionTask requiredTask = Objects.requireNonNull(task, "task");
        if (this.task != null && this.task != requiredTask) {
            throw new IllegalStateException("issue is already assigned to another task");
        }
        this.task = requiredTask;
    }
    // 管理复核历史
    public void addReviewRecord(ReviewRecord reviewRecord) {
        ReviewRecord requiredRecord = Objects.requireNonNull(reviewRecord, "reviewRecord");
        requiredRecord.assignTo(this);
        reviewRecords.add(requiredRecord);
    }

    public String getIssueId() {
        return issueId;
    }

    public ProductionTask getTask() {
        return task;
    }

    public String getIssueType() {
        return issueType;
    }

    public QualityIssueStatus getStatus() {
        return status;
    }

    public String getDescription() {
        return description;
    }

    public List<ReviewRecord> getReviewRecords() {
        return Collections.unmodifiableList(reviewRecords);
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
