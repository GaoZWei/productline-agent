package com.productline.business.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkOperationQueryRequest;
import com.productline.business.api.dto.ReworkOperationQueryResponse;
import com.productline.business.api.dto.ReworkStartRequest;
import com.productline.business.api.dto.ReworkWriteReceipt;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.repository.ReworkOperationQueryRepository;
import com.productline.business.domain.repository.ReworkOperationQueryRepository.StoredReceipt;
import com.productline.business.domain.repository.ReworkReadRepository;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ReworkOperationQueryService {
    private static final Set<String> OPERATIONS = Set.of("CREATE_LIFECYCLE_REWORK", "START_REWORK",
            "BLOCK_REWORK", "FAIL_REWORK", "RESUME_REWORK", "REGISTER_REWORK_RESULT",
            "REGISTER_REWORK_INSPECTION", "SUBMIT_REWORK_REVIEW", "CREATE_NEXT_REWORK");
    private final ReworkOperationQueryRepository receipts;
    private final ReworkReadRepository reads;
    private final ObjectMapper mapper;
    private final TransactionTemplate snapshot;

    public ReworkOperationQueryService(ReworkOperationQueryRepository receipts, ReworkReadRepository reads,
            ObjectMapper mapper, PlatformTransactionManager manager) {
        this.receipts = receipts;
        this.reads = reads;
        this.mapper = mapper;
        snapshot = new TransactionTemplate(manager);
        snapshot.setReadOnly(true);
        snapshot.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        snapshot.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public ReworkOperationQueryResponse query(String taskId, String user, String role,
            ReworkOperationQueryRequest request) {
        if (user == null || user.isBlank()) throw new AuthenticationRequiredException("authenticated user is required");
        if (user.length() > 128 || user.indexOf('\r') >= 0 || user.indexOf('\n') >= 0) {
            throw new InvalidRequestException("X-User-Id must contain 1 to 128 safe characters");
        }
        if (!"REVIEWER".equals(role)) throw new PermissionDeniedException("REVIEWER role is required");
        if (taskId == null || taskId.length() > 64 || !taskId.matches("TASK-[A-Z0-9][A-Z0-9-]*")) {
            throw new InvalidRequestException("resource identifier is invalid");
        }
        Objects.requireNonNull(request);
        // 父任务和用户限定的原回执属于同一快照；不加写锁、不查当前返工来拼造旧结果。
        return Objects.requireNonNull(snapshot.execute(status -> {
            if (!reads.taskExists(taskId)) throw new ResourceNotFoundException("production task", taskId);
            return receipts.find(taskId, user, request.idempotencyKey())
                    .map(stored -> new ReworkOperationQueryResponse(true, decode(stored)))
                    .orElseGet(() -> new ReworkOperationQueryResponse(false, null));
        }));
    }

    private ReworkWriteReceipt decode(StoredReceipt stored) {
        try {
            JsonNode node = mapper.readTree(stored.json());
            if (node == null || !node.isObject() || node.size() != 12) throw invalidStored();
            for (String field : List.of("operation", "operationId", "taskId", "reworkTaskId", "status", "issueStatus")) {
                if (!node.hasNonNull(field) || !node.get(field).isTextual()) throw invalidStored();
            }
            for (String field : List.of("taskVersion", "roundNumber")) {
                if (!node.has(field) || !sequence(node.get(field))) throw invalidStored();
            }
            for (String field : List.of("previousReworkTaskId", "inspectionId", "reviewId")) {
                if (!node.has(field) || (!node.get(field).isNull()
                        && (!node.get(field).isTextual() || !validId(node.get(field).textValue())))) throw invalidStored();
            }
            if (!node.has("processingRevision") || (!node.get("processingRevision").isNull()
                    && !sequence(node.get("processingRevision")))) throw invalidStored();
            ReworkWriteReceipt receipt = mapper.readerFor(ReworkWriteReceipt.class)
                    .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readValue(stored.json());
            if (!OPERATIONS.contains(receipt.operation()) || !stored.operation().equals(receipt.operation())
                    || !stored.operationId().equals(receipt.operationId()) || !validId(receipt.operationId())
                    || !stored.taskId().equals(receipt.taskId()) || !stored.reworkTaskId().equals(receipt.reworkTaskId())
                    || !validId(receipt.reworkTaskId()) || stored.roundNumber() != receipt.roundNumber()
                    || stored.taskVersion() != receipt.taskVersion()
                    || (receipt.roundNumber() == 1) != (receipt.previousReworkTaskId() == null)
                    || (receipt.inspectionId() != null && receipt.processingRevision() == null)
                    || (receipt.reviewId() != null && receipt.inspectionId() == null)) throw invalidStored();
            return receipt;
        } catch (JsonProcessingException exception) {
            throw invalidStored();
        }
    }

    private static boolean sequence(JsonNode value) {
        return value.isIntegralNumber() && value.canConvertToLong()
                && value.longValue() > 0 && value.longValue() <= ReworkStartRequest.MAX_SAFE_INTEGER;
    }

    private static boolean validId(String value) {
        return value != null && value.length() <= 64 && value.matches("[A-Z]+-[A-Z0-9][A-Z0-9-]*");
    }

    private static IllegalStateException invalidStored() {
        return new IllegalStateException("stored rework operation receipt is invalid");
    }
}
