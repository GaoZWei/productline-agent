package com.productline.business.application;

import com.productline.business.api.dto.ReworkDetailResponse;
import com.productline.business.api.dto.ReworkDetailResponse.AllowedAction;
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
import com.productline.business.domain.repository.ReworkReadRepository;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ReworkQueryService {
    private final ReworkReadRepository repository;
    private final TransactionTemplate readSnapshot;

    public ReworkQueryService(ReworkReadRepository repository, PlatformTransactionManager transactionManager) {
        this.repository = repository;
        readSnapshot = new TransactionTemplate(transactionManager);
        readSnapshot.setReadOnly(true);
        readSnapshot.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        // 不继承调用方可能已有的读写事务或较弱隔离级别。
        readSnapshot.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public ReworkDetailResponse getDetail(String taskId, String reworkTaskId, String userId, String userRole) {
        requireReader(userId, userRole);
        requireId(taskId, "TASK-[A-Z0-9][A-Z0-9-]*");
        requireId(reworkTaskId, "[A-Z]+-[A-Z0-9][A-Z0-9-]*");
        // 授权与参数检查在开启事务之前；父任务、归属与当前材料属于同一只读快照。
        return Objects.requireNonNull(readSnapshot.execute(status -> {
            if (!repository.taskExists(taskId)) {
                throw new ResourceNotFoundException("production task", taskId);
            }
            String owner = repository.findOwner(reworkTaskId)
                    .orElseThrow(() -> new ResourceNotFoundException("rework task", reworkTaskId));
            if (!taskId.equals(owner)) {
                throw new BusinessConflictException("rework task does not belong to the requested task");
            }
            var snapshot = repository.findDetail(taskId, reworkTaskId)
                    .orElseThrow(() -> new ResourceNotFoundException("rework task", reworkTaskId));
            if (snapshot.taskVersion() < 0 || snapshot.taskVersion() > 9007199254740991L) {
                throw new IllegalStateException("stored task version is invalid");
            }
            return new ReworkDetailResponse(snapshot.reworkTask(), snapshot.issueStatus(), snapshot.roundNumber(),
                    snapshot.previousReworkTaskId(), allowedActions(snapshot), snapshot.taskVersion(),
                    snapshot.processing(), snapshot.inspection(), snapshot.review());
        }));
    }

    private void requireReader(String userId, String role) {
        if (userId == null || userId.isBlank()) {
            throw new AuthenticationRequiredException("authenticated user is required");
        }
        if (userId.length() > 128 || userId.indexOf('\r') >= 0 || userId.indexOf('\n') >= 0) {
            throw new InvalidRequestException("X-User-Id must contain 1 to 128 safe characters");
        }
        if (!"REVIEWER".equals(role)) {
            throw new PermissionDeniedException("REVIEWER role is required");
        }
    }

    private void requireId(String value, String pattern) {
        if (value == null || value.length() > 64 || !value.matches(pattern)) {
            throw new InvalidRequestException("resource identifier is invalid");
        }
    }

    static List<AllowedAction> allowedActions(ReworkLifecycleSnapshot snapshot) {
        if (snapshot.roundNumber() == null || snapshot.reworkTask().sourceIssueId() == null
                || snapshot.taskStatus() != ProductionTaskStatus.COMPLETED || snapshot.hasSuccessor()) {
            return List.of();
        }
        var status = snapshot.reworkTask().status();
        var issue = snapshot.issueStatus();
        if (status == ProductionTaskStatus.PENDING && issue == QualityIssueStatus.OPEN) {
            return List.of(AllowedAction.START_REWORK);
        }
        if ((status == ProductionTaskStatus.BLOCKED || status == ProductionTaskStatus.FAILED)
                && issue == QualityIssueStatus.PROCESSING) {
            return List.of(AllowedAction.RESUME_REWORK);
        }
        if (status == ProductionTaskStatus.RUNNING && issue == QualityIssueStatus.PROCESSING) {
            List<AllowedAction> actions = new ArrayList<>(List.of(AllowedAction.BLOCK_REWORK,
                    AllowedAction.FAIL_REWORK, AllowedAction.REGISTER_REWORK_RESULT));
            if (snapshot.processing() != null) {
                actions.add(AllowedAction.REGISTER_REWORK_INSPECTION);
            }
            return List.copyOf(actions);
        }
        boolean passed = snapshot.processing() != null && snapshot.inspection() != null
                && snapshot.inspection().result() == ReworkInspectionResult.PASSED;
        if (status == ProductionTaskStatus.COMPLETED && issue == QualityIssueStatus.RESOLVED && passed) {
            return List.of(AllowedAction.SUBMIT_REWORK_REVIEW);
        }
        if (status == ProductionTaskStatus.COMPLETED && issue == QualityIssueStatus.OPEN && passed
                && snapshot.review() != null && !snapshot.hasOtherActiveRework()
                && (snapshot.review().status() == ReviewStatus.REJECTED
                    || snapshot.review().status() == ReviewStatus.REWORK_REQUIRED)) {
            return List.of(AllowedAction.CREATE_NEXT_REWORK);
        }
        return List.of();
    }
}
