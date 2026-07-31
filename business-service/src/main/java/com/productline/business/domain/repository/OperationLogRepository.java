package com.productline.business.domain.repository;

import com.productline.business.domain.model.OperationLog;
import org.springframework.data.jpa.repository.JpaRepository;

public interface OperationLogRepository extends JpaRepository<OperationLog, String> {
}
