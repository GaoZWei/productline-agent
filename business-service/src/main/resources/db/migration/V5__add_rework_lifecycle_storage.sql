-- 只增加存储及完整性约束，不为存量返工补轮次、材料或业务状态。
CREATE FUNCTION rework_utf16_length(value TEXT) RETURNS INTEGER
LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT char_length(value) + count(*)::INTEGER
    FROM regexp_split_to_table(value, '') AS characters(ch)
    WHERE ascii(ch) > 65535
$$;

CREATE FUNCTION rework_valid_text(value TEXT, maximum INTEGER, trimmed BOOLEAN) RETURNS BOOLEAN
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $$
    WITH whitespace(chars) AS (
        VALUES (E' \t\n\r\f' || U&'\000B\001C\001D\001E\001F\1680\2000\2001\2002\2003\2004\2005\2006\2008\2009\200A\2028\2029\205F\3000')
    )
    SELECT COALESCE(rework_utf16_length(value) BETWEEN 1 AND maximum
        AND btrim(value, chars) <> ''
        AND (NOT trimmed OR value = btrim(value, chars)), FALSE)
    FROM whitespace
$$;

CREATE FUNCTION rework_valid_references(refs JSONB) RETURNS BOOLEAN
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN jsonb_typeof(refs) = 'array' THEN
        jsonb_array_length(refs) BETWEEN 1 AND 20
        AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(refs) AS entries(reference)
            WHERE NOT COALESCE(jsonb_typeof(reference) = 'string'
                AND rework_valid_text(reference #>> '{}', 1024, TRUE), FALSE)
        ) ELSE FALSE END
$$;

CREATE FUNCTION rework_valid_inspection_item(item JSONB) RETURNS BOOLEAN
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN jsonb_typeof(item) = 'object' THEN
        item ?& ARRAY['checkItem', 'result', 'comment', 'evidenceReferences']
        AND item - ARRAY['checkItem', 'result', 'comment', 'evidenceReferences'] = '{}'::jsonb
        AND jsonb_typeof(item->'checkItem') = 'string'
        AND rework_valid_text(item->>'checkItem', 128, FALSE)
        AND jsonb_typeof(item->'result') = 'string' AND item->>'result' IN ('PASSED', 'FAILED')
        AND jsonb_typeof(item->'comment') = 'string'
        AND rework_valid_text(item->>'comment', 1000, FALSE)
        AND rework_valid_references(item->'evidenceReferences')
        ELSE FALSE END
$$;

CREATE FUNCTION rework_valid_inspection_items(items JSONB, result TEXT) RETURNS BOOLEAN
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN jsonb_typeof(items) = 'array' THEN
        jsonb_array_length(items) BETWEEN 1 AND 50
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(items) AS entries(item)
            WHERE NOT COALESCE(rework_valid_inspection_item(item), FALSE))
        AND result = CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(items) AS entries(item)
            WHERE item->>'result' = 'FAILED') THEN 'FAILED' ELSE 'PASSED' END
        ELSE FALSE END
$$;

-- 复合外键验证归属；这些唯一键只使用原有主键及短字段，不改变旧行内容。
ALTER TABLE quality_issues ADD CONSTRAINT uq_quality_issue_task UNIQUE (issue_id, task_id);
ALTER TABLE rework_tasks ADD CONSTRAINT uq_rework_task_issue UNIQUE (rework_task_id, task_id, source_issue_id);

CREATE TABLE rework_lifecycles (
    rework_task_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    source_issue_id VARCHAR(64) NOT NULL,
    round_number BIGINT NOT NULL CHECK (round_number BETWEEN 1 AND 9007199254740991),
    previous_rework_task_id VARCHAR(64),
    previous_round_number BIGINT,
    creation_sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    created_by VARCHAR(128) NOT NULL CHECK (rework_valid_text(created_by, 128, FALSE)),
    created_at TIMESTAMPTZ NOT NULL,
    started_by VARCHAR(128),
    started_at TIMESTAMPTZ,
    CONSTRAINT fk_rework_lifecycle_task_issue FOREIGN KEY (rework_task_id, task_id, source_issue_id)
        REFERENCES rework_tasks (rework_task_id, task_id, source_issue_id),
    CONSTRAINT fk_rework_lifecycle_issue_task FOREIGN KEY (source_issue_id, task_id)
        REFERENCES quality_issues (issue_id, task_id),
    CONSTRAINT uq_rework_lifecycle_round UNIQUE (task_id, source_issue_id, round_number),
    CONSTRAINT uq_rework_lifecycle_predecessor UNIQUE (previous_rework_task_id),
    CONSTRAINT uq_rework_lifecycle_scope UNIQUE (rework_task_id, task_id, source_issue_id, round_number),
    CONSTRAINT uq_rework_lifecycle_receipt_scope UNIQUE (rework_task_id, task_id, round_number),
    CONSTRAINT fk_rework_lifecycle_previous FOREIGN KEY (previous_rework_task_id, task_id, source_issue_id, previous_round_number)
        REFERENCES rework_lifecycles (rework_task_id, task_id, source_issue_id, round_number),
    CONSTRAINT ck_rework_lifecycle_previous CHECK (
        (round_number = 1 AND previous_rework_task_id IS NULL AND previous_round_number IS NULL)
        OR (round_number > 1 AND previous_rework_task_id IS NOT NULL AND previous_round_number IS NOT NULL
            AND previous_round_number = round_number - 1)
    ),
    CONSTRAINT ck_rework_lifecycle_start CHECK (
        (started_by IS NULL AND started_at IS NULL)
        OR (started_by IS NOT NULL AND started_at IS NOT NULL AND rework_valid_text(started_by, 128, FALSE))
    )
);
CREATE INDEX idx_rework_lifecycle_task_creation ON rework_lifecycles (task_id, creation_sequence);

CREATE TABLE rework_processing_revisions (
    rework_task_id VARCHAR(64) NOT NULL REFERENCES rework_lifecycles (rework_task_id),
    processing_revision BIGINT NOT NULL CHECK (processing_revision BETWEEN 1 AND 9007199254740991),
    artifact_id TEXT NOT NULL CHECK (rework_valid_text(artifact_id, 256, TRUE)),
    artifact_version TEXT NOT NULL CHECK (rework_valid_text(artifact_version, 128, TRUE)),
    processing_comment TEXT NOT NULL CHECK (rework_valid_text(processing_comment, 1000, FALSE)),
    evidence_references JSONB NOT NULL CHECK (rework_valid_references(evidence_references)),
    registered_by VARCHAR(128) NOT NULL CHECK (rework_valid_text(registered_by, 128, FALSE)),
    registered_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (rework_task_id, processing_revision)
);

CREATE TABLE rework_inspections (
    inspection_id VARCHAR(64) PRIMARY KEY,
    rework_task_id VARCHAR(64) NOT NULL,
    processing_revision BIGINT NOT NULL,
    inspection_sequence BIGINT NOT NULL CHECK (inspection_sequence BETWEEN 1 AND 9007199254740991),
    result VARCHAR(16) NOT NULL CHECK (result IN ('PASSED', 'FAILED')),
    items JSONB NOT NULL CHECK (COALESCE(rework_valid_inspection_items(items, result), FALSE)),
    inspector_id VARCHAR(128) NOT NULL CHECK (rework_valid_text(inspector_id, 128, FALSE)),
    inspected_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_rework_inspection_revision FOREIGN KEY (rework_task_id, processing_revision)
        REFERENCES rework_processing_revisions (rework_task_id, processing_revision),
    CONSTRAINT uq_rework_inspection_sequence UNIQUE (rework_task_id, inspection_sequence),
    CONSTRAINT uq_rework_inspection_binding UNIQUE (inspection_id, rework_task_id, processing_revision, result)
);
CREATE INDEX idx_rework_inspection_current ON rework_inspections (rework_task_id, processing_revision, inspection_sequence DESC);

CREATE TABLE rework_reviews (
    review_id VARCHAR(64) PRIMARY KEY,
    rework_task_id VARCHAR(64) NOT NULL,
    processing_revision BIGINT NOT NULL,
    inspection_id VARCHAR(64) NOT NULL,
    inspection_result VARCHAR(16) NOT NULL DEFAULT 'PASSED' CHECK (inspection_result = 'PASSED'),
    review_sequence BIGINT NOT NULL CHECK (review_sequence BETWEEN 1 AND 9007199254740991),
    status VARCHAR(32) NOT NULL CHECK (status IN ('APPROVED', 'REJECTED', 'REWORK_REQUIRED')),
    review_comment TEXT NOT NULL CHECK (rework_valid_text(review_comment, 1000, FALSE)),
    reviewed_by VARCHAR(128) NOT NULL CHECK (rework_valid_text(reviewed_by, 128, FALSE)),
    reviewed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_rework_review_passed_inspection FOREIGN KEY (inspection_id, rework_task_id, processing_revision, inspection_result)
        REFERENCES rework_inspections (inspection_id, rework_task_id, processing_revision, result),
    CONSTRAINT uq_rework_review_sequence UNIQUE (rework_task_id, review_sequence)
);
CREATE INDEX idx_rework_review_current ON rework_reviews (rework_task_id, processing_revision, inspection_id, review_sequence DESC);

-- 保留旧操作，新写服务启用后才会使用扩展值；旧行和旧Java实体字段保持不变。
ALTER TABLE idempotency_records DROP CONSTRAINT ck_idempotency_operation_type;
ALTER TABLE idempotency_records ADD CONSTRAINT ck_idempotency_operation_type CHECK (
    operation_type IN ('SUBMIT_REVIEW', 'CREATE_REWORK', 'CREATE_LIFECYCLE_REWORK', 'START_REWORK',
        'BLOCK_REWORK', 'FAIL_REWORK', 'RESUME_REWORK', 'REGISTER_REWORK_RESULT',
        'REGISTER_REWORK_INSPECTION', 'SUBMIT_REWORK_REVIEW', 'CREATE_NEXT_REWORK')
);
ALTER TABLE operation_logs DROP CONSTRAINT ck_operation_logs_operation_type;
ALTER TABLE operation_logs ADD CONSTRAINT ck_operation_logs_operation_type CHECK (
    operation_type IN ('SUBMIT_REVIEW', 'CREATE_REWORK', 'CREATE_LIFECYCLE_REWORK', 'START_REWORK',
        'BLOCK_REWORK', 'FAIL_REWORK', 'RESUME_REWORK', 'REGISTER_REWORK_RESULT',
        'REGISTER_REWORK_INSPECTION', 'SUBMIT_REWORK_REVIEW', 'CREATE_NEXT_REWORK')
);
ALTER TABLE idempotency_records ADD CONSTRAINT uq_rework_idempotency_binding
    UNIQUE (idempotency_key, operation_type, request_hash, actor_user_id, resource_id, task_version_after);
ALTER TABLE operation_logs ADD CONSTRAINT uq_rework_operation_binding
    UNIQUE (operation_id, operation_type, target_type, target_id, actor_user_id, idempotency_key_hash);

CREATE TABLE rework_operation_receipts (
    idempotency_key VARCHAR(128) PRIMARY KEY CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
    operation_id VARCHAR(64) NOT NULL UNIQUE,
    operation_type VARCHAR(32) NOT NULL CHECK (operation_type IN ('CREATE_LIFECYCLE_REWORK', 'START_REWORK',
        'BLOCK_REWORK', 'FAIL_REWORK', 'RESUME_REWORK', 'REGISTER_REWORK_RESULT',
        'REGISTER_REWORK_INSPECTION', 'SUBMIT_REWORK_REVIEW', 'CREATE_NEXT_REWORK')),
    request_hash VARCHAR(64) NOT NULL CHECK (request_hash ~ '^[a-f0-9]{64}$'),
    actor_user_id VARCHAR(128) NOT NULL CHECK (rework_valid_text(actor_user_id, 128, FALSE)),
    task_id VARCHAR(64) NOT NULL,
    rework_task_id VARCHAR(64) NOT NULL,
    round_number BIGINT NOT NULL,
    task_version_after BIGINT NOT NULL CHECK (task_version_after BETWEEN 1 AND 9007199254740991),
    idempotency_key_hash VARCHAR(64) NOT NULL CHECK (idempotency_key_hash = encode(sha256(convert_to(idempotency_key, 'UTF8')), 'hex')),
    target_type VARCHAR(32) NOT NULL DEFAULT 'PRODUCTION_TASK' CHECK (target_type = 'PRODUCTION_TASK'),
    response_data JSONB NOT NULL,
    CONSTRAINT fk_rework_receipt_lifecycle FOREIGN KEY (rework_task_id, task_id, round_number)
        REFERENCES rework_lifecycles (rework_task_id, task_id, round_number),
    CONSTRAINT fk_rework_receipt_idempotency FOREIGN KEY (idempotency_key, operation_type, request_hash, actor_user_id, rework_task_id, task_version_after)
        REFERENCES idempotency_records (idempotency_key, operation_type, request_hash, actor_user_id, resource_id, task_version_after)
        DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT fk_rework_receipt_audit FOREIGN KEY (operation_id, operation_type, target_type, task_id, actor_user_id, idempotency_key_hash)
        REFERENCES operation_logs (operation_id, operation_type, target_type, target_id, actor_user_id, idempotency_key_hash)
        DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT ck_rework_receipt_response CHECK (COALESCE(
        jsonb_typeof(response_data) = 'object'
        AND response_data ?& ARRAY['operation','operationId','taskId','reworkTaskId','taskVersion','status','issueStatus',
            'roundNumber','previousReworkTaskId','processingRevision','inspectionId','reviewId']
        AND response_data - ARRAY['operation','operationId','taskId','reworkTaskId','taskVersion','status','issueStatus',
            'roundNumber','previousReworkTaskId','processingRevision','inspectionId','reviewId'] = '{}'::jsonb
        AND response_data->>'operation' = operation_type
        AND response_data->>'operationId' = operation_id
        AND response_data->>'taskId' = task_id AND response_data->>'reworkTaskId' = rework_task_id
        AND response_data->'taskVersion' = to_jsonb(task_version_after)
        AND response_data->'roundNumber' = to_jsonb(round_number)
        AND response_data->>'status' IN ('PENDING','RUNNING','COMPLETED','FAILED','BLOCKED')
        AND response_data->>'issueStatus' IN ('OPEN','PROCESSING','RESOLVED','CLOSED'), FALSE))
);
CREATE INDEX idx_rework_receipt_owner ON rework_operation_receipts (actor_user_id, task_id, idempotency_key);

-- 历史与原始成功回执追加后不可改写，回滚不受此限制；不通过级联删除丢失证据。
CREATE FUNCTION rework_reject_history_mutation() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'rework history is append-only' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER rework_processing_append_only BEFORE UPDATE OR DELETE ON rework_processing_revisions
    FOR EACH ROW EXECUTE FUNCTION rework_reject_history_mutation();
CREATE TRIGGER rework_inspection_append_only BEFORE UPDATE OR DELETE ON rework_inspections
    FOR EACH ROW EXECUTE FUNCTION rework_reject_history_mutation();
CREATE TRIGGER rework_review_append_only BEFORE UPDATE OR DELETE ON rework_reviews
    FOR EACH ROW EXECUTE FUNCTION rework_reject_history_mutation();
CREATE TRIGGER rework_receipt_append_only BEFORE UPDATE OR DELETE ON rework_operation_receipts
    FOR EACH ROW EXECUTE FUNCTION rework_reject_history_mutation();

CREATE FUNCTION rework_protect_lifecycle_identity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'rework lifecycle identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.rework_task_id,NEW.task_id,NEW.source_issue_id,NEW.round_number,NEW.previous_rework_task_id,
        NEW.previous_round_number,NEW.creation_sequence,NEW.created_by,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.rework_task_id,OLD.task_id,OLD.source_issue_id,OLD.round_number,OLD.previous_rework_task_id,
        OLD.previous_round_number,OLD.creation_sequence,OLD.created_by,OLD.created_at)
        OR (OLD.started_at IS NOT NULL AND ROW(NEW.started_by,NEW.started_at) IS DISTINCT FROM ROW(OLD.started_by,OLD.started_at)) THEN
        RAISE EXCEPTION 'rework lifecycle identity is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER rework_lifecycle_identity_immutable BEFORE UPDATE OR DELETE ON rework_lifecycles
    FOR EACH ROW EXECUTE FUNCTION rework_protect_lifecycle_identity();
