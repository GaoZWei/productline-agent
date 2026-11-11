package com.productline.business.application;

import com.productline.business.api.dto.DeliveryConditionsResponse;
import com.productline.business.api.dto.DeliveryConditionsResponse.Blocker;
import com.productline.business.api.dto.DeliveryConditionsResponse.Code;
import com.productline.business.api.dto.DeliveryConditionsResponse.IssueCondition;
import com.productline.business.api.dto.DeliveryConditionsResponse.TaskConditions;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.dto.EffectiveReviewSnapshot;
import com.productline.business.domain.dto.QualityIssueDto;
import com.productline.business.domain.enums.DeliveryStatus;
import com.productline.business.domain.enums.OrderStatus;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import com.productline.business.domain.repository.DeliveryConditionsRepository;
import com.productline.business.domain.repository.EffectiveReviewRepository;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.MultiValueMap;

/** 重验已知交付条件；不写状态、不把历史失败永久当作受控问题的当前结论。 */
@Service
public class DeliveryConditionsService {
    private final DeliveryConditionsRepository facts;
    private final EffectiveReviewRepository reviews;
    private final TransactionTemplate snapshot;

    public DeliveryConditionsService(DeliveryConditionsRepository facts, EffectiveReviewRepository reviews,
            PlatformTransactionManager manager) {
        this.facts = facts;
        this.reviews = reviews;
        snapshot = new TransactionTemplate(manager);
        snapshot.setReadOnly(true);
        snapshot.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        snapshot.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public DeliveryConditionsResponse read(String orderId, String user, String role, MultiValueMap<String, String> query) {
        if (user == null || user.isBlank()) throw new AuthenticationRequiredException("authenticated user is required");
        if (user.length() > 128 || user.indexOf('\r') >= 0 || user.indexOf('\n') >= 0 || user.indexOf('\0') >= 0
                || !StandardCharsets.UTF_8.newEncoder().canEncode(user)) throw invalid();
        if (!"REVIEWER".equals(role)) throw new PermissionDeniedException("REVIEWER role is required");
        if (orderId == null || orderId.length() > 64 || !orderId.matches("ORDER-[A-Z0-9][A-Z0-9-]*") || !query.isEmpty()) throw invalid();
        return Objects.requireNonNull(snapshot.execute(status -> conditions(orderId)));
    }

    private DeliveryConditionsResponse conditions(String orderId) {
        var order = facts.order(orderId).orElseThrow(() -> new ResourceNotFoundException("order", orderId));
        var blockers = new ArrayList<Blocker>();
        var tasks = new ArrayList<TaskConditions>();
        if (order.status() == OrderStatus.BLOCKED) blockers.add(new Blocker(Code.ORDER_BLOCKED, null, orderId, order.status().name()));
        var taskFacts = facts.tasks(orderId);
        if (taskFacts.isEmpty()) blockers.add(new Blocker(Code.MISSING_PRODUCTION_TASKS, null, orderId, null));
        for (var task : taskFacts) {
            if (task.version() < 0 || task.version() > 9007199254740991L) throw new IllegalStateException("stored task version is invalid");
            String id = task.taskId();
            if (task.status() != ProductionTaskStatus.COMPLETED) blockers.add(new Blocker(Code.PRODUCTION_TASK_NOT_COMPLETED, id, id, task.status().name()));
            var steps = facts.steps(id);
            if (steps.isEmpty()) blockers.add(new Blocker(Code.MISSING_PRODUCTION_STEPS, id, id, null));
            for (var step : steps) if (step.status() != ProductionTaskStatus.COMPLETED) {
                blockers.add(new Blocker(Code.PRODUCTION_STEP_NOT_COMPLETED, id, step.stepId(), step.status().name()));
            }
            // 复用同一选取规则和当前事务，不能调用另开快照的HTTP/Service拼接事实。
            var effective = reviews.issues(id).stream().collect(Collectors.toMap(EffectiveReviewSnapshot::issueId, Function.identity()));
            var issues = new ArrayList<IssueCondition>();
            for (var issue : facts.issues(id)) {
                var review = effective.get(issue.issueId());
                if (review == null) throw new IllegalStateException("effective review binding is unavailable");
                issues.add(new IssueCondition(issue, review));
                issueBlockers(id, issue, review, blockers);
            }
            var active = facts.activeReworks(id);
            for (var rework : active) blockers.add(new Blocker(Code.ACTIVE_REWORK, id, rework.reworkTaskId(), rework.status().name()));
            tasks.add(new TaskConditions(id, task.version(), task.status(), steps, issues, active));
        }
        var deliveries = facts.deliveries(orderId);
        if (deliveries.isEmpty()) blockers.add(new Blocker(Code.MISSING_DELIVERY_RECORDS, null, orderId, null));
        for (var record : deliveries) if (record.status() == DeliveryStatus.NOT_READY || record.status() == DeliveryStatus.BLOCKED
                || record.status() == DeliveryStatus.FAILED) {
            blockers.add(new Blocker(Code.DELIVERY_NOT_READY, null, record.deliveryId(), record.status().name()));
        }
        return new DeliveryConditionsResponse(order, tasks, deliveries, blockers, !blockers.isEmpty());
    }

    private void issueBlockers(String task, QualityIssueDto issue, EffectiveReviewSnapshot effective, List<Blocker> blockers) {
        if (effective.roundNumber() != null) {
            if (issue.status() != QualityIssueStatus.CLOSED) blockers.add(new Blocker(Code.CONTROLLED_ISSUE_NOT_CLOSED, task, issue.issueId(), issue.status().name()));
            if (effective.review() == null || effective.review().status() != ReviewStatus.APPROVED) {
                blockers.add(new Blocker(Code.EFFECTIVE_REVIEW_NOT_APPROVED, task, issue.issueId(),
                        effective.review() == null ? null : effective.review().status().name()));
            }
        } else {
            // 存量没有受控绑定，显式保留旧规则，不按ID或时间挑选一个历史通过。
            if (issue.status() == QualityIssueStatus.OPEN || issue.status() == QualityIssueStatus.PROCESSING) {
                blockers.add(new Blocker(Code.QUALITY_ISSUE_UNRESOLVED, task, issue.issueId(), issue.status().name()));
            }
            for (var old : effective.legacyReviews()) if (old.status() != ReviewStatus.APPROVED) {
                blockers.add(new Blocker(Code.LEGACY_REVIEW_NOT_APPROVED, task, old.reviewId(), old.status().name()));
            }
            if (issue.status() == QualityIssueStatus.RESOLVED && effective.legacyReviews().stream().noneMatch(old -> old.status() == ReviewStatus.APPROVED)) {
                blockers.add(new Blocker(Code.LEGACY_RESOLVED_ISSUE_WITHOUT_APPROVAL, task, issue.issueId(), issue.status().name()));
            }
        }
    }

    private InvalidRequestException invalid() {
        return new InvalidRequestException("delivery conditions require a safe order identifier and no query parameters");
    }
}
