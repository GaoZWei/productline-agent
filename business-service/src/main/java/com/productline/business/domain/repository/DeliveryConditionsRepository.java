package com.productline.business.domain.repository;

import com.productline.business.domain.dto.DeliveryRecordDto;
import com.productline.business.domain.dto.OrderDto;
import com.productline.business.domain.dto.ProductionStepDto;
import com.productline.business.domain.dto.QualityIssueDto;
import com.productline.business.domain.dto.ReworkTaskDto;
import com.productline.business.domain.enums.DeliveryStatus;
import com.productline.business.domain.enums.OrderStatus;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** 只读取订单及关联事实；由应用层提供同一个独立只读快照。 */
@Repository
public class DeliveryConditionsRepository {
    private final JdbcTemplate jdbc;

    public DeliveryConditionsRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Optional<OrderDto> order(String id) {
        return jdbc.query("SELECT order_id,product_type,status FROM production_orders WHERE order_id=?",
                (rs, row) -> new OrderDto(rs.getString("order_id"), rs.getString("product_type"),
                        OrderStatus.valueOf(rs.getString("status"))), id).stream().findFirst();
    }

    public List<TaskFact> tasks(String orderId) {
        return jdbc.query("SELECT task_id,version,status FROM production_tasks WHERE order_id=? ORDER BY task_id",
                (rs, row) -> new TaskFact(rs.getString("task_id"), rs.getLong("version"),
                        ProductionTaskStatus.valueOf(rs.getString("status"))), orderId);
    }

    public List<ProductionStepDto> steps(String taskId) {
        return jdbc.query("SELECT * FROM production_steps WHERE task_id=? ORDER BY sequence_number,step_id",
                (rs, row) -> new ProductionStepDto(rs.getString("step_id"), taskId, rs.getString("step_name"),
                        rs.getInt("sequence_number"), ProductionTaskStatus.valueOf(rs.getString("status"))), taskId);
    }

    public List<QualityIssueDto> issues(String taskId) {
        return jdbc.query("SELECT * FROM quality_issues WHERE task_id=? ORDER BY issue_id",
                (rs, row) -> new QualityIssueDto(rs.getString("issue_id"), taskId, rs.getString("issue_type"),
                        QualityIssueStatus.valueOf(rs.getString("status")), rs.getString("description")), taskId);
    }

    public List<ReworkTaskDto> activeReworks(String taskId) {
        return jdbc.query("""
                SELECT r.* FROM rework_tasks r
                LEFT JOIN rework_lifecycles l ON l.rework_task_id=r.rework_task_id
                WHERE r.task_id=? AND (r.status IN ('PENDING','RUNNING','BLOCKED')
                    OR (r.status='FAILED' AND l.rework_task_id IS NOT NULL))
                ORDER BY r.rework_task_id
                """, (rs, row) -> new ReworkTaskDto(rs.getString("rework_task_id"), taskId,
                        rs.getString("source_issue_id"), ProductionTaskStatus.valueOf(rs.getString("status")), rs.getString("reason")), taskId);
    }

    public List<DeliveryRecordDto> deliveries(String orderId) {
        return jdbc.query("SELECT * FROM delivery_records WHERE order_id=? ORDER BY delivery_id",
                (rs, row) -> new DeliveryRecordDto(rs.getString("delivery_id"), orderId,
                        DeliveryStatus.valueOf(rs.getString("status"))), orderId);
    }

    public record TaskFact(String taskId, long version, ProductionTaskStatus status) {}
}
