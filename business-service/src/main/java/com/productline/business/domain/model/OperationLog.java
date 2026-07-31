package com.productline.business.domain.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.Objects;

@Entity
@Table(name = "operation_logs")
public class OperationLog {

    @Id
    @Column(name = "operation_id", nullable = false, length = 64)
    private String operationId;

    @Column(name = "operation_type", nullable = false, length = 32)
    private String operationType;

    @Column(name = "target_type", nullable = false, length = 32)
    private String targetType;

    @Column(name = "target_id", nullable = false, length = 64)
    private String targetId;

    @Column(name = "actor_user_id", nullable = false, length = 128)
    private String actorUserId;

    @Column(name = "idempotency_key_hash", nullable = false, length = 64)
    private String idempotencyKeyHash;

    @Column(name = "before_state", nullable = false, columnDefinition = "TEXT")
    private String beforeState;

    @Column(name = "after_state", nullable = false, columnDefinition = "TEXT")
    private String afterState;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected OperationLog() {
    }

    public OperationLog(
            String operationId,
            String operationType,
            String targetType,
            String targetId,
            String actorUserId,
            String idempotencyKeyHash,
            String beforeState,
            String afterState) {
        this.operationId = requireText(operationId, "operationId");
        this.operationType = requireText(operationType, "operationType");
        this.targetType = requireText(targetType, "targetType");
        this.targetId = requireText(targetId, "targetId");
        this.actorUserId = requireText(actorUserId, "actorUserId");
        this.idempotencyKeyHash = requireText(idempotencyKeyHash, "idempotencyKeyHash");
        this.beforeState = requireText(beforeState, "beforeState");
        this.afterState = requireText(afterState, "afterState");
        this.createdAt = Instant.now();
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name);
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
