package com.productline.business.domain.model;

import com.productline.business.domain.enums.ProductionTaskStatus;
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
@Table(name = "rework_tasks")
public class ReworkTask {
    // 表示由质检问题产生的返工任务
    @Id
    @Column(name = "rework_task_id", nullable = false, length = 64)
    private String reworkTaskId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "task_id", nullable = false)
    private ProductionTask task;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "source_issue_id")
    private QualityIssue sourceIssue;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private ProductionTaskStatus status;

    @Column(name = "reason", nullable = false, length = 1000)
    private String reason;

    protected ReworkTask() {
    }

    public ReworkTask(
            String reworkTaskId,
            ProductionTaskStatus status,
            String reason) {
        this.reworkTaskId = requireText(reworkTaskId, "reworkTaskId");
        this.status = Objects.requireNonNull(status, "status");
        this.reason = requireText(reason, "reason");
    }

    // 在返工任务挂到生产任务时校验来源问题
    void assignTo(ProductionTask task) {
        ProductionTask requiredTask = Objects.requireNonNull(task, "task");
        if (this.task != null && this.task != requiredTask) {
            throw new IllegalStateException("rework task is already assigned to another task");
        }
        if (sourceIssue != null
                && sourceIssue.getTask() != null
                && sourceIssue.getTask() != requiredTask) {
            throw new IllegalArgumentException(
                    "source issue must belong to the same production task");
        }
        this.task = requiredTask;
    }

    // 在设置来源问题时反向校验
    public void setSourceIssue(QualityIssue sourceIssue) {
        QualityIssue requiredIssue = Objects.requireNonNull(sourceIssue, "sourceIssue");
        if (task != null
                && requiredIssue.getTask() != null
                && requiredIssue.getTask() != task) {
            throw new IllegalArgumentException(
                    "source issue must belong to the same production task");
        }
        this.sourceIssue = requiredIssue;
    }

    public String getReworkTaskId() {
        return reworkTaskId;
    }

    public ProductionTask getTask() {
        return task;
    }

    public QualityIssue getSourceIssue() {
        return sourceIssue;
    }

    public ProductionTaskStatus getStatus() {
        return status;
    }

    public String getReason() {
        return reason;
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
