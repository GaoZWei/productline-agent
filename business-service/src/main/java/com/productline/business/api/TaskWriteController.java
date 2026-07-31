package com.productline.business.api;

import com.productline.business.api.dto.ReviewSubmissionRequest;
import com.productline.business.api.dto.ReviewWriteResponse;
import com.productline.business.api.dto.ReworkCreationRequest;
import com.productline.business.api.dto.ReworkWriteResponse;
import com.productline.business.application.BusinessWriteService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks")
public class TaskWriteController {

    private final BusinessWriteService writeService;

    public TaskWriteController(BusinessWriteService writeService) {
        this.writeService = writeService;
    }

    // 提交复核结果（必须带用户id、角色、幂等键）
    @PostMapping("/{taskId}/review")
    public ReviewWriteResponse submitReview(
            @PathVariable String taskId,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-User-Role", required = false) String userRole,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @Valid @RequestBody ReviewSubmissionRequest request) {
        return writeService.submitReview(
                taskId, userId, userRole, idempotencyKey, request);
    }

    // 创建返工任务（必须带用户id、角色、幂等键）
    @PostMapping("/{taskId}/rework")
    public ReworkWriteResponse createRework(
            @PathVariable String taskId,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-User-Role", required = false) String userRole,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @Valid @RequestBody ReworkCreationRequest request) {
        return writeService.createRework(
                taskId, userId, userRole, idempotencyKey, request);
    }
}
