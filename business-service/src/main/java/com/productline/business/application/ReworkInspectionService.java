package com.productline.business.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkInspectionRequest;
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
import com.productline.business.domain.model.ReworkInspection;
import com.productline.business.domain.model.ReworkProcessingEvidence;
import com.productline.business.domain.model.ReworkProcessingSnapshot;
import com.productline.business.domain.model.ReworkRound;
import com.productline.business.domain.repository.ReworkInspectionRepository;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.domain.repository.ReworkResultRepository;
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
public class ReworkInspectionService {
    private static final String OPERATION = "REGISTER_REWORK_INSPECTION";
    private final ReworkStartRepository writes;
    private final ReworkResultRepository results;
    private final ReworkReadRepository reads;
    private final ReworkInspectionRepository inspections;
    private final ReworkTaskRepository reworks;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;
    private final ReworkTransitionPolicy policy = new ReworkTransitionPolicy();

    public ReworkInspectionService(ReworkStartRepository writes, ReworkResultRepository results,
            ReworkReadRepository reads, ReworkInspectionRepository inspections, ReworkTaskRepository reworks,
            ObjectMapper mapper, PlatformTransactionManager transactionManager) {
        this.writes = writes; this.results = results; this.reads = reads; this.inspections = inspections;
        this.reworks = reworks; this.mapper = mapper;
        transaction = new TransactionTemplate(transactionManager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    public ReworkWriteReceipt register(String taskId, String reworkId, String actor, String role,
            String key, ReworkInspectionRequest request) {
        validate(taskId, reworkId, actor, role, key);
        Objects.requireNonNull(request, "request");
        String requestHash = hash(json(List.of(OPERATION, taskId, reworkId, request.expectedVersion(),
                request.processingRevision(), request.items())));
        return Objects.requireNonNull(transaction.execute(status ->
                registerInTransaction(taskId, reworkId, actor, key, request, requestHash)));
    }

    private ReworkWriteReceipt registerInTransaction(String taskId, String reworkId, String actor,
            String key, ReworkInspectionRequest request, String requestHash) {
        int inserted = writes.reserve(key, OPERATION, requestHash, actor);
        var reservation = Objects.requireNonNull(writes.reservation(key));
        if (!OPERATION.equals(reservation.operation()) || !requestHash.equals(reservation.requestHash())
                || !actor.equals(reservation.actor())) throw new BusinessConflictException("idempotency key was already used for another request");
        if (inserted == 0) {
            if (!reworkId.equals(reservation.resourceId()) || reservation.version() == null) {
                throw new BusinessConflictException("original rework receipt is unavailable or still in progress");
            }
            return replay(writes.receipt(key, taskId, reworkId, actor, requestHash)
                    .orElseThrow(() -> new BusinessConflictException("original rework receipt is unavailable")),
                    taskId, reworkId, reservation.version());
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
                || current.reworkTask().status() != ProductionTaskStatus.RUNNING
                || current.issueStatus() != QualityIssueStatus.PROCESSING
                || current.processing() == null || current.processing().processingRevision() != request.processingRevision()) {
            throw new BusinessConflictException("inspection requires a running managed rework and its current processing revision");
        }
        if (!writes.lockProcessingIssue(taskId, current.reworkTask().sourceIssueId()) || !results.lockRunning(taskId, reworkId)) {
            throw new BusinessConflictException("rework or source issue was modified concurrently");
        }
        long previousSequence = inspections.latestSequence(reworkId);
        if (previousSequence >= ReworkStartRequest.MAX_SAFE_INTEGER) throw new BusinessConflictException("inspection sequence cannot be incremented safely");
        var rework = reworks.findById(reworkId).orElseThrow(() -> new ResourceNotFoundException("rework", reworkId));
        var round = ReworkRound.from(rework, current.roundNumber());
        var processing = current.processing();
        var material = ReworkProcessingSnapshot.recorded(rework, new ReworkProcessingEvidence(
                processing.artifact(), processing.processingComment(), processing.evidenceReferences()));
        String inspectionId = generatedId("INSPECTION-");
        var inspection = ReworkInspection.recorded(inspectionId, round, rework, material, actor, Instant.now(), request.items());
        ProductionTaskStatus reworkStatus = ProductionTaskStatus.RUNNING;
        QualityIssueStatus issueStatus = QualityIssueStatus.PROCESSING;
        if (inspection.getResult() == ReworkInspectionResult.PASSED) {
            var proposal = policy.complete(rework, round, material, inspection);
            reworkStatus = proposal.getAfter().reworkStatus(); issueStatus = proposal.getAfter().issueStatus();
        }
        long nextVersion = request.expectedVersion() + 1;
        updated(writes.advanceVersion(taskId, request.expectedVersion()));
        updated(inspections.append(inspection, request.processingRevision(), previousSequence + 1, json(request.items())));
        // 已通过检查不能单独提交；检查记录与本轮完成、问题待复核必须一起成功或回滚。
        if (inspection.getResult() == ReworkInspectionResult.PASSED) {
            updated(inspections.complete(taskId, reworkId));
            updated(inspections.resolve(taskId, current.reworkTask().sourceIssueId()));
        }
        String operationId = generatedId("OPERATION-");
        var receipt = new ReworkWriteReceipt(OPERATION, operationId, taskId, reworkId, nextVersion,
                reworkStatus, issueStatus, current.roundNumber(), current.previousReworkTaskId(),
                request.processingRevision(), inspectionId, null);
        updated(writes.completeReservation(key, reworkId, nextVersion));
        String keyHash = hash(key);
        updated(writes.audit(operationId, OPERATION, taskId, actor, keyHash,
                json(auditState(reworkId, request.expectedVersion(), request.processingRevision(),
                        current.inspection() == null ? null : current.inspection().inspectionId(),
                        ProductionTaskStatus.RUNNING, QualityIssueStatus.PROCESSING)),
                json(auditState(reworkId, nextVersion, request.processingRevision(), inspectionId, reworkStatus, issueStatus))));
        updated(writes.saveReceipt(key, operationId, OPERATION, requestHash, actor, taskId, reworkId,
                current.roundNumber(), nextVersion, keyHash, json(receipt)));
        return receipt;
    }

    private Map<String, Object> auditState(String reworkId, long version, long revision, String inspectionId,
            ProductionTaskStatus reworkStatus, QualityIssueStatus issueStatus) {
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("reworkTaskId", reworkId); state.put("taskVersion", version); state.put("processingRevision", revision);
        state.put("inspectionId", inspectionId); state.put("status", reworkStatus); state.put("issueStatus", issueStatus);
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
