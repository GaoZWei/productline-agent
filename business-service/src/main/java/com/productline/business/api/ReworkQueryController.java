package com.productline.business.api;

import com.productline.business.api.dto.ReworkDetailResponse;
import com.productline.business.application.ReworkQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks/{taskId}/reworks")
public class ReworkQueryController {
    private final ReworkQueryService queryService;

    public ReworkQueryController(ReworkQueryService queryService) {
        this.queryService = queryService;
    }

    @GetMapping("/{reworkTaskId}")
    public ReworkDetailResponse getDetail(@PathVariable String taskId, @PathVariable String reworkTaskId,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-User-Role", required = false) String userRole) {
        return queryService.getDetail(taskId, reworkTaskId, userId, userRole);
    }
}
