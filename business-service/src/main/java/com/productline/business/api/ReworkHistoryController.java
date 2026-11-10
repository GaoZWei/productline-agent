package com.productline.business.api;

import com.productline.business.api.dto.ReworkHistoryResponse;
import com.productline.business.application.ReworkHistoryService;
import com.productline.business.domain.repository.ReworkHistoryRepository.Kind;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks/{taskId}/reworks/{reworkTaskId}")
public class ReworkHistoryController {
    private final ReworkHistoryService service;

    public ReworkHistoryController(ReworkHistoryService service) { this.service = service; }

    @GetMapping("/results")
    public ReworkHistoryResponse<?> results(@PathVariable String taskId, @PathVariable String reworkTaskId,
            @RequestHeader(value = "X-User-Id", required = false) String user,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestParam MultiValueMap<String, String> query) {
        return service.read(taskId, reworkTaskId, user, role, Kind.RESULTS, query);
    }

    @GetMapping("/inspections")
    public ReworkHistoryResponse<?> inspections(@PathVariable String taskId, @PathVariable String reworkTaskId,
            @RequestHeader(value = "X-User-Id", required = false) String user,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestParam MultiValueMap<String, String> query) {
        return service.read(taskId, reworkTaskId, user, role, Kind.INSPECTIONS, query);
    }

    @GetMapping("/reviews")
    public ReworkHistoryResponse<?> reviews(@PathVariable String taskId, @PathVariable String reworkTaskId,
            @RequestHeader(value = "X-User-Id", required = false) String user,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestParam MultiValueMap<String, String> query) {
        return service.read(taskId, reworkTaskId, user, role, Kind.REVIEWS, query);
    }
}
