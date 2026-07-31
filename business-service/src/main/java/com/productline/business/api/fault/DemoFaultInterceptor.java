package com.productline.business.api.fault;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.api.trace.TraceIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class DemoFaultInterceptor implements HandlerInterceptor {

    public static final String FAULT_HEADER = "X-Demo-Fault";
    public static final String DELAY_HEADER = "X-Demo-Delay-Ms";

    private static final String API_PREFIX = "/api/";
    private static final String TIMEOUT = "timeout";
    private static final String SERVER_ERROR = "server-error";
    private static final String INVALID_RESPONSE = "invalid-response";
    private static final String PERMISSION_DENIED = "permission-denied";
    private static final Logger LOGGER = LoggerFactory.getLogger(DemoFaultInterceptor.class);

    private final DemoFaultProperties properties;
    private final ObjectMapper objectMapper;

    public DemoFaultInterceptor(DemoFaultProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean preHandle(
            HttpServletRequest request,
            HttpServletResponse response,
            Object handler) throws IOException {
        if (!shouldSimulate(request)) {
            return true;
        }

        applyRequestedDelay(request.getHeader(DELAY_HEADER));
        String fault = request.getHeader(FAULT_HEADER);
        if (fault == null || fault.isBlank()) {
            return true;
        }

        String faultType = fault.trim();
        LOGGER.warn("Applying demo fault, type={}, path={}", faultType, request.getRequestURI());
        // 分派四种故障类型
        return switch (faultType) {
            case TIMEOUT -> simulateTimeout();
            case SERVER_ERROR -> throw new IllegalStateException("demo server fault");
            case INVALID_RESPONSE -> writeInvalidResponse(request, response);
            case PERMISSION_DENIED -> throw new PermissionDeniedException("demo permission denied");
            default -> throw new InvalidRequestException("unsupported X-Demo-Fault value");
        };
    }

    private boolean shouldSimulate(HttpServletRequest request) {
        return properties.enabled()
                && HttpMethod.GET.matches(request.getMethod())
                && request.getRequestURI().startsWith(API_PREFIX);
    }

    private void applyRequestedDelay(String value) {
        if (value == null) {
            return;
        }
        long delayMs;
        try {
            delayMs = Long.parseLong(value);
        } catch (NumberFormatException exception) {
            throw new InvalidRequestException("X-Demo-Delay-Ms must be an integer");
        }
        if (delayMs < 0 || delayMs > properties.maxDelayMs()) {
            throw new InvalidRequestException(
                    "X-Demo-Delay-Ms must be between 0 and " + properties.maxDelayMs());
        }
        sleep(delayMs);
    }

    private boolean simulateTimeout() {
        sleep(properties.timeoutDelayMs());
        return true;
    }

    private boolean writeInvalidResponse(
            HttpServletRequest request,
            HttpServletResponse response) throws IOException {
        ObjectNode body = objectMapper.createObjectNode();
        body.put("success", true);
        body.put("code", "SUCCESS");
        body.put("message", "success");
        body.put("trace_id", TraceIdFilter.currentTraceId(request));
        body.put("retryable", false);

        response.setStatus(HttpStatus.OK.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        objectMapper.writeValue(response.getOutputStream(), body);
        return false;
    }

    private void sleep(long delayMs) {
        try {
            Thread.sleep(delayMs);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("demo fault delay was interrupted", exception);
        }
    }
}
