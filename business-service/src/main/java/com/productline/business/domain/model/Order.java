package com.productline.business.domain.model;

import com.productline.business.domain.enums.OrderStatus;
import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

@Entity
@Table(name = "production_orders")
public class Order {

    @Id
    @Column(name = "order_id", nullable = false, length = 64)
    private String orderId;

    @Column(name = "product_type", nullable = false, length = 64)
    private String productType;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private OrderStatus status;

    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true)
    private final List<ProductionTask> tasks = new ArrayList<>();

    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true)
    private final List<DeliveryRecord> deliveryRecords = new ArrayList<>();

    protected Order() {
    }

    public Order(String orderId, String productType, OrderStatus status) {
        this.orderId = requireText(orderId, "orderId");
        this.productType = requireText(productType, "productType");
        this.status = Objects.requireNonNull(status, "status");
    }
    // 添加一个生产任务并同步设置任务所属订单
    public void addTask(ProductionTask task) {
        ProductionTask requiredTask = Objects.requireNonNull(task, "task");
        requiredTask.assignTo(this);
        tasks.add(requiredTask);
    }
    // 添加交付记录并建立订单关系
    public void addDeliveryRecord(DeliveryRecord deliveryRecord) {
        DeliveryRecord requiredRecord = Objects.requireNonNull(deliveryRecord, "deliveryRecord");
        requiredRecord.assignTo(this);
        deliveryRecords.add(requiredRecord);
    }

    public String getOrderId() {
        return orderId;
    }

    public String getProductType() {
        return productType;
    }

    public OrderStatus getStatus() {
        return status;
    }

    public List<ProductionTask> getTasks() {
        return Collections.unmodifiableList(tasks);
    }

    public List<DeliveryRecord> getDeliveryRecords() {
        return Collections.unmodifiableList(deliveryRecords);
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
