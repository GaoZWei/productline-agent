package com.productline.business.domain.model;

import java.util.Optional;

/** 用明确提供的轮次和业务身份定位一次返工，不根据历史记录或随机ID推断轮次。 */
public record ReworkRound(String reworkTaskId, String taskId, String sourceIssueId, long roundNumber) {

    public ReworkRound {
        requireText(reworkTaskId, "reworkTaskId");
        requireText(taskId, "taskId");
        requireText(sourceIssueId, "sourceIssueId");
        if (roundNumber <= 0) {
            throw new IllegalArgumentException("roundNumber must be greater than zero");
        }
        if (roundNumber > 9007199254740991L) {
            throw new IllegalArgumentException("roundNumber must be a positive safe integer");
        }
    }

    public static ReworkRound from(ReworkTask rework, long roundNumber) {
        ReworkProcessingSnapshot target = ReworkProcessingSnapshot.unrecorded(rework);
        String issueId = target.getSourceIssueId().orElseThrow(
                () -> new IllegalStateException("rework round requires a source issue"));
        return new ReworkRound(target.getReworkTaskId(), target.getTaskId(), issueId, roundNumber);
    }

    /** 业务身份校验不替代权限校验，也不证明轮次已持久化或可进入下一轮。 */
    public void requireBelongsTo(ReworkTask rework) {
        ReworkProcessingSnapshot current = ReworkProcessingSnapshot.unrecorded(rework);
        if (!reworkTaskId.equals(current.getReworkTaskId())
                || !taskId.equals(current.getTaskId())
                || !Optional.of(sourceIssueId).equals(current.getSourceIssueId())) {
            throw new IllegalArgumentException(
                    "rework round must belong to the same rework, task and source issue");
        }
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
    }
}
