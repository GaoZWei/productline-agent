package com.productline.business.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkStartRequest;
import com.productline.business.api.dto.ReworkWriteReceipt;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.application.ReworkStartService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks/{taskId}/reworks/{reworkTaskId}")
public class ReworkStartController {
    private final ReworkStartService service;
    private final ObjectMapper mapper;

    public ReworkStartController(ReworkStartService service, ObjectMapper mapper) {
        this.service = service;
        this.mapper = mapper;
    }

    @PostMapping("/start")
    public ReworkWriteReceipt start(@PathVariable String taskId, @PathVariable String reworkTaskId,
            @RequestHeader(value = "X-User-Id", required = false) String actor,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestHeader(value = "Idempotency-Key", required = false) String key,
            @RequestHeader(value = "Content-Type", required = false) String contentType,
            @RequestBody(required = false) String body) {
        try {
            if (contentType == null || !MediaType.APPLICATION_JSON.includes(MediaType.parseMediaType(contentType))) {
                throw new InvalidRequestException("start request requires application/json");
            }
        } catch (org.springframework.http.InvalidMediaTypeException exception) {
            throw new InvalidRequestException("start request requires application/json");
        }
        return service.start(taskId, reworkTaskId, actor, role, key, ReworkStartRequest.parse(body, mapper));
    }
}
