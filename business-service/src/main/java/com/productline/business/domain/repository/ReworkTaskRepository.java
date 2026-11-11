package com.productline.business.domain.repository;

import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.model.ReworkTask;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ReworkTaskRepository extends JpaRepository<ReworkTask, String> {

    List<ReworkTask> findAllByTaskTaskIdOrderByReworkTaskIdAsc(String taskId);

    boolean existsByTaskTaskIdAndSourceIssueIssueIdAndStatusIn(
            String taskId,
            String sourceIssueId,
            Collection<ProductionTaskStatus> statuses);

    @Query(value = "SELECT EXISTS (SELECT 1 FROM rework_lifecycles WHERE task_id=:taskId AND source_issue_id=:issueId)",
            nativeQuery = true)
    boolean hasLifecycle(@Param("taskId") String taskId, @Param("issueId") String issueId);
}
