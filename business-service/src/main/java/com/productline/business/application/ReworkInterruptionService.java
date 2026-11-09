package com.productline.business.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkInterruptionRequest;
import com.productline.business.api.dto.ReworkWriteReceipt;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.BusinessConflictException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.model.ReworkRound;
import com.productline.business.domain.repository.ProductionTaskRepository;
import com.productline.business.domain.repository.ReworkReadRepository;
import com.productline.business.domain.repository.ReworkStartRepository;
import com.productline.business.domain.repository.ReworkTaskRepository;
import com.productline.business.domain.validation.ReworkTransitionPolicy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
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
public class ReworkInterruptionService {
    private enum Mode {
        BLOCK("BLOCK_REWORK"), FAIL("FAIL_REWORK"), RESUME("RESUME_REWORK");
        final String operation;
        Mode(String operation) { this.operation = operation; }
    }
    private final ReworkStartRepository writes;
    private final ReworkReadRepository reads;
    private final ProductionTaskRepository tasks;
    private final ReworkTaskRepository reworks;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;
    private final ReworkTransitionPolicy policy = new ReworkTransitionPolicy();

    public ReworkInterruptionService(ReworkStartRepository writes, ReworkReadRepository reads,
            ProductionTaskRepository tasks, ReworkTaskRepository reworks, ObjectMapper mapper,
            PlatformTransactionManager transactionManager) {
        this.writes = writes;
        this.reads = reads;
        this.tasks = tasks;
        this.reworks = reworks;
        this.mapper = mapper;
        transaction = new TransactionTemplate(transactionManager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    public ReworkWriteReceipt block(String taskId, String reworkId, String actor, String role,
            String key, ReworkInterruptionRequest request) {
        return transition(taskId, reworkId, actor, role, key, request, Mode.BLOCK);
    }

    public ReworkWriteReceipt fail(String taskId, String reworkId, String actor, String role,
            String key, ReworkInterruptionRequest request) {
        return transition(taskId, reworkId, actor, role, key, request, Mode.FAIL);
    }

    public ReworkWriteReceipt resume(String taskId, String reworkId, String actor, String role,
            String key, ReworkInterruptionRequest request) {
        return transition(taskId, reworkId, actor, role, key, request, Mode.RESUME);
    }

    private ReworkWriteReceipt transition(String taskId, String reworkId, String actor, String role,
            String key, ReworkInterruptionRequest request, Mode mode) {
        validate(taskId, reworkId, actor, role, key);
        Objects.requireNonNull(request, "request");
        String requestHash = hash(json(List.of(mode.operation, taskId, reworkId, request.expectedVersion(), request.reason())));
        return Objects.requireNonNull(transaction.execute(status ->
                transitionInTransaction(taskId, reworkId, actor, key, request, requestHash, mode)));
    }

    private ReworkWriteReceipt transitionInTransaction(String taskId, String reworkId, String actor,
            String key, ReworkInterruptionRequest request, String requestHash, Mode mode) {
        String operation = mode.operation;
        int inserted = writes.reserve(key, operation, requestHash, actor);
        var reserved = Objects.requireNonNull(writes.reservation(key));
        if (!operation.equals(reserved.operation()) || !requestHash.equals(reserved.requestHash())
                || !actor.equals(reserved.actor())) {
            throw new BusinessConflictException("idempotency key was already used for another request");
        }
        if (inserted == 0) {
            if (!reworkId.equals(reserved.resourceId()) || reserved.version() == null) {
                throw new BusinessConflictException("original rework receipt is unavailable or still in progress");
            }
            // 重放只读首次回执，不能因后来的状态或任务版本改变而再次写入。
            String stored = writes.receipt(key, taskId, reworkId, actor, requestHash)
                    .orElseThrow(() -> new BusinessConflictException("original rework receipt is unavailable"));
            return replay(stored, taskId, reworkId, reserved.version(), operation);
        }
        // 全部同任务操作共用版本；先锁父任务，再重新读取状态并执行CAS。
        if (!writes.lockTask(taskId)) throw new ResourceNotFoundException("task", taskId);
        var task = tasks.findById(taskId).orElseThrow(() -> new ResourceNotFoundException("task", taskId));
        var rework = reworks.findById(reworkId).orElseThrow(() -> new ResourceNotFoundException("rework", reworkId));
        if (!taskId.equals(rework.getTask().getTaskId())) {
            throw new BusinessConflictException("rework task does not belong to the requested task");
        }
        if (task.getVersion() != request.expectedVersion() || task.getVersion() >= ReworkInterruptionRequest.MAX_SAFE_INTEGER) {
            throw new BusinessConflictException("task version is stale or cannot be incremented safely");
        }
        if (rework.getSourceIssue() == null) throw new BusinessConflictException("rework lifecycle is required");
        String issueId = rework.getSourceIssue().getIssueId();
        var lifecycle = writes.lifecycle(taskId, reworkId, issueId)
                .orElseThrow(() -> new BusinessConflictException("rework lifecycle is required"));
        if (writes.hasSuccessor(reworkId)) {
            throw new BusinessConflictException("rework has a successor");
        }
        ReworkTransitionPolicy.Transition proposal;
        try {
            ReworkRound round = ReworkRound.from(rework, lifecycle.roundNumber());
            proposal = switch (mode) {
                case BLOCK -> policy.block(rework, round, request.reason());
                case FAIL -> policy.fail(rework, round, request.reason());
                case RESUME -> policy.resume(rework, round, request.reason());
            };
        } catch (IllegalArgumentException | IllegalStateException exception) {
            throw new BusinessConflictException("current task, rework or issue state does not allow interruption");
        }
        long nextVersion = request.expectedVersion() + 1;
        updated(writes.advanceVersion(taskId, request.expectedVersion()));
        if (!writes.lockProcessingIssue(taskId, issueId)) {
            throw new BusinessConflictException("source issue was modified concurrently");
        }
        // 恢复须仍匹配刚复查的BLOCKED/FAILED，不能把一次旧恢复意图作用到别的状态。
        updated(mode == Mode.RESUME
                ? writes.markResumed(taskId, reworkId, proposal.getBefore().reworkStatus())
                : writes.markInterrupted(taskId, reworkId, proposal.getAfter().reworkStatus()));
        var current = reads.findDetail(taskId, reworkId)
                .orElseThrow(() -> new IllegalStateException("interrupted rework snapshot is unavailable"));
        String operationId = "OPERATION-" + UUID.randomUUID().toString().toUpperCase(Locale.ROOT);
        var receipt = new ReworkWriteReceipt(operation, operationId, taskId, reworkId, nextVersion,
                proposal.getAfter().reworkStatus(), proposal.getAfter().issueStatus(), lifecycle.roundNumber(),
                current.previousReworkTaskId(), current.processing() == null ? null : current.processing().processingRevision(),
                current.inspection() == null ? null : current.inspection().inspectionId(),
                current.review() == null ? null : current.review().reviewId());
        updated(writes.completeReservation(key, reworkId, nextVersion));
        String keyHash = hash(key);
        updated(writes.audit(operationId, operation, taskId, actor, keyHash,
                json(Map.of("taskVersion", request.expectedVersion(), "reworkTaskId", reworkId,
                        "status", proposal.getBefore().reworkStatus(), "issueStatus", proposal.getBefore().issueStatus())),
                json(Map.of("taskVersion", nextVersion, "reworkTaskId", reworkId,
                        "status", proposal.getAfter().reworkStatus(), "issueStatus", proposal.getAfter().issueStatus(),
                        "reason", proposal.getReason().orElseThrow()))));
        // 幂等完成和审计先落入同一事务，满足V5立即检查的组合外键，再保存不可变成功JSON。
        updated(writes.saveReceipt(key, operationId, operation, requestHash, actor, taskId, reworkId,
                lifecycle.roundNumber(), nextVersion, keyHash, json(receipt)));
        return receipt;
    }

    private ReworkWriteReceipt replay(String stored, String taskId, String reworkId, long version, String operation) {
        try {
            var receipt = mapper.readerFor(ReworkWriteReceipt.class)
                    .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).<ReworkWriteReceipt>readValue(stored);
            if (!operation.equals(receipt.operation()) || !taskId.equals(receipt.taskId())
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
        if (actor.length() > 128 || actor.indexOf('\r') >= 0 || actor.indexOf('\n') >= 0) {
            throw new InvalidRequestException("X-User-Id must contain 1 to 128 safe characters");
        }
        if (!"REVIEWER".equals(role)) throw new PermissionDeniedException("REVIEWER role is required");
        if (taskId == null || taskId.length() > 64 || !taskId.matches("TASK-[A-Z0-9][A-Z0-9-]*")
                || reworkId == null || reworkId.length() > 64 || !reworkId.matches("[A-Z]+-[A-Z0-9][A-Z0-9-]*")) {
            throw new InvalidRequestException("resource identifier is invalid");
        }
        if (key == null || !key.matches("[A-Za-z0-9._:-]{1,128}")) {
            throw new InvalidRequestException("Idempotency-Key must contain 1 to 128 safe characters");
        }
    }

    private void updated(int count) {
        if (count != 1) throw new BusinessConflictException("rework was modified concurrently");
    }

    private String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to serialize rework state");
        }
    }

    private String hash(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}
