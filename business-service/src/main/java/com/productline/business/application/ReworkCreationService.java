package com.productline.business.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkInterruptionRequest;
import com.productline.business.api.dto.ReworkLifecycleCreationRequest;
import com.productline.business.api.dto.ReworkStartRequest;
import com.productline.business.api.dto.ReworkWriteReceipt;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.BusinessConflictException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.dto.ReworkLifecycleSnapshot;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.repository.ReworkCreationRepository;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.domain.repository.ReworkStartRepository;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** 首轮与后继轮独立创建；不开始处理、不继承旧材料，也不替代Python人工确认。 */
@Service
public class ReworkCreationService {
    private static final String FIRST = "CREATE_LIFECYCLE_REWORK";
    private static final String NEXT = "CREATE_NEXT_REWORK";
    private final ReworkCreationRepository creates;
    private final ReworkStartRepository writes;
    private final ReworkReadRepository reads;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;

    public ReworkCreationService(ReworkCreationRepository creates, ReworkStartRepository writes,
            ReworkReadRepository reads, ObjectMapper mapper, PlatformTransactionManager manager) {
        this.creates = creates;
        this.writes = writes;
        this.reads = reads;
        this.mapper = mapper;
        transaction = new TransactionTemplate(manager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    public ReworkWriteReceipt first(String taskId, String actor, String role, String key,
            ReworkLifecycleCreationRequest request) {
        Objects.requireNonNull(request, "request");
        return create(taskId, request.sourceIssueId(), actor, role, key, FIRST, request.expectedVersion(), request.reason());
    }

    public ReworkWriteReceipt next(String taskId, String previousId, String actor, String role, String key,
            ReworkInterruptionRequest request) {
        Objects.requireNonNull(request, "request");
        return create(taskId, previousId, actor, role, key, NEXT, request.expectedVersion(), request.reason());
    }

    private ReworkWriteReceipt create(String taskId, String targetId, String actor, String role, String key,
            String operation, long version, String reason) {
        validate(taskId, targetId, actor, role, key);
        String requestHash = hash(json(List.of(operation, taskId, targetId, version, reason)));
        return Objects.requireNonNull(transaction.execute(status ->
                createInTransaction(taskId, targetId, actor, key, operation, version, reason, requestHash)));
    }

    private ReworkWriteReceipt createInTransaction(String taskId, String targetId, String actor, String key,
            String operation, long version, String reason, String requestHash) {
        int inserted = writes.reserve(key, operation, requestHash, actor);
        var reserved = Objects.requireNonNull(writes.reservation(key));
        if (!operation.equals(reserved.operation()) || !requestHash.equals(reserved.requestHash())
                || !actor.equals(reserved.actor())) {
            throw new BusinessConflictException("idempotency key was already used for another request");
        }
        if (inserted == 0) {
            if (reserved.resourceId() == null || reserved.version() == null) {
                throw new BusinessConflictException("original rework receipt is unavailable or still in progress");
            }
            String stored = writes.receipt(key, taskId, reserved.resourceId(), actor, requestHash)
                    .orElseThrow(() -> new BusinessConflictException("original rework receipt is unavailable"));
            return replay(stored, operation, taskId, reserved.resourceId(), reserved.version());
        }
        if (!writes.lockTask(taskId)) throw new ResourceNotFoundException("task", taskId);
        var task = creates.task(taskId);
        if (task.status() != ProductionTaskStatus.COMPLETED || task.version() != version
                || version >= ReworkStartRequest.MAX_SAFE_INTEGER) {
            throw new BusinessConflictException("task must be COMPLETED with a current incrementable version");
        }
        boolean next = NEXT.equals(operation);
        ReworkLifecycleSnapshot previous = next ? previous(taskId, targetId) : null;
        String issueId = next ? previous.reworkTask().sourceIssueId() : targetId;
        if (issueId == null) throw new BusinessConflictException("rework lifecycle is required");
        var issue = creates.lockIssue(issueId).orElseThrow(() -> new ResourceNotFoundException("quality issue", issueId));
        if (!taskId.equals(issue.taskId())) throw new BusinessConflictException("quality issue does not belong to the requested task");
        if (issue.status() != QualityIssueStatus.OPEN || creates.hasActive(taskId, issueId)) {
            throw new BusinessConflictException("creation requires an OPEN issue without an active rework");
        }
        if (!next && creates.hasLifecycle(taskId, issueId)) {
            throw new BusinessConflictException("controlled rework already exists; use next-round");
        }
        if (next) requireReturnedRound(taskId, targetId, previous);
        long round = next ? previous.roundNumber() + 1 : 1;
        String reworkId = generatedId("REWORK-");
        String operationId = generatedId("OPERATION-");
        long nextVersion = version + 1;
        updated(writes.advanceVersion(taskId, version));
        updated(creates.create(taskId, issueId, reworkId, reason));
        updated(creates.lifecycle(taskId, issueId, reworkId, round, next ? targetId : null, actor, Instant.now()));
        var receipt = new ReworkWriteReceipt(operation, operationId, taskId, reworkId, nextVersion,
                ProductionTaskStatus.PENDING, QualityIssueStatus.OPEN, round, next ? targetId : null, null, null, null);
        var before = new LinkedHashMap<String, Object>();
        before.put("taskVersion", version); before.put("sourceIssueId", issueId); before.put("issueStatus", issue.status());
        before.put("previousReworkTaskId", next ? targetId : null);
        if (next) {
            // 关联实际退回结论和原始意见，而不是让新原因覆盖前轮证据。
            before.put("previousReviewId", previous.review().reviewId());
            before.put("previousReviewStatus", previous.review().status());
            before.put("previousReviewComment", previous.review().reviewComment());
        }
        var after = new LinkedHashMap<String, Object>(before);
        after.put("taskVersion", nextVersion); after.put("reworkTaskId", reworkId);
        after.put("status", ProductionTaskStatus.PENDING); after.put("roundNumber", round); after.put("reason", reason);
        updated(writes.completeReservation(key, reworkId, nextVersion));
        String keyHash = hash(key);
        updated(writes.audit(operationId, operation, taskId, actor, keyHash, json(before), json(after)));
        updated(writes.saveReceipt(key, operationId, operation, requestHash, actor, taskId, reworkId,
                round, nextVersion, keyHash, json(receipt)));
        return receipt;
    }

    private ReworkLifecycleSnapshot previous(String taskId, String previousId) {
        String owner = reads.findOwner(previousId).orElseThrow(() -> new ResourceNotFoundException("rework", previousId));
        if (!taskId.equals(owner)) throw new BusinessConflictException("rework task does not belong to the requested task");
        return reads.findDetail(taskId, previousId).orElseThrow(() -> new ResourceNotFoundException("rework", previousId));
    }

    private void requireReturnedRound(String taskId, String previousId, ReworkLifecycleSnapshot previous) {
        if (previous.roundNumber() == null || previous.roundNumber() < 1
                || previous.roundNumber() >= ReworkStartRequest.MAX_SAFE_INTEGER || previous.hasSuccessor()
                || previous.reworkTask().status() != ProductionTaskStatus.COMPLETED
                || previous.issueStatus() != QualityIssueStatus.OPEN || previous.processing() == null
                || previous.inspection() == null || previous.inspection().result() != ReworkInspectionResult.PASSED
                || previous.review() == null || (previous.review().status() != ReviewStatus.REJECTED
                    && previous.review().status() != ReviewStatus.REWORK_REQUIRED)
                || !creates.lockCompleted(taskId, previousId)) {
            throw new BusinessConflictException("next round requires the current completed controlled round with an effective returned review");
        }
    }

    private ReworkWriteReceipt replay(String stored, String operation, String taskId, String reworkId, long version) {
        try {
            var receipt = mapper.readerFor(ReworkWriteReceipt.class).with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).<ReworkWriteReceipt>readValue(stored);
            if (!operation.equals(receipt.operation()) || !taskId.equals(receipt.taskId())
                    || !reworkId.equals(receipt.reworkTaskId()) || receipt.taskVersion() != version) {
                throw new IllegalStateException("stored rework receipt has an invalid binding");
            }
            return receipt;
        } catch (JsonProcessingException exception) { throw new IllegalStateException("stored rework receipt is invalid"); }
    }

    private void validate(String taskId, String targetId, String actor, String role, String key) {
        if (actor == null || actor.isBlank()) throw new AuthenticationRequiredException("authenticated user is required");
        if (actor.length() > 128 || actor.indexOf('\r') >= 0 || actor.indexOf('\n') >= 0 || actor.indexOf('\0') >= 0
                || !StandardCharsets.UTF_8.newEncoder().canEncode(actor)) {
            throw new InvalidRequestException("X-User-Id must contain 1 to 128 safe characters");
        }
        if (!"REVIEWER".equals(role)) throw new PermissionDeniedException("REVIEWER role is required");
        if (taskId == null || taskId.length() > 64 || !taskId.matches("TASK-[A-Z0-9][A-Z0-9-]*")
                || targetId == null || targetId.length() > 64 || !targetId.matches("[A-Z]+-[A-Z0-9][A-Z0-9-]*")) {
            throw new InvalidRequestException("resource identifier is invalid");
        }
        if (key == null || !key.matches("[A-Za-z0-9._:-]{1,128}")) {
            throw new InvalidRequestException("Idempotency-Key must contain 1 to 128 safe characters");
        }
    }

    private void updated(int count) { if (count != 1) throw new BusinessConflictException("rework was modified concurrently"); }
    private String generatedId(String prefix) { return prefix + UUID.randomUUID().toString().toUpperCase(Locale.ROOT); }
    private String json(Object value) {
        try { return mapper.writeValueAsString(value); }
        catch (JsonProcessingException exception) { throw new IllegalStateException("failed to serialize rework state"); }
    }
    private String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException exception) { throw new IllegalStateException("SHA-256 is unavailable", exception); }
    }
}
