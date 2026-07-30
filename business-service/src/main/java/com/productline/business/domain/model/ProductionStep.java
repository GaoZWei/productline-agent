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
@Table(name = "production_steps")
public class ProductionStep {
    // 描述具体生产步骤。步骤序号必须大于零，同一生产任务内数据库层面不能重复。
    @Id
    @Column(name = "step_id", nullable = false, length = 64)
    private String stepId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "task_id", nullable = false)
    private ProductionTask task;

    @Column(name = "step_name", nullable = false, length = 128)
    private String stepName;

    @Column(name = "sequence_number", nullable = false)
    private int sequenceNumber;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private ProductionTaskStatus status;

    protected ProductionStep() {
    }

    public ProductionStep(
            String stepId,
            String stepName,
            int sequenceNumber,
            ProductionTaskStatus status) {
        this.stepId = requireText(stepId, "stepId");
        this.stepName = requireText(stepName, "stepName");
        if (sequenceNumber <= 0) {
            throw new IllegalArgumentException("sequenceNumber must be greater than zero");
        }
        this.sequenceNumber = sequenceNumber;
        this.status = Objects.requireNonNull(status, "status");
    }

    void assignTo(ProductionTask task) {
        ProductionTask requiredTask = Objects.requireNonNull(task, "task");
        if (this.task != null && this.task != requiredTask) {
            throw new IllegalStateException("step is already assigned to another task");
        }
        this.task = requiredTask;
    }

    public String getStepId() {
        return stepId;
    }

    public ProductionTask getTask() {
        return task;
    }

    public String getStepName() {
        return stepName;
    }

    public int getSequenceNumber() {
        return sequenceNumber;
    }

    public ProductionTaskStatus getStatus() {
        return status;
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
