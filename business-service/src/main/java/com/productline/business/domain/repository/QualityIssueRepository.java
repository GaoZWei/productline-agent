package com.productline.business.domain.repository;

import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.model.QualityIssue;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface QualityIssueRepository extends JpaRepository<QualityIssue, String> {
    // 不传 status
    List<QualityIssue> findAllByTaskTaskIdOrderByIssueIdAsc(String taskId);

    // 传status
    List<QualityIssue> findAllByTaskTaskIdAndStatusOrderByIssueIdAsc(
            String taskId, QualityIssueStatus status);
}
