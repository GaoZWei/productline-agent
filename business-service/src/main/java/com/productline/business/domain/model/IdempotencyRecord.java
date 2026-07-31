package com.productline.business.domain.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "idempotency_records")
public class IdempotencyRecord {

    @Id
    @Column(name = "idempotency_key", nullable = false, length = 128)
    private String idempotencyKey;

    @Column(name = "operation_type", nullable = false, length = 32)
    private String operationType;

    @Column(name = "request_hash", nullable = false, length = 64)
    private String requestHash;

    @Column(name = "actor_user_id", nullable = false, length = 128)
    private String actorUserId;

    @Column(name = "resource_id", length = 64)
    private String resourceId;

    @Column(name = "task_version_after")
    private Long taskVersionAfter;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected IdempotencyRecord() {
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public String getOperationType() {
        return operationType;
    }

    public String getRequestHash() {
        return requestHash;
    }

    public String getActorUserId() {
        return actorUserId;
    }

    public String getResourceId() {
        return resourceId;
    }

    public Long getTaskVersionAfter() {
        return taskVersionAfter;
    }

    public boolean isCompleted() {
        return resourceId != null && taskVersionAfter != null;
    }

    public void complete(String resourceId, long taskVersionAfter) {
        if (isCompleted()) {
            throw new IllegalStateException("idempotency record is already completed");
        }
        this.resourceId = resourceId;
        this.taskVersionAfter = taskVersionAfter;
    }
}
