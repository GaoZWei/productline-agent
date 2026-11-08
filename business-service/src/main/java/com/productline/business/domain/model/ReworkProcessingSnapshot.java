package com.productline.business.domain.model;

import java.util.Objects;
import java.util.Optional;

/**
 * 将处理证据绑定到返工、生产任务和来源问题的不可变领域快照。
 * 这里只校验登记材料与资源关联，不持久化、不推进状态，也不代替权限、版本或人工确认校验。
 */
public final class ReworkProcessingSnapshot {

    private final String reworkTaskId;
    private final String taskId;
    private final Optional<String> sourceIssueId;
    private final Optional<ReworkProcessingEvidence> evidence;

    private ReworkProcessingSnapshot(
            String reworkTaskId,
            String taskId,
            Optional<String> sourceIssueId,
            Optional<ReworkProcessingEvidence> evidence) {
        this.reworkTaskId = reworkTaskId;
        this.taskId = taskId;
        this.sourceIssueId = sourceIssueId;
        this.evidence = evidence;
    }

    /** 显式表示尚未登记材料；历史记录缺少来源问题时也保留为空，不补造事实。 */
    public static ReworkProcessingSnapshot unrecorded(ReworkTask rework) {
        return capture(rework, Optional.empty());
    }

    /** 表示已提供完整登记材料，不表示材料已落库、检查通过或问题已解决。 */
    public static ReworkProcessingSnapshot recorded(
            ReworkTask rework, ReworkProcessingEvidence evidence) {
        return capture(rework, Optional.of(Objects.requireNonNull(evidence, "evidence")));
    }

    private static ReworkProcessingSnapshot capture(
            ReworkTask rework, Optional<ReworkProcessingEvidence> evidence) {
        Objects.requireNonNull(rework, "rework");
        ProductionTask task = rework.getTask();
        if (task == null) {
            throw new IllegalStateException("rework must belong to a production task");
        }
        QualityIssue issue = rework.getSourceIssue();
        if (issue == null && evidence.isPresent()) {
            throw new IllegalStateException("recorded evidence requires a source issue");
        }
        if (issue != null && (issue.getTask() == null
                || !task.getTaskId().equals(issue.getTask().getTaskId()))) {
            throw new IllegalStateException("source issue must belong to the rework production task");
        }
        return new ReworkProcessingSnapshot(
                rework.getReworkTaskId(),
                task.getTaskId(),
                Optional.ofNullable(issue).map(QualityIssue::getIssueId),
                evidence);
    }

    /** 防止调用方将旧材料误用于另一个返工或已改变来源的返工；不能替代并发版本校验。 */
    public void requireBelongsTo(ReworkTask rework) {
        ReworkProcessingSnapshot current = unrecorded(rework);
        if (!reworkTaskId.equals(current.reworkTaskId)
                || !taskId.equals(current.taskId)
                || !sourceIssueId.equals(current.sourceIssueId)) {
            throw new IllegalArgumentException(
                    "processing snapshot must belong to the same rework, task and source issue");
        }
    }

    public String getReworkTaskId() {
        return reworkTaskId;
    }

    public String getTaskId() {
        return taskId;
    }

    public Optional<String> getSourceIssueId() {
        return sourceIssueId;
    }

    public Optional<ReworkProcessingEvidence> getEvidence() {
        return evidence;
    }
}
