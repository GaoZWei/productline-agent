package com.productline.business.application;

import com.productline.business.api.dto.DeliveryStatusResponse;
import com.productline.business.api.dto.OrderOverviewResponse;
import com.productline.business.api.dto.OrderTasksResponse;
import com.productline.business.api.dto.ProductionProgressResponse;
import com.productline.business.api.dto.QualityIssueListResponse;
import com.productline.business.api.dto.QualityIssueOverviewResponse;
import com.productline.business.api.dto.ReviewResultResponse;
import com.productline.business.api.dto.TaskOverviewResponse;
import com.productline.business.api.error.ResourceNotFoundException;
import com.productline.business.domain.dto.DeliveryRecordDto;
import com.productline.business.domain.dto.OrderDto;
import com.productline.business.domain.dto.ProductionStepDto;
import com.productline.business.domain.dto.ProductionTaskDto;
import com.productline.business.domain.dto.QualityIssueDto;
import com.productline.business.domain.dto.ReviewRecordDto;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.model.DeliveryRecord;
import com.productline.business.domain.model.Order;
import com.productline.business.domain.model.ProductionStep;
import com.productline.business.domain.model.ProductionTask;
import com.productline.business.domain.model.QualityIssue;
import com.productline.business.domain.model.ReviewRecord;
import com.productline.business.domain.repository.DeliveryRecordRepository;
import com.productline.business.domain.repository.OrderRepository;
import com.productline.business.domain.repository.ProductionStepRepository;
import com.productline.business.domain.repository.ProductionTaskRepository;
import com.productline.business.domain.repository.QualityIssueRepository;
import com.productline.business.domain.repository.ReviewRecordRepository;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

// @Transactional(readOnly = true)保证 Entity 到 DTO 的转换发生在有效事务内，懒加载关系可以安全访问
// 明确这些方法不会修改数据库。
// 给数据库和 Hibernate 提供只读事务语义
@Service
@Transactional(readOnly = true)
public class BusinessQueryService {

        private final OrderRepository orderRepository;
        private final ProductionTaskRepository taskRepository;
        private final ProductionStepRepository stepRepository;
        private final QualityIssueRepository issueRepository;
        private final ReviewRecordRepository reviewRepository;
        private final DeliveryRecordRepository deliveryRepository;

        public BusinessQueryService(
                        OrderRepository orderRepository,
                        ProductionTaskRepository taskRepository,
                        ProductionStepRepository stepRepository,
                        QualityIssueRepository issueRepository,
                        ReviewRecordRepository reviewRepository,
                        DeliveryRecordRepository deliveryRepository) {
                this.orderRepository = orderRepository;
                this.taskRepository = taskRepository;
                this.stepRepository = stepRepository;
                this.issueRepository = issueRepository;
                this.reviewRepository = reviewRepository;
                this.deliveryRepository = deliveryRepository;
        }

        // 查询订单详情
        public OrderDto getOrder(String orderId) {
                return toDto(requireOrder(orderId)); // toDto 把 Order Entity 转换为 OrderDto
        }

        public OrderTasksResponse getOrderTasks(String orderId) {
                requireOrder(orderId);
                List<ProductionTaskDto> tasks = taskRepository.findAllByOrderOrderIdOrderByTaskIdAsc(orderId).stream()
                                .map(this::toDto)
                                .toList();
                return new OrderTasksResponse(orderId, tasks);
        }

        public ProductionTaskDto getTask(String taskId) {
                return toDto(requireTask(taskId));
        }

        // 查询生产任务进度
        public ProductionProgressResponse getProductionProgress(String taskId) {
                requireTask(taskId);
                List<ProductionStepDto> steps = stepRepository.findAllByTaskTaskIdOrderBySequenceNumberAsc(taskId)
                                .stream()
                                .map(this::toDto)
                                .toList();
                return new ProductionProgressResponse(taskId, steps);
        }

        // 质检问题过滤，status为null时查询该任务所有问题
        // issues.stream().map(this::toDto).toList()：返回结构只包含接口需要的字段
        // QualityIssueListResponse：响应结构定义
        public QualityIssueListResponse getQualityIssues(
                        String taskId, QualityIssueStatus status) {
                requireTask(taskId);
                // 根据 status 选择查询方法
                List<QualityIssue> issues = status == null
                                ? issueRepository.findAllByTaskTaskIdOrderByIssueIdAsc(taskId)
                                : issueRepository.findAllByTaskTaskIdAndStatusOrderByIssueIdAsc(
                                                taskId, status);
                return new QualityIssueListResponse(
                                taskId, issues.stream().map(this::toDto).toList());
        }

        public ReviewResultResponse getReviewResult(String taskId) {
                requireTask(taskId);
                List<ReviewRecordDto> reviews = reviewRepository.findAllByTaskIdOrderByReviewIdAsc(taskId).stream()
                                .map(this::toDto)
                                .toList();
                return new ReviewResultResponse(taskId, reviews);
        }

        public DeliveryStatusResponse getDeliveryStatus(String orderId) {
                requireOrder(orderId);
                List<DeliveryRecordDto> records = deliveryRepository.findAllByOrderOrderIdOrderByDeliveryIdAsc(orderId)
                                .stream()
                                .map(this::toDto)
                                .toList();
                return new DeliveryStatusResponse(orderId, records);
        }

        // 订单总览聚合信息
        public OrderOverviewResponse getOrderOverview(String orderId) {
                Order order = requireOrder(orderId);
                List<TaskOverviewResponse> tasks = taskRepository.findAllByOrderOrderIdOrderByTaskIdAsc(orderId)
                                .stream()
                                .map(this::toOverview)
                                .toList();
                List<DeliveryRecordDto> deliveryRecords = deliveryRepository
                                .findAllByOrderOrderIdOrderByDeliveryIdAsc(orderId).stream()
                                .map(this::toDto)
                                .toList();
                return new OrderOverviewResponse(toDto(order), tasks, deliveryRecords);
        }

        // 任务内部的组合逻辑，将任务详情、生产进度、质检问题、审核结果、交付记录等信息聚合到一个响应对象中
        private TaskOverviewResponse toOverview(ProductionTask task) {
                String taskId = task.getTaskId();
                List<ProductionStepDto> steps = stepRepository.findAllByTaskTaskIdOrderBySequenceNumberAsc(taskId)
                                .stream()
                                .map(this::toDto)
                                .toList();
                Map<String, List<ReviewRecordDto>> reviewsByIssue = reviewRepository
                                .findAllByTaskIdOrderByReviewIdAsc(taskId).stream()
                                .collect(
                                                Collectors.groupingBy(
                                                                review -> review.getIssue().getIssueId(),
                                                                Collectors.mapping(this::toDto, Collectors.toList())));
                List<QualityIssueOverviewResponse> issues = issueRepository.findAllByTaskTaskIdOrderByIssueIdAsc(taskId)
                                .stream()
                                .map(
                                                issue -> new QualityIssueOverviewResponse(
                                                                toDto(issue),
                                                                reviewsByIssue.getOrDefault(
                                                                                issue.getIssueId(), List.of())))
                                .toList();
                return new TaskOverviewResponse(toDto(task), steps, issues);
        }

        private Order requireOrder(String orderId) {
                return orderRepository
                                .findById(orderId)
                                .orElseThrow(() -> new ResourceNotFoundException("order", orderId));
        }

        // 检查任务是否存在，不存在则抛出异常（检查任务存在，是为了区分 404 还是 200+[]）
        private ProductionTask requireTask(String taskId) {
                return taskRepository
                                .findById(taskId)
                                .orElseThrow(() -> new ResourceNotFoundException("task", taskId));
        }

        private OrderDto toDto(Order order) {
                return new OrderDto(order.getOrderId(), order.getProductType(), order.getStatus());
        }

        private ProductionTaskDto toDto(ProductionTask task) {
                return new ProductionTaskDto(
                                task.getTaskId(),
                                task.getOrder().getOrderId(),
                                task.getStatus(),
                                task.getVersion());
        }

        private ProductionStepDto toDto(ProductionStep step) {
                return new ProductionStepDto(
                                step.getStepId(),
                                step.getTask().getTaskId(),
                                step.getStepName(),
                                step.getSequenceNumber(),
                                step.getStatus());
        }

        private QualityIssueDto toDto(QualityIssue issue) {
                return new QualityIssueDto(
                                issue.getIssueId(),
                                issue.getTask().getTaskId(),
                                issue.getIssueType(),
                                issue.getStatus(),
                                issue.getDescription());
        }

        private ReviewRecordDto toDto(ReviewRecord review) {
                return new ReviewRecordDto(
                                review.getReviewId(),
                                review.getIssue().getIssueId(),
                                review.getStatus(),
                                review.getReviewComment());
        }

        private DeliveryRecordDto toDto(DeliveryRecord record) {
                return new DeliveryRecordDto(
                                record.getDeliveryId(), record.getOrder().getOrderId(), record.getStatus());
        }
}
