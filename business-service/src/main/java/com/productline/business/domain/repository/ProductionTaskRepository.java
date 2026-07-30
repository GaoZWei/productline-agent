package com.productline.business.domain.repository;

import com.productline.business.domain.model.ProductionTask;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProductionTaskRepository extends JpaRepository<ProductionTask, String> {
}
