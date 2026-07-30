package com.productline.business.domain.model;

import com.productline.business.domain.enums.DeliveryStatus;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.util.Objects;

@Entity
@Table(name = "delivery_records")
public class DeliveryRecord {
    // 保存订单交付状态；ORDER-003 对应状态固定为 BLOCKED
    @Id
    @Column(name = "delivery_id", nullable = false, length = 64)
    private String deliveryId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "order_id", nullable = false)
    private Order order;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private DeliveryStatus status;

    protected DeliveryRecord() {
    }

    public DeliveryRecord(String deliveryId, DeliveryStatus status) {
        this.deliveryId = requireText(deliveryId, "deliveryId");
        this.status = Objects.requireNonNull(status, "status");
    }

    void assignTo(Order order) {
        Order requiredOrder = Objects.requireNonNull(order, "order");
        if (this.order != null && this.order != requiredOrder) {
            throw new IllegalStateException(
                    "delivery record is already assigned to another order");
        }
        this.order = requiredOrder;
    }

    public String getDeliveryId() {
        return deliveryId;
    }

    public Order getOrder() {
        return order;
    }

    public DeliveryStatus getStatus() {
        return status;
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
