package com.productline.business.application;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReviewSubmissionRequest;
import com.productline.business.api.dto.ReviewWriteResponse;
import com.productline.business.api.dto.ReworkCreationRequest;
import com.productline.business.api.dto.ReworkWriteResponse;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.BusinessConflictException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.dto.ReviewRecordDto;
import com.productline.business.domain.dto.ReworkTaskDto;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.model.IdempotencyRecord;
import com.productline.business.domain.model.OperationLog;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import com.productline.business.domain.model.ReviewRecord;
import com.productline.business.domain.model.ReworkTask;
import com.productline.business.domain.repository.IdempotencyRecordRepository;
import com.productline.business.domain.repository.OperationLogRepository;
import com.productline.business.domain.repository.ProductionTaskRepository;
import com.productline.business.domain.repository.QualityIssueRepository;
import com.productline.business.domain.repository.ReviewRecordRepository;
import com.productline.business.domain.repository.ReworkTaskRepository;
import jakarta.persistence.EntityManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.EnumSet;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class BusinessWriteService {

        private static final String REVIEWER_ROLE = "REVIEWER";
        private static final String SUBMIT_REVIEW = "SUBMIT_REVIEW";
        private static final String CREATE_REWORK = "CREATE_REWORK";
        private static final EnumSet<ProductionTaskStatus> ACTIVE_REWORK_STATUSES = EnumSet.of(
                        ProductionTaskStatus.PENDING,
                        ProductionTaskStatus.RUNNING,
                        ProductionTaskStatus.BLOCKED);

        private final ProductionTaskRepository taskRepository;
        private final QualityIssueRepository issueRepository;
        private final ReviewRecordRepository reviewRepository;
        private final ReworkTaskRepository reworkRepository;
        private final IdempotencyRecordRepository idempotencyRepository;
        private final OperationLogRepository operationLogRepository;
        private final EntityManager entityManager;
        private final ObjectMapper objectMapper;

        public BusinessWriteService(
                        ProductionTaskRepository taskRepository,
                        QualityIssueRepository issueRepository,
                        ReviewRecordRepository reviewRepository,
                        ReworkTaskRepository reworkRepository,
                        IdempotencyRecordRepository idempotencyRepository,
                        OperationLogRepository operationLogRepository,
                        EntityManager entityManager,
                        ObjectMapper objectMapper) {
                this.taskRepository = taskRepository;
                this.issueRepository = issueRepository;
                this.reviewRepository = reviewRepository;
                this.reworkRepository = reworkRepository;
                this.idempotencyRepository = idempotencyRepository;
                this.operationLogRepository = operationLogRepository;
                this.entityManager = entityManager;
                this.objectMapper = objectMapper;
        }

        // 提交复核结果
        // 主要限制：
        // 只有 REVIEWER 可以提交。
        // 生产任务必须是 COMPLETED。
        // 问题必须属于路径中的任务。
        // PENDING 不能作为最终复核结论。
        // CLOSED 问题不能重复复核。
        // 只有 RESOLVED 问题可以提交 APPROVED。
        // 当前只追加复核历史，不自动修改问题、订单或交付状态。
        @Transactional
        public ReviewWriteResponse submitReview(
                        String taskId,
                        String userId,
                        String userRole,
                        String idempotencyKey,
                        ReviewSubmissionRequest request) {
                validateActor(userId, userRole);
                validateIdempotencyKey(idempotencyKey);
                String requestHash = hash(
                                SUBMIT_REVIEW,
                                taskId,
                                request.issueId(),
                                request.status().name(),
                                request.reviewComment(),
                                request.expectedVersion().toString());
                IdempotencyRecord idempotency = reserveOrLoad(
                                idempotencyKey,
                                SUBMIT_REVIEW,
                                requestHash,
                                userId);
                if (idempotency.isCompleted()) {
                        return replayReview(idempotency);
                }

                ProductionTask task = requireTask(taskId);
                validateExpectedVersion(task, request.expectedVersion());
                validateCompletedTask(task);
                QualityIssue issue = requireIssueForTask(request.issueId(), taskId);
                validateReviewState(issue, request.status());

                int reviewCountBefore = reviewRepository.findAllByTaskIdOrderByReviewIdAsc(taskId).size();
                String reviewId = generatedId("REVIEW-WRITE-");
                ReviewRecord review = new ReviewRecord(reviewId, request.status(), request.reviewComment());
                issue.addReviewRecord(review);

                long nextVersion = incrementVersion(task, request.expectedVersion());
                idempotency.complete(reviewId, nextVersion);
                operationLogRepository.save(
                                new OperationLog(
                                                generatedId("OPERATION-"),
                                                SUBMIT_REVIEW,
                                                "PRODUCTION_TASK",
                                                taskId,
                                                userId,
                                                hash(idempotencyKey),
                                                json(
                                                                Map.of(
                                                                                "taskVersion",
                                                                                request.expectedVersion(),
                                                                                "issueId",
                                                                                issue.getIssueId(),
                                                                                "reviewCount",
                                                                                reviewCountBefore)),
                                                json(
                                                                Map.of(
                                                                                "taskVersion",
                                                                                nextVersion,
                                                                                "issueId",
                                                                                issue.getIssueId(),
                                                                                "reviewId",
                                                                                reviewId,
                                                                                "reviewStatus",
                                                                                request.status().name(),
                                                                                "reviewCount",
                                                                                reviewCountBefore + 1))));
                return new ReviewWriteResponse(toDto(review), nextVersion);
        }

        @Transactional
        public ReworkWriteResponse createRework(
                        String taskId,
                        String userId,
                        String userRole,
                        String idempotencyKey,
                        ReworkCreationRequest request) {
                validateActor(userId, userRole);
                validateIdempotencyKey(idempotencyKey);
                String requestHash = hash(
                                CREATE_REWORK,
                                taskId,
                                request.sourceIssueId(),
                                request.reason(),
                                request.expectedVersion().toString());
                IdempotencyRecord idempotency = reserveOrLoad(
                                idempotencyKey,
                                CREATE_REWORK,
                                requestHash,
                                userId);
                if (idempotency.isCompleted()) {
                        return replayRework(idempotency);
                }

                ProductionTask task = requireTask(taskId);
                validateExpectedVersion(task, request.expectedVersion());
                validateCompletedTask(task);
                QualityIssue issue = requireIssueForTask(request.sourceIssueId(), taskId);
                if (issue.getStatus() == QualityIssueStatus.CLOSED) {
                        throw new BusinessConflictException("closed issue cannot create rework");
                }
                if (reworkRepository.existsByTaskTaskIdAndSourceIssueIssueIdAndStatusIn(
                                taskId, issue.getIssueId(), ACTIVE_REWORK_STATUSES)) {
                        throw new BusinessConflictException(
                                        "active rework already exists for issue: " + issue.getIssueId());
                }

                String reworkTaskId = generatedId("REWORK-WRITE-");
                ReworkTask rework = new ReworkTask(
                                reworkTaskId,
                                ProductionTaskStatus.PENDING,
                                request.reason());
                rework.setSourceIssue(issue);
                task.addReworkTask(rework);

                long nextVersion = incrementVersion(task, request.expectedVersion());
                idempotency.complete(reworkTaskId, nextVersion);
                operationLogRepository.save(
                                new OperationLog(
                                                generatedId("OPERATION-"),
                                                CREATE_REWORK,
                                                "PRODUCTION_TASK",
                                                taskId,
                                                userId,
                                                hash(idempotencyKey),
                                                json(
                                                                Map.of(
                                                                                "taskVersion",
                                                                                request.expectedVersion(),
                                                                                "sourceIssueId",
                                                                                issue.getIssueId(),
                                                                                "activeReworkExists",
                                                                                false)),
                                                json(
                                                                Map.of(
                                                                                "taskVersion",
                                                                                nextVersion,
                                                                                "sourceIssueId",
                                                                                issue.getIssueId(),
                                                                                "reworkTaskId",
                                                                                reworkTaskId,
                                                                                "reworkStatus",
                                                                                ProductionTaskStatus.PENDING.name()))));
                return new ReworkWriteResponse(toDto(rework), nextVersion);
        }

        // 幂等控制：确保每个请求只执行一次
        private IdempotencyRecord reserveOrLoad(
                        String key, String operationType, String requestHash, String actorUserId) {
                int inserted = idempotencyRepository.reserve(
                                key, operationType, requestHash, actorUserId);
                IdempotencyRecord record = idempotencyRepository
                                .findById(key)
                                .orElseThrow(
                                                () -> new IllegalStateException(
                                                                "reserved idempotency record is missing"));
                if (inserted == 0
                                && (!record.getOperationType().equals(operationType)
                                                || !record.getRequestHash().equals(requestHash)
                                                || !record.getActorUserId().equals(actorUserId))) {
                        throw new BusinessConflictException(
                                        "idempotency key was already used for another request");
                }
                if (inserted == 0 && !record.isCompleted()) {
                        throw new BusinessConflictException("idempotency request is still in progress");
                }
                return record;
        }

        private ReviewWriteResponse replayReview(IdempotencyRecord record) {
                ReviewRecord review = reviewRepository
                                .findById(record.getResourceId())
                                .orElseThrow(
                                                () -> new BusinessConflictException(
                                                                "idempotent review result is unavailable"));
                return new ReviewWriteResponse(toDto(review), record.getTaskVersionAfter());
        }

        private ReworkWriteResponse replayRework(IdempotencyRecord record) {
                ReworkTask rework = reworkRepository
                                .findById(record.getResourceId())
                                .orElseThrow(
                                                () -> new BusinessConflictException(
                                                                "idempotent rework result is unavailable"));
                return new ReworkWriteResponse(toDto(rework), record.getTaskVersionAfter());
        }

        // 校验用户角色
        private void validateActor(String userId, String userRole) {
                if (userId == null || userId.isBlank()) {
                        throw new AuthenticationRequiredException("authenticated user is required");
                }
                if (userId.length() > 128) {
                        throw new InvalidRequestException("X-User-Id must not exceed 128 characters");
                }
                if (!REVIEWER_ROLE.equals(userRole)) {
                        throw new PermissionDeniedException("REVIEWER role is required");
                }
        }

        private void validateIdempotencyKey(String key) {
                if (key == null || key.isBlank() || key.length() > 128) {
                        throw new InvalidRequestException(
                                        "Idempotency-Key must contain 1 to 128 characters");
                }
        }

        private void validateExpectedVersion(ProductionTask task, long expectedVersion) {
                if (task.getVersion() != expectedVersion) {
                        throw new BusinessConflictException(
                                        "task version conflict: expected "
                                                        + expectedVersion
                                                        + " but was "
                                                        + task.getVersion());
                }
        }

        private void validateCompletedTask(ProductionTask task) {
                if (task.getStatus() != ProductionTaskStatus.COMPLETED) {
                        throw new BusinessConflictException(
                                        "task must be COMPLETED before review or rework");
                }
        }

        private void validateReviewState(QualityIssue issue, ReviewStatus status) {
                if (status == ReviewStatus.PENDING) {
                        throw new BusinessConflictException("PENDING is not a review conclusion");
                }
                if (issue.getStatus() == QualityIssueStatus.CLOSED) {
                        throw new BusinessConflictException("closed issue cannot be reviewed again");
                }
                if (status == ReviewStatus.APPROVED
                                && issue.getStatus() != QualityIssueStatus.RESOLVED) {
                        throw new BusinessConflictException(
                                        "only a RESOLVED issue can be approved");
                }
        }

        private ProductionTask requireTask(String taskId) {
                return taskRepository
                                .findById(taskId)
                                .orElseThrow(() -> new ResourceNotFoundException("task", taskId));
        }

        private QualityIssue requireIssueForTask(String issueId, String taskId) {
                QualityIssue issue = issueRepository
                                .findById(issueId)
                                .orElseThrow(
                                                () -> new ResourceNotFoundException("quality issue", issueId));
                if (!issue.getTask().getTaskId().equals(taskId)) {
                        throw new BusinessConflictException(
                                        "quality issue does not belong to task: " + taskId);
                }
                return issue;
        }

        private long incrementVersion(ProductionTask task, long expectedVersion) {
                int updated = taskRepository.incrementVersionIfMatches(task.getTaskId(), expectedVersion);
                if (updated != 1) {
                        throw new BusinessConflictException("task was modified concurrently");
                }
                entityManager.refresh(task);
                return task.getVersion();
        }

        private ReviewRecordDto toDto(ReviewRecord review) {
                return new ReviewRecordDto(
                                review.getReviewId(),
                                review.getIssue().getIssueId(),
                                review.getStatus(),
                                review.getReviewComment());
        }

        private ReworkTaskDto toDto(ReworkTask rework) {
                return new ReworkTaskDto(
                                rework.getReworkTaskId(),
                                rework.getTask().getTaskId(),
                                rework.getSourceIssue() == null
                                                ? null
                                                : rework.getSourceIssue().getIssueId(),
                                rework.getStatus(),
                                rework.getReason());
        }

        private String generatedId(String prefix) {
                return prefix + UUID.randomUUID().toString().toUpperCase(Locale.ROOT);
        }

        private String json(Map<String, Object> value) {
                try {
                        return objectMapper.writeValueAsString(value);
                } catch (JsonProcessingException exception) {
                        throw new IllegalStateException("failed to serialize operation state", exception);
                }
        }

        private String hash(String... values) {
                try {
                        MessageDigest digest = MessageDigest.getInstance("SHA-256");
                        byte[] bytes = digest.digest(
                                        String.join("\u001f", values)
                                                        .getBytes(StandardCharsets.UTF_8));
                        return HexFormat.of().formatHex(bytes);
                } catch (NoSuchAlgorithmException exception) {
                        throw new IllegalStateException("SHA-256 is unavailable", exception);
                }
        }
}
