package com.productline.business.domain.repository;

import com.productline.business.domain.model.ProductionTask;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProductionTaskRepository extends JpaRepository<ProductionTask, String> {

    List<ProductionTask> findAllByOrderOrderIdOrderByTaskIdAsc(String orderId);

    @Modifying(flushAutomatically = true)
    @Query(
            value =
                    "UPDATE production_tasks SET version = version + 1 "
                            + "WHERE task_id = :taskId AND version = :expectedVersion",
            nativeQuery = true)
    int incrementVersionIfMatches(
            @Param("taskId") String taskId,
            @Param("expectedVersion") long expectedVersion);
}
