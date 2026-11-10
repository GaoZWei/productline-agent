package com.productline.business.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkReviewRequest;
import com.productline.business.api.dto.ReworkStartRequest;
import com.productline.business.api.dto.ReworkWriteReceipt;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.BusinessConflictException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.model.ReworkInspection;
import com.productline.business.domain.model.ReworkProcessingEvidence;
import com.productline.business.domain.model.ReworkProcessingSnapshot;
import com.productline.business.domain.model.ReworkRound;
import com.productline.business.domain.repository.ReworkReviewRepository;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.domain.repository.ReworkStartRepository;
import com.productline.business.domain.repository.ReworkTaskRepository;
import com.productline.business.domain.validation.ReworkTransitionPolicy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ReworkReviewService {
    private static final String OPERATION = "SUBMIT_REWORK_REVIEW";
    private final ReworkStartRepository writes;
    private final ReworkReadRepository reads;
    private final ReworkReviewRepository reviews;
    private final ReworkTaskRepository reworks;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;
    private final ReworkTransitionPolicy policy = new ReworkTransitionPolicy();

    public ReworkReviewService(ReworkStartRepository writes, ReworkReadRepository reads,
            ReworkReviewRepository reviews, ReworkTaskRepository reworks,
            ObjectMapper mapper, PlatformTransactionManager manager) {
        this.writes = writes; this.reads = reads; this.reviews = reviews; this.reworks = reworks; this.mapper = mapper;
        transaction = new TransactionTemplate(manager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    public ReworkWriteReceipt submit(String taskId, String reworkId, String actor, String role,
            String key, ReworkReviewRequest request) {
        validate(taskId, reworkId, actor, role, key);
        Objects.requireNonNull(request, "request");
        // T817只接通通过分支，合法退回结论留给T818，不提前执行问题回到OPEN。
        if (request.status() != ReviewStatus.APPROVED) throw new BusinessConflictException("non-approved rework review is not supported yet");
        String requestHash = hash(json(List.of(OPERATION, taskId, reworkId, request.expectedVersion(),
                request.processingRevision(), request.inspectionId(), request.status(), request.reviewComment())));
        return Objects.requireNonNull(transaction.execute(status -> submitInTransaction(taskId, reworkId, actor, key, request, requestHash)));
    }

    private ReworkWriteReceipt submitInTransaction(String taskId, String reworkId, String actor,
            String key, ReworkReviewRequest request, String requestHash) {
        int inserted = writes.reserve(key, OPERATION, requestHash, actor);
        var reservation = Objects.requireNonNull(writes.reservation(key));
        if (!OPERATION.equals(reservation.operation()) || !requestHash.equals(reservation.requestHash())
                || !actor.equals(reservation.actor())) throw new BusinessConflictException("idempotency key was already used for another request");
        if (inserted == 0) {
            if (!reworkId.equals(reservation.resourceId()) || reservation.version() == null) {
                throw new BusinessConflictException("original rework receipt is unavailable or still in progress");
            }
            return replay(writes.receipt(key, taskId, reworkId, actor, requestHash)
                    .orElseThrow(() -> new BusinessConflictException("original rework receipt is unavailable")), taskId, reworkId, reservation.version());
        }
        if (!writes.lockTask(taskId)) throw new ResourceNotFoundException("task", taskId);
        String owner = reads.findOwner(reworkId).orElseThrow(() -> new ResourceNotFoundException("rework", reworkId));
        if (!taskId.equals(owner)) throw new BusinessConflictException("rework task does not belong to the requested task");
        var current = reads.findDetail(taskId, reworkId).orElseThrow(() -> new IllegalStateException("rework snapshot is unavailable"));
        if (current.taskVersion() != request.expectedVersion() || current.taskVersion() >= ReworkStartRequest.MAX_SAFE_INTEGER) {
            throw new BusinessConflictException("task version is stale or cannot be incremented safely");
        }
        if (current.roundNumber() == null || current.reworkTask().sourceIssueId() == null || current.hasSuccessor()
                || current.taskStatus() != ProductionTaskStatus.COMPLETED
                || current.reworkTask().status() != ProductionTaskStatus.COMPLETED || current.issueStatus() != QualityIssueStatus.RESOLVED
                || current.processing() == null || current.processing().processingRevision() != request.processingRevision()
                || current.inspection() == null || current.inspection().result() != ReworkInspectionResult.PASSED
                || !current.inspection().inspectionId().equals(request.inspectionId())) {
            throw new BusinessConflictException("review requires a completed managed rework, resolved issue and its current passed inspection");
        }
        String issueId = current.reworkTask().sourceIssueId();
        if (!reviews.lockResolvedIssue(taskId, issueId) || !reviews.lockCompleted(taskId, reworkId)) {
            throw new BusinessConflictException("rework or source issue was modified concurrently");
        }
        long previousSequence = reviews.latestSequence(reworkId);
        if (previousSequence >= ReworkStartRequest.MAX_SAFE_INTEGER) throw new BusinessConflictException("review sequence cannot be incremented safely");
        var rework = reworks.findById(reworkId).orElseThrow(() -> new ResourceNotFoundException("rework", reworkId));
        var round = ReworkRound.from(rework, current.roundNumber());
        var material = ReworkProcessingSnapshot.recorded(rework, new ReworkProcessingEvidence(current.processing().artifact(),
                current.processing().processingComment(), current.processing().evidenceReferences()));
        var captured = current.inspection();
        var inspection = ReworkInspection.recorded(captured.inspectionId(), round, rework, material,
                captured.inspectorId(), captured.inspectedAt(), captured.items());
        ReworkTransitionPolicy.Transition proposal;
        try { proposal = policy.review(rework, round, material, inspection, request.status(), request.reviewComment()); }
        catch (IllegalArgumentException | IllegalStateException exception) { throw new BusinessConflictException("current material does not allow rework review"); }
        long nextVersion = request.expectedVersion() + 1;
        String reviewId = generatedId("REVIEW-");
        updated(writes.advanceVersion(taskId, request.expectedVersion()));
        updated(reviews.append(reviewId, reworkId, request.processingRevision(), request.inspectionId(), previousSequence + 1,
                request.status(), request.reviewComment(), actor, Instant.now()));
        // 复核通过与关闭来源问题不可分开提交；本轮完成和全部材料保留，不自动推进交付。
        updated(reviews.close(taskId, issueId));
        String operationId = generatedId("OPERATION-");
        var receipt = new ReworkWriteReceipt(OPERATION, operationId, taskId, reworkId, nextVersion,
                proposal.getAfter().reworkStatus(), proposal.getAfter().issueStatus(), current.roundNumber(), current.previousReworkTaskId(),
                request.processingRevision(), request.inspectionId(), reviewId);
        updated(writes.completeReservation(key, reworkId, nextVersion));
        String keyHash = hash(key);
        var before = auditState(reworkId, request.expectedVersion(), request.processingRevision(), request.inspectionId(),
                current.review() == null ? null : current.review().reviewId(), QualityIssueStatus.RESOLVED);
        var after = auditState(reworkId, nextVersion, request.processingRevision(), request.inspectionId(), reviewId, QualityIssueStatus.CLOSED);
        after.put("reviewStatus", request.status()); after.put("reviewComment", request.reviewComment());
        updated(writes.audit(operationId, OPERATION, taskId, actor, keyHash, json(before), json(after)));
        updated(writes.saveReceipt(key, operationId, OPERATION, requestHash, actor, taskId, reworkId,
                current.roundNumber(), nextVersion, keyHash, json(receipt)));
        return receipt;
    }

    private Map<String, Object> auditState(String reworkId, long version, long revision, String inspection, String review, QualityIssueStatus issueStatus) {
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("reworkTaskId", reworkId); state.put("taskVersion", version); state.put("processingRevision", revision);
        state.put("inspectionId", inspection); state.put("reviewId", review); state.put("status", ProductionTaskStatus.COMPLETED); state.put("issueStatus", issueStatus);
        return state;
    }

    private ReworkWriteReceipt replay(String stored, String taskId, String reworkId, long version) {
        try {
            var receipt = mapper.readerFor(ReworkWriteReceipt.class).with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).<ReworkWriteReceipt>readValue(stored);
            if (!OPERATION.equals(receipt.operation()) || !taskId.equals(receipt.taskId())
                    || !reworkId.equals(receipt.reworkTaskId()) || receipt.taskVersion() != version) {
                throw new IllegalStateException("stored rework receipt has an invalid binding");
            }
            return receipt;
        } catch (JsonProcessingException exception) { throw new IllegalStateException("stored rework receipt is invalid"); }
    }

    private void validate(String taskId, String reworkId, String actor, String role, String key) {
        if (actor == null || actor.isBlank()) throw new AuthenticationRequiredException("authenticated user is required");
        if (actor.length() > 128 || actor.indexOf('\r') >= 0 || actor.indexOf('\n') >= 0 || actor.indexOf('\0') >= 0
                || !StandardCharsets.UTF_8.newEncoder().canEncode(actor)) throw new InvalidRequestException("X-User-Id must contain 1 to 128 safe characters");
        if (!"REVIEWER".equals(role)) throw new PermissionDeniedException("REVIEWER role is required");
        if (taskId == null || taskId.length() > 64 || !taskId.matches("TASK-[A-Z0-9][A-Z0-9-]*")
                || reworkId == null || reworkId.length() > 64 || !reworkId.matches("[A-Z]+-[A-Z0-9][A-Z0-9-]*")) throw new InvalidRequestException("resource identifier is invalid");
        if (key == null || !key.matches("[A-Za-z0-9._:-]{1,128}")) throw new InvalidRequestException("Idempotency-Key must contain 1 to 128 safe characters");
    }

    private String generatedId(String prefix) { return prefix + UUID.randomUUID().toString().toUpperCase(Locale.ROOT); }
    private void updated(int count) { if (count != 1) throw new BusinessConflictException("rework was modified concurrently"); }
    private String json(Object value) {
        try { return mapper.writeValueAsString(value); }
        catch (JsonProcessingException exception) { throw new IllegalStateException("failed to serialize rework state"); }
    }
    private String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException exception) { throw new IllegalStateException("SHA-256 is unavailable", exception); }
    }
}
