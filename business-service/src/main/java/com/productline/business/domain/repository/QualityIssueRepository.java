package com.productline.business.domain.repository;

import com.productline.business.domain.model.QualityIssue;
import org.springframework.data.jpa.repository.JpaRepository;

public interface QualityIssueRepository extends JpaRepository<QualityIssue, String> {
}
