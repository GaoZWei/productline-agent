package com.productline.business.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkResultRequest;
import com.productline.business.api.dto.ReworkStartRequest;
import com.productline.business.api.dto.ReworkWriteReceipt;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.BusinessConflictException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.domain.repository.ReworkResultRepository;
import com.productline.business.domain.repository.ReworkStartRepository;
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
public class ReworkResultService {
    private static final String OPERATION = "REGISTER_REWORK_RESULT";
    private final ReworkStartRepository writes;
    private final ReworkResultRepository results;
    private final ReworkReadRepository reads;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;

    public ReworkResultService(ReworkStartRepository writes, ReworkResultRepository results,
            ReworkReadRepository reads, ObjectMapper mapper, PlatformTransactionManager transactionManager) {
        this.writes = writes; this.results = results; this.reads = reads; this.mapper = mapper;
        transaction = new TransactionTemplate(transactionManager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    public ReworkWriteReceipt register(String taskId, String reworkId, String actor, String role,
            String key, ReworkResultRequest request) {
        validate(taskId, reworkId, actor, role, key);
        Objects.requireNonNull(request, "request");
        String requestHash = hash(json(List.of(OPERATION, taskId, reworkId, request.expectedVersion(),
                request.artifact().artifactId(), request.artifact().artifactVersion(),
                request.processingComment(), request.evidenceReferences())));
        return Objects.requireNonNull(transaction.execute(status ->
                registerInTransaction(taskId, reworkId, actor, key, request, requestHash)));
    }

    private ReworkWriteReceipt registerInTransaction(String taskId, String reworkId, String actor,
            String key, ReworkResultRequest request, String requestHash) {
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
                || current.issueStatus() != QualityIssueStatus.PROCESSING) {
            throw new BusinessConflictException("current task, rework or issue state does not allow result registration");
        }
        // 锁住本轮及来源状态至提交，材料登记不能在并发结束/关闭后落入旧轮。
        if (!writes.lockProcessingIssue(taskId, current.reworkTask().sourceIssueId()) || !results.lockRunning(taskId, reworkId)) {
            throw new BusinessConflictException("rework or source issue was modified concurrently");
        }
        long latest = results.latestRevision(reworkId);
        if (latest >= ReworkStartRequest.MAX_SAFE_INTEGER) throw new BusinessConflictException("processing revision cannot be incremented safely");
        long revision = latest + 1;
        long nextVersion = request.expectedVersion() + 1;
        updated(writes.advanceVersion(taskId, request.expectedVersion()));
        updated(results.append(reworkId, revision, request.artifact().artifactId(), request.artifact().artifactVersion(),
                request.processingComment(), json(request.evidenceReferences()), actor, Instant.now()));
        String operationId = "OPERATION-" + UUID.randomUUID().toString().toUpperCase(Locale.ROOT);
        // 新修订没有检查或复核；相同成果版本文本也不能沿用旧材料的结论。
        var receipt = new ReworkWriteReceipt(OPERATION, operationId, taskId, reworkId, nextVersion,
                ProductionTaskStatus.RUNNING, QualityIssueStatus.PROCESSING, current.roundNumber(),
                current.previousReworkTaskId(), revision, null, null);
        updated(writes.completeReservation(key, reworkId, nextVersion));
        String keyHash = hash(key);
        writes.audit(operationId, OPERATION, taskId, actor, keyHash,
                json(auditState(taskId, reworkId, request.expectedVersion(), latest == 0 ? null : latest)),
                json(auditState(taskId, reworkId, nextVersion, revision)));
        writes.saveReceipt(key, operationId, OPERATION, requestHash, actor, taskId, reworkId,
                current.roundNumber(), nextVersion, keyHash, json(receipt));
        return receipt;
    }

    private Map<String, Object> auditState(String taskId, String reworkId, long version, Long revision) {
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("taskId", taskId); state.put("reworkTaskId", reworkId); state.put("taskVersion", version);
        state.put("status", "RUNNING"); state.put("issueStatus", "PROCESSING"); state.put("processingRevision", revision);
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
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored rework receipt is invalid");
        }
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

    private void updated(int count) {
        if (count != 1) throw new BusinessConflictException("rework was modified concurrently");
    }

    private String json(Object value) {
        try { return mapper.writeValueAsString(value); }
        catch (JsonProcessingException exception) { throw new IllegalStateException("failed to serialize rework state"); }
    }

    private String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException exception) { throw new IllegalStateException("SHA-256 is unavailable", exception); }
    }
}
