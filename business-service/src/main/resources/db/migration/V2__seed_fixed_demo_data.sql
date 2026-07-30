-- M0.3 fixed demo baseline. Keep IDs and states stable because later Java APIs and
-- Python Tools use them as contract fixtures.
INSERT INTO production_orders (order_id, product_type, status)
VALUES
    ('ORDER-001', 'DOM', 'PRODUCING'),
    ('ORDER-002', 'DOM', 'BLOCKED'),
    ('ORDER-003', 'DOM', 'QUALITY_CHECKING'),
    ('ORDER-004', 'DOM', 'REVIEWING'),
    ('ORDER-005', 'DOM', 'READY_FOR_DELIVERY');

INSERT INTO production_tasks (task_id, order_id, status)
VALUES
    ('TASK-001', 'ORDER-001', 'RUNNING'),
    ('TASK-002', 'ORDER-002', 'FAILED'),
    ('TASK-003', 'ORDER-003', 'COMPLETED'),
    ('TASK-004', 'ORDER-004', 'COMPLETED'),
    ('TASK-005', 'ORDER-005', 'COMPLETED');

INSERT INTO production_steps (step_id, task_id, step_name, sequence_number, status)
VALUES
    ('STEP-001-01', 'TASK-001', '影像预处理', 1, 'RUNNING'),
    ('STEP-002-01', 'TASK-002', '影像预处理', 1, 'FAILED'),
    ('STEP-003-01', 'TASK-003', 'DOM 生产处理', 1, 'COMPLETED'),
    ('STEP-004-01', 'TASK-004', 'DOM 生产处理', 1, 'COMPLETED'),
    ('STEP-005-01', 'TASK-005', 'DOM 生产处理', 1, 'COMPLETED');

INSERT INTO quality_issues (issue_id, task_id, issue_type, status, description)
VALUES
    (
        'ISSUE-001',
        'TASK-003',
        'COORDINATE_SYSTEM',
        'OPEN',
        '成果坐标系与生产规范要求不一致，问题尚未处理。'
    ),
    (
        'ISSUE-002',
        'TASK-004',
        'COORDINATE_SYSTEM',
        'RESOLVED',
        '坐标系问题已处理，等待复核确认。'
    ),
    (
        'ISSUE-003',
        'TASK-005',
        'COORDINATE_SYSTEM',
        'CLOSED',
        '坐标系问题已处理并通过复核。'
    );

INSERT INTO review_records (review_id, issue_id, status, review_comment)
VALUES
    ('REVIEW-003', 'ISSUE-001', 'PENDING', NULL),
    ('REVIEW-004', 'ISSUE-002', 'PENDING', '问题已处理，等待复核。'),
    ('REVIEW-005', 'ISSUE-003', 'APPROVED', '复核通过。');

INSERT INTO delivery_records (delivery_id, order_id, status)
VALUES
    ('DELIVERY-001', 'ORDER-001', 'NOT_READY'),
    ('DELIVERY-002', 'ORDER-002', 'NOT_READY'),
    ('DELIVERY-003', 'ORDER-003', 'BLOCKED'),
    ('DELIVERY-004', 'ORDER-004', 'BLOCKED'),
    ('DELIVERY-005', 'ORDER-005', 'READY');
