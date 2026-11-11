package com.productline.business.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkInterruptionRequest;
import com.productline.business.api.dto.ReworkLifecycleCreationRequest;
import com.productline.business.api.dto.ReworkWriteReceipt;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.application.ReworkCreationService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks/{taskId}/reworks")
public class ReworkCreationController {
    private final ReworkCreationService service;
    private final ObjectMapper mapper;

    public ReworkCreationController(ReworkCreationService service, ObjectMapper mapper) {
        this.service = service;
        this.mapper = mapper;
    }

    @PostMapping
    public ReworkWriteReceipt first(@PathVariable String taskId,
            @RequestHeader(value = "X-User-Id", required = false) String actor,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestHeader(value = "Idempotency-Key", required = false) String key,
            @RequestHeader(value = "Content-Type", required = false) String contentType,
            @RequestBody(required = false) String body) {
        requireJson(contentType);
        return service.first(taskId, actor, role, key, ReworkLifecycleCreationRequest.parse(body, mapper));
    }

    @PostMapping("/{reworkTaskId}/next-round")
    public ReworkWriteReceipt next(@PathVariable String taskId, @PathVariable String reworkTaskId,
            @RequestHeader(value = "X-User-Id", required = false) String actor,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestHeader(value = "Idempotency-Key", required = false) String key,
            @RequestHeader(value = "Content-Type", required = false) String contentType,
            @RequestBody(required = false) String body) {
        requireJson(contentType);
        return service.next(taskId, reworkTaskId, actor, role, key, ReworkInterruptionRequest.parse(body, mapper));
    }

    private void requireJson(String contentType) {
        try {
            if (contentType == null || !MediaType.APPLICATION_JSON.includes(MediaType.parseMediaType(contentType))) {
                throw new InvalidRequestException("creation request requires application/json");
            }
        } catch (org.springframework.http.InvalidMediaTypeException exception) {
            throw new InvalidRequestException("creation request requires application/json");
        }
    }
}
