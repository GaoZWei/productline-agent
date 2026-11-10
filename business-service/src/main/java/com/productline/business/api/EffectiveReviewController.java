package com.productline.business.api;

import com.productline.business.api.dto.EffectiveReviewsResponse;
import com.productline.business.application.EffectiveReviewService;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class EffectiveReviewController {
    private final EffectiveReviewService service;

    public EffectiveReviewController(EffectiveReviewService service) { this.service = service; }

    @GetMapping("/api/tasks/{taskId}/effective-reviews")
    public EffectiveReviewsResponse read(@PathVariable String taskId,
            @RequestHeader(value = "X-User-Id", required = false) String user,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestParam MultiValueMap<String, String> query) {
        return service.read(taskId, user, role, query);
    }
}
