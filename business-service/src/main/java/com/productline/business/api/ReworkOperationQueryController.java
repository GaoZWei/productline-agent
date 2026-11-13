package com.productline.business.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.dto.ReworkOperationQueryRequest;
import com.productline.business.api.dto.ReworkOperationQueryResponse;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.application.ReworkOperationQueryService;
import org.springframework.http.MediaType;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tasks/{taskId}/reworks/operations/query")
public class ReworkOperationQueryController {
    private final ReworkOperationQueryService service;
    private final ObjectMapper mapper;

    public ReworkOperationQueryController(ReworkOperationQueryService service, ObjectMapper mapper) {
        this.service = service;
        this.mapper = mapper;
    }

    @PostMapping
    public ReworkOperationQueryResponse query(@PathVariable String taskId,
            @RequestHeader(value = "X-User-Id", required = false) String user,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestHeader(value = "Content-Type", required = false) String contentType,
            @RequestParam MultiValueMap<String, String> query,
            @RequestBody(required = false) String body) {
        if (!query.isEmpty()) throw new InvalidRequestException("operation query does not accept query parameters");
        try {
            if (contentType == null || !MediaType.APPLICATION_JSON.includes(MediaType.parseMediaType(contentType))) {
                throw new InvalidRequestException("operation query requires application/json");
            }
        } catch (org.springframework.http.InvalidMediaTypeException exception) {
            throw new InvalidRequestException("operation query requires application/json");
        }
        return service.query(taskId, user, role, ReworkOperationQueryRequest.parse(body, mapper));
    }
}
