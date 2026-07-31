package com.productline.business.domain.repository;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.model.ReworkTask;
import java.util.Collection;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ReworkTaskRepository extends JpaRepository<ReworkTask, String> {

    boolean existsByTaskTaskIdAndSourceIssueIssueIdAndStatusIn(
            String taskId,
            String sourceIssueId,
            Collection<ProductionTaskStatus> statuses);
}
