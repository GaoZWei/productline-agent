package com.productline.business.domain.model;

import com.productline.business.domain.enums.ProductionTaskStatus;
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
@Table(name = "production_tasks")
public class ProductionTask {
    // 承载生产步骤、质检问题和返工任务
    @Id
    @Column(name = "task_id", nullable = false, length = 64)
    private String taskId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "order_id", nullable = false)
    private Order order;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private ProductionTaskStatus status;

    @OneToMany(mappedBy = "task", cascade = CascadeType.ALL, orphanRemoval = true)
    private final List<ProductionStep> steps = new ArrayList<>();

    @OneToMany(mappedBy = "task", cascade = CascadeType.ALL, orphanRemoval = true)
    private final List<QualityIssue> qualityIssues = new ArrayList<>();

    @OneToMany(mappedBy = "task", cascade = CascadeType.ALL, orphanRemoval = true)
    private final List<ReworkTask> reworkTasks = new ArrayList<>();

    protected ProductionTask() {
    }

    public ProductionTask(String taskId, ProductionTaskStatus status) {
        this.taskId = requireText(taskId, "taskId");
        this.status = Objects.requireNonNull(status, "status");
    }

    void assignTo(Order order) {
        Order requiredOrder = Objects.requireNonNull(order, "order");
        if (this.order != null && this.order != requiredOrder) {
            throw new IllegalStateException("task is already assigned to another order");
        }
        this.order = requiredOrder;
    }

    public void addStep(ProductionStep step) {
        ProductionStep requiredStep = Objects.requireNonNull(step, "step");
        requiredStep.assignTo(this);
        steps.add(requiredStep);
    }
    // 添加质检问题
    public void addQualityIssue(QualityIssue issue) {
        QualityIssue requiredIssue = Objects.requireNonNull(issue, "issue");
        requiredIssue.assignTo(this);
        qualityIssues.add(requiredIssue);
    }

    public void addReworkTask(ReworkTask reworkTask) {
        ReworkTask requiredTask = Objects.requireNonNull(reworkTask, "reworkTask");
        requiredTask.assignTo(this);
        reworkTasks.add(requiredTask);
    }

    public String getTaskId() {
        return taskId;
    }

    public Order getOrder() {
        return order;
    }

    public ProductionTaskStatus getStatus() {
        return status;
    }

    public List<ProductionStep> getSteps() {
        return Collections.unmodifiableList(steps);
    }

    public List<QualityIssue> getQualityIssues() {
        return Collections.unmodifiableList(qualityIssues);
    }

    public List<ReworkTask> getReworkTasks() {
        return Collections.unmodifiableList(reworkTasks);
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
