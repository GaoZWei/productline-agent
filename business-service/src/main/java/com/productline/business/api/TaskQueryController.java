package com.productline.business.api;

import com.productline.business.api.dto.ProductionProgressResponse;
import com.productline.business.api.dto.QualityIssueListResponse;
import com.productline.business.api.dto.ReviewResultResponse;
import com.productline.business.application.BusinessQueryService;
import com.productline.business.domain.dto.ProductionTaskDto;
import com.productline.business.domain.enums.QualityIssueStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks")
public class TaskQueryController {

    private final BusinessQueryService queryService;

    public TaskQueryController(BusinessQueryService queryService) {
        this.queryService = queryService;
    }

    @GetMapping("/{taskId}")
    public ProductionTaskDto getTask(@PathVariable String taskId) {
        return queryService.getTask(taskId);
    }

    @GetMapping("/{taskId}/progress")
    public ProductionProgressResponse getProductionProgress(@PathVariable String taskId) {
        return queryService.getProductionProgress(taskId);
    }

    // 查询质检问题列表
    @GetMapping("/{taskId}/quality-issues")
    public QualityIssueListResponse getQualityIssues(
            @PathVariable String taskId,
            @RequestParam(required = false) QualityIssueStatus status) {
        return queryService.getQualityIssues(taskId, status);
    }

    @GetMapping("/{taskId}/review")
    public ReviewResultResponse getReviewResult(@PathVariable String taskId) {
        return queryService.getReviewResult(taskId);
    }
}
