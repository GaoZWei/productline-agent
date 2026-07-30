CREATE TABLE production_orders (
    order_id VARCHAR(64) PRIMARY KEY,
    product_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    CONSTRAINT ck_production_orders_status CHECK (
        status IN (
            'CREATED',
            'PRODUCING',
            'QUALITY_CHECKING',
            'REVIEWING',
            'READY_FOR_DELIVERY',
            'DELIVERING',
            'DELIVERED',
            'BLOCKED'
        )
    )
);

CREATE TABLE production_tasks (
    task_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    CONSTRAINT fk_production_tasks_order
        FOREIGN KEY (order_id) REFERENCES production_orders (order_id) ON DELETE CASCADE,
    CONSTRAINT ck_production_tasks_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'BLOCKED')
    )
);

CREATE INDEX idx_production_tasks_order_id ON production_tasks (order_id);

CREATE TABLE production_steps (
    step_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    step_name VARCHAR(128) NOT NULL,
    sequence_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    CONSTRAINT fk_production_steps_task
        FOREIGN KEY (task_id) REFERENCES production_tasks (task_id) ON DELETE CASCADE,
    CONSTRAINT uq_production_steps_task_sequence UNIQUE (task_id, sequence_number),
    CONSTRAINT ck_production_steps_sequence CHECK (sequence_number > 0),
    CONSTRAINT ck_production_steps_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'BLOCKED')
    )
);

CREATE INDEX idx_production_steps_task_id ON production_steps (task_id);

CREATE TABLE quality_issues (
    issue_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    issue_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    description VARCHAR(1000) NOT NULL,
    CONSTRAINT fk_quality_issues_task
        FOREIGN KEY (task_id) REFERENCES production_tasks (task_id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_issues_status CHECK (
        status IN ('OPEN', 'PROCESSING', 'RESOLVED', 'CLOSED')
    )
);

CREATE INDEX idx_quality_issues_task_id ON quality_issues (task_id);
CREATE INDEX idx_quality_issues_status ON quality_issues (status);

CREATE TABLE review_records (
    review_id VARCHAR(64) PRIMARY KEY,
    issue_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    review_comment VARCHAR(1000),
    CONSTRAINT fk_review_records_issue
        FOREIGN KEY (issue_id) REFERENCES quality_issues (issue_id) ON DELETE CASCADE,
    CONSTRAINT ck_review_records_status CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'REWORK_REQUIRED')
    )
);

CREATE INDEX idx_review_records_issue_id ON review_records (issue_id);

CREATE TABLE rework_tasks (
    rework_task_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    source_issue_id VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    CONSTRAINT fk_rework_tasks_task
        FOREIGN KEY (task_id) REFERENCES production_tasks (task_id) ON DELETE CASCADE,
    CONSTRAINT fk_rework_tasks_source_issue
        FOREIGN KEY (source_issue_id) REFERENCES quality_issues (issue_id) ON DELETE SET NULL,
    CONSTRAINT ck_rework_tasks_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'BLOCKED')
    )
);

CREATE INDEX idx_rework_tasks_task_id ON rework_tasks (task_id);
CREATE INDEX idx_rework_tasks_source_issue_id ON rework_tasks (source_issue_id);

CREATE TABLE delivery_records (
    delivery_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    CONSTRAINT fk_delivery_records_order
        FOREIGN KEY (order_id) REFERENCES production_orders (order_id) ON DELETE CASCADE,
    CONSTRAINT ck_delivery_records_status CHECK (
        status IN ('NOT_READY', 'READY', 'DELIVERING', 'DELIVERED', 'FAILED', 'BLOCKED')
    )
);

CREATE INDEX idx_delivery_records_order_id ON delivery_records (order_id);
