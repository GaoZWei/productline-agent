package com.productline.business.domain.repository;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.model.ReworkTask;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ReworkTaskRepository extends JpaRepository<ReworkTask, String> {

    List<ReworkTask> findAllByTaskTaskIdOrderByReworkTaskIdAsc(String taskId);

    boolean existsByTaskTaskIdAndSourceIssueIssueIdAndStatusIn(
            String taskId,
            String sourceIssueId,
            Collection<ProductionTaskStatus> statuses);
}
