ALTER TABLE production_tasks
    ADD COLUMN version BIGINT NOT NULL DEFAULT 0;

CREATE TABLE idempotency_records (
    idempotency_key VARCHAR(128) PRIMARY KEY,
    operation_type VARCHAR(32) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    actor_user_id VARCHAR(128) NOT NULL,
    resource_id VARCHAR(64),
    task_version_after BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_idempotency_operation_type CHECK (
        operation_type IN ('SUBMIT_REVIEW', 'CREATE_REWORK')
    ),
    CONSTRAINT ck_idempotency_completion CHECK (
        (resource_id IS NULL AND task_version_after IS NULL)
        OR (resource_id IS NOT NULL AND task_version_after IS NOT NULL)
    )
);

CREATE TABLE operation_logs (
    operation_id VARCHAR(64) PRIMARY KEY,
    operation_type VARCHAR(32) NOT NULL,
    target_type VARCHAR(32) NOT NULL,
    target_id VARCHAR(64) NOT NULL,
    actor_user_id VARCHAR(128) NOT NULL,
    idempotency_key_hash VARCHAR(64) NOT NULL,
    before_state TEXT NOT NULL,
    after_state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_operation_logs_operation_type CHECK (
        operation_type IN ('SUBMIT_REVIEW', 'CREATE_REWORK')
    )
);

CREATE INDEX idx_operation_logs_target
    ON operation_logs (target_type, target_id, created_at);
