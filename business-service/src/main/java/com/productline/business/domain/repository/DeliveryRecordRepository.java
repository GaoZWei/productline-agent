package com.productline.business.domain.repository;

import com.productline.business.domain.model.DeliveryRecord;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DeliveryRecordRepository extends JpaRepository<DeliveryRecord, String> {
}
