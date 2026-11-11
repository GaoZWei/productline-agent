package com.productline.business.domain.repository;

import com.productline.business.domain.model.ProductionTask;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProductionTaskRepository extends JpaRepository<ProductionTask, String> {

    List<ProductionTask> findAllByOrderOrderIdOrderByTaskIdAsc(String orderId);

    // 新旧创建共用父任务锁；成功幂等重放在加锁前返回原结果。
    @Query(value = "SELECT task_id FROM production_tasks WHERE task_id=:taskId FOR UPDATE", nativeQuery = true)
    Optional<String> lockForReworkCreation(@Param("taskId") String taskId);

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
