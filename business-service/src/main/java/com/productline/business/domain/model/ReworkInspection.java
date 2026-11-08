package com.productline.business.domain.model;

import com.productline.business.domain.enums.ReworkInspectionResult;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * 保留一次人工检查及其绑定材料的不可变领域记录，同轮多次检查各有独立身份。
 * 不持久化、不验证原件或人员权限、不选择当前有效检查，也不推进返工、问题或复核状态。
 */
public final class ReworkInspection {

    private final String inspectionId;
    private final ReworkRound round;
    private final ReworkProcessingEvidence processingEvidence;
    private final String inspectorId;
    private final Instant inspectedAt;
    private final List<ReworkInspectionItem> items;
    private final ReworkInspectionResult result;

    private ReworkInspection(
            String inspectionId, ReworkRound round, ReworkProcessingEvidence processingEvidence,
            String inspectorId, Instant inspectedAt, List<ReworkInspectionItem> items) {
        this.inspectionId = inspectionId;
        this.round = round;
        this.processingEvidence = processingEvidence;
        this.inspectorId = inspectorId;
        this.inspectedAt = inspectedAt;
        this.items = items;
        this.result = items.stream().allMatch(item -> item.result() == ReworkInspectionResult.PASSED)
                ? ReworkInspectionResult.PASSED : ReworkInspectionResult.FAILED;
    }

    /** 人工材料只说明已提供完整登记输入，真实身份、时间及原件仍由后续应用核实。 */
    public static ReworkInspection recorded(
            String inspectionId, ReworkRound round, ReworkTask rework,
            ReworkProcessingSnapshot processing, String inspectorId, Instant inspectedAt,
            List<ReworkInspectionItem> items) {
        requireText(inspectionId, "inspectionId");
        requireText(inspectorId, "inspectorId");
        Objects.requireNonNull(round, "round").requireBelongsTo(rework);
        Objects.requireNonNull(processing, "processing").requireBelongsTo(rework);
        Objects.requireNonNull(inspectedAt, "inspectedAt");
        Objects.requireNonNull(items, "items");
        List<ReworkInspectionItem> capturedItems = new ArrayList<>(items);
        if (capturedItems.isEmpty()) {
            throw new IllegalArgumentException("items must not be empty");
        }
        capturedItems.forEach(item -> Objects.requireNonNull(item, "inspection item"));
        return new ReworkInspection(inspectionId, round, requireEvidence(processing), inspectorId,
                inspectedAt, List.copyOf(capturedItems));
    }

    /** 比较完整处理材料，避免同一成果版本下更换处理说明或证据后仍沿用旧检查。 */
    public void requireAppliesTo(
            ReworkRound currentRound, ReworkTask rework, ReworkProcessingSnapshot currentProcessing) {
        Objects.requireNonNull(currentRound, "currentRound").requireBelongsTo(rework);
        Objects.requireNonNull(currentProcessing, "currentProcessing").requireBelongsTo(rework);
        if (!round.equals(currentRound)) {
            throw new IllegalArgumentException("inspection must belong to the same rework round");
        }
        if (!processingEvidence.equals(requireEvidence(currentProcessing))) {
            throw new IllegalArgumentException("inspection does not apply to the current processing evidence");
        }
    }

    private static ReworkProcessingEvidence requireEvidence(ReworkProcessingSnapshot processing) {
        return processing.getEvidence().orElseThrow(
                () -> new IllegalStateException("inspection requires recorded processing evidence"));
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
    }

    public String getInspectionId() {
        return inspectionId;
    }

    public ReworkRound getRound() {
        return round;
    }

    public ReworkProcessingEvidence getProcessingEvidence() {
        return processingEvidence;
    }

    public String getInspectorId() {
        return inspectorId;
    }

    public Instant getInspectedAt() {
        return inspectedAt;
    }

    public List<ReworkInspectionItem> getItems() {
        return items;
    }

    public ReworkInspectionResult getResult() {
        return result;
    }
}
