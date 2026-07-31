package com.productline.business.domain.repository;

import com.productline.business.domain.model.ProductionTask;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProductionTaskRepository extends JpaRepository<ProductionTask, String> {

    List<ProductionTask> findAllByOrderOrderIdOrderByTaskIdAsc(String orderId);
}
