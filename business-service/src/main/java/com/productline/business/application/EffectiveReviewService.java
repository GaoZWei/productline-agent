package com.productline.business.application;

import com.productline.business.api.dto.EffectiveReviewsResponse;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.repository.EffectiveReviewRepository;
import java.util.Objects;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.MultiValueMap;

@Service
public class EffectiveReviewService {
    private final EffectiveReviewRepository repository;
    private final TransactionTemplate snapshot;

    public EffectiveReviewService(EffectiveReviewRepository repository, PlatformTransactionManager manager) {
        this.repository = repository;
        snapshot = new TransactionTemplate(manager);
        snapshot.setReadOnly(true);
        snapshot.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        snapshot.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public EffectiveReviewsResponse read(String task, String user, String role, MultiValueMap<String, String> query) {
        if (user == null || user.isBlank()) throw new AuthenticationRequiredException("authenticated user is required");
        if (user.length() > 128 || user.indexOf('\r') >= 0 || user.indexOf('\n') >= 0) throw invalid();
        if (!"REVIEWER".equals(role)) throw new PermissionDeniedException("REVIEWER role is required");
        if (task == null || task.length() > 64 || !task.matches("TASK-[A-Z0-9][A-Z0-9-]*") || !query.isEmpty()) throw invalid();
        return Objects.requireNonNull(snapshot.execute(status -> {
            long version = repository.taskVersion(task).orElseThrow(() -> new ResourceNotFoundException("production task", task));
            if (version < 0 || version > 9007199254740991L) throw new IllegalStateException("stored task version is invalid");
            return new EffectiveReviewsResponse(task, version, repository.issues(task));
        }));
    }

    private InvalidRequestException invalid() {
        return new InvalidRequestException("effective reviews require a safe task identifier and no query parameters");
    }
}
