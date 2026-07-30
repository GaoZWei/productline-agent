package com.productline.business.domain.repository;

import com.productline.business.domain.model.ProductionStep;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProductionStepRepository extends JpaRepository<ProductionStep, String> {
}
