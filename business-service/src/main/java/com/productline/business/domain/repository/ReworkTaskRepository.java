package com.productline.business.domain.repository;

import com.productline.business.domain.model.ReworkTask;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ReworkTaskRepository extends JpaRepository<ReworkTask, String> {
}
