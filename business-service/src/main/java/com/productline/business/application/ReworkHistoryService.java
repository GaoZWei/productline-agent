package com.productline.business.application;

import com.productline.business.api.dto.ReworkHistoryResponse;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.BusinessConflictException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.repository.ReworkHistoryRepository;
import com.productline.business.domain.repository.ReworkHistoryRepository.Kind;
import com.productline.business.domain.repository.ReworkReadRepository;
import java.util.List;
import java.util.Objects;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.MultiValueMap;

@Service
public class ReworkHistoryService {
    private final ReworkReadRepository facts;
    private final ReworkHistoryRepository history;
    private final ReworkHistoryCursor cursors;
    private final TransactionTemplate snapshot;

    public ReworkHistoryService(ReworkReadRepository facts, ReworkHistoryRepository history,
            ReworkHistoryCursor cursors, PlatformTransactionManager manager) {
        this.facts = facts;
        this.history = history;
        this.cursors = cursors;
        snapshot = new TransactionTemplate(manager);
        snapshot.setReadOnly(true);
        snapshot.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        snapshot.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public ReworkHistoryResponse<?> read(String task, String rework, String user, String role,
            Kind kind, MultiValueMap<String, String> query) {
        if (user == null || user.isBlank()) throw new AuthenticationRequiredException("authenticated user is required");
        if (user.length() > 128 || user.indexOf('\r') >= 0 || user.indexOf('\n') >= 0) throw invalid();
        if (!"REVIEWER".equals(role)) throw new PermissionDeniedException("REVIEWER role is required");
        if (task == null || task.length() > 64 || !task.matches("TASK-[A-Z0-9][A-Z0-9-]*")
                || rework == null || rework.length() > 64 || !rework.matches("[A-Z]+-[A-Z0-9][A-Z0-9-]*")) throw invalid();
        if (query.entrySet().stream().anyMatch(e -> !List.of("cursor", "limit").contains(e.getKey())
                || e.getValue().size() != 1)) throw invalid();
        String rawLimit = query.getFirst("limit");
        if (rawLimit != null && !rawLimit.matches("[1-9][0-9]{0,2}")) throw invalid();
        int limit = rawLimit == null ? 20 : Integer.parseInt(rawLimit);
        if (limit > 100) throw invalid();
        String token = query.getFirst("cursor");
        var bound = token == null ? null : cursors.decode(token, user, task, rework, kind.name());
        return Objects.requireNonNull(snapshot.execute(status -> {
            if (!facts.taskExists(task)) throw new ResourceNotFoundException("production task", task);
            String owner = facts.findOwner(rework).orElseThrow(() -> new ResourceNotFoundException("rework task", rework));
            if (!task.equals(owner)) throw new BusinessConflictException("rework task does not belong to the requested task");
            long upper = bound == null ? history.upper(task, rework, kind) : bound.upper();
            long after = bound == null ? 0 : bound.after();
            if (upper < 0 || upper > 9007199254740991L) throw new IllegalStateException("stored history sequence is invalid");
            if (kind == Kind.RESULTS) {
                var rows = history.results(task, rework, after, upper, limit + 1);
                var page = rows.subList(0, Math.min(rows.size(), limit));
                String next = rows.size() <= limit ? null : cursors.encode(user, task, rework, kind.name(),
                        new ReworkHistoryCursor.Window(page.getLast().processingRevision(), upper));
                return new ReworkHistoryResponse<>(task, rework, page, next);
            }
            if (kind == Kind.REVIEWS) {
                var rows = history.reviews(task, rework, after, upper, limit + 1);
                var page = rows.subList(0, Math.min(rows.size(), limit));
                String next = rows.size() <= limit ? null : cursors.encode(user, task, rework, kind.name(),
                        new ReworkHistoryCursor.Window(page.getLast().reviewSequence(), upper));
                return new ReworkHistoryResponse<>(task, rework, page, next);
            }
            var rows = history.inspections(task, rework, after, upper, limit + 1);
            var page = rows.subList(0, Math.min(rows.size(), limit));
            String next = rows.size() <= limit ? null : cursors.encode(user, task, rework, kind.name(),
                    new ReworkHistoryCursor.Window(page.getLast().inspectionSequence(), upper));
            return new ReworkHistoryResponse<>(task, rework, page, next);
        }));
    }

    private InvalidRequestException invalid() {
        return new InvalidRequestException("history requires safe resource identifiers and only cursor and limit (1 to 100)");
    }
}
