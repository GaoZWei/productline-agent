package com.productline.business.domain.repository;

import com.productline.business.domain.model.ReviewRecord;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ReviewRecordRepository extends JpaRepository<ReviewRecord, String> {
}
