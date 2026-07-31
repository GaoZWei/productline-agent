package com.productline.business.api;

import com.productline.business.api.dto.DeliveryStatusResponse;
import com.productline.business.api.dto.OrderOverviewResponse;
import com.productline.business.api.dto.OrderTasksResponse;
import com.productline.business.application.BusinessQueryService;
import com.productline.business.domain.dto.OrderDto;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

// @RestController 表示该类返回的数据会被 Jackson 自动序列化成 JSON；
// @RequestMapping("/api/orders") 统一定义订单路径前缀
@RestController
@RequestMapping("/api/orders")
public class OrderQueryController {

    private final BusinessQueryService queryService;

    public OrderQueryController(BusinessQueryService queryService) {
        this.queryService = queryService;
    }

    // 查询订单详情
    @GetMapping("/{orderId}")
    public OrderDto getOrder(@PathVariable String orderId) {
        return queryService.getOrder(orderId);
    }

    // 查询订单关联任务
    @GetMapping("/{orderId}/tasks")
    public OrderTasksResponse getOrderTasks(@PathVariable String orderId) {
        return queryService.getOrderTasks(orderId);
    }

    // 查询交付记录
    @GetMapping("/{orderId}/delivery-status")
    public DeliveryStatusResponse getDeliveryStatus(@PathVariable String orderId) {
        return queryService.getDeliveryStatus(orderId);
    }

    // 查询完整订单聚合信息
    @GetMapping("/{orderId}/overview")
    public OrderOverviewResponse getOrderOverview(@PathVariable String orderId) {
        return queryService.getOrderOverview(orderId);
    }
}
