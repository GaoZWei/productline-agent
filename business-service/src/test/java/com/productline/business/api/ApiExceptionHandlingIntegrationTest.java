package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Import(ApiExceptionHandlingIntegrationTest.TestErrorController.class)
class ApiExceptionHandlingIntegrationTest extends PostgresIntegrationTestSupport {

    @LocalServerPort private int port;

    @Autowired private TestRestTemplate restTemplate;

    @Test
    void wrapsSuccessAndPropagatesCallerTraceId() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Trace-Id", "trace-client-001");

        ResponseEntity<JsonNode> response =
                exchange("/api/orders/ORDER-003", HttpMethod.GET, headers, null);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertEnvelope(response, true, "SUCCESS", false);
        assertThat(response.getHeaders().getFirst("X-Trace-Id"))
                .isEqualTo("trace-client-001");
        assertThat(response.getBody().path("trace_id").asText())
                .isEqualTo("trace-client-001");
        assertThat(response.getBody().path("data").path("orderId").asText())
                .isEqualTo("ORDER-003");
    }

    @Test
    void mapsParameterErrorsTo400() {
        ResponseEntity<JsonNode> response =
                exchange(
                        "/api/tasks/TASK-003/quality-issues?status=UNKNOWN",
                        HttpMethod.GET,
                        new HttpHeaders(),
                        null);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertEnvelope(response, false, "PARAM_VALIDATION_ERROR", false);
    }

    @Test
    void mapsBodyValidationAndMalformedJsonTo400() {
        HttpHeaders validationHeaders =
                writeHeaders("reviewer-001", "REVIEWER", "error-validation");
        Map<String, Object> invalidBody =
                Map.of(
                        "issueId", "ISSUE-001",
                        "status", "REWORK_REQUIRED",
                        "reviewComment", "",
                        "expectedVersion", 0);
        ResponseEntity<JsonNode> validation =
                exchange(
                        "/api/tasks/TASK-003/review",
                        HttpMethod.POST,
                        validationHeaders,
                        invalidBody);

        HttpHeaders malformedHeaders =
                writeHeaders("reviewer-001", "REVIEWER", "error-json");
        malformedHeaders.setContentType(MediaType.APPLICATION_JSON);
        ResponseEntity<JsonNode> malformed =
                restTemplate.exchange(
                        "http://127.0.0.1:"
                                + port
                                + "/api/tasks/TASK-003/review",
                        HttpMethod.POST,
                        new HttpEntity<>("{not-json", malformedHeaders),
                        JsonNode.class);

        assertThat(validation.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertEnvelope(validation, false, "PARAM_VALIDATION_ERROR", false);
        assertThat(malformed.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertEnvelope(malformed, false, "PARAM_VALIDATION_ERROR", false);
    }

    @Test
    void mapsMissingIdentityTo401AndPermissionFailureTo403() {
        HttpHeaders unauthenticatedHeaders = writeHeaders(null, "REVIEWER", "error-auth");
        HttpHeaders forbiddenHeaders = writeHeaders("reviewer-001", "VIEWER", "error-role");
        Map<String, Object> body = reviewBody(0);

        ResponseEntity<JsonNode> unauthenticated =
                exchange(
                        "/api/tasks/TASK-003/review",
                        HttpMethod.POST,
                        unauthenticatedHeaders,
                        body);
        ResponseEntity<JsonNode> forbidden =
                exchange(
                        "/api/tasks/TASK-003/review",
                        HttpMethod.POST,
                        forbiddenHeaders,
                        body);

        assertThat(unauthenticated.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertEnvelope(unauthenticated, false, "PERMISSION_DENIED", false);
        assertThat(forbidden.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        assertEnvelope(forbidden, false, "PERMISSION_DENIED", false);
    }

    @Test
    void mapsUnknownResourceTo404WithGeneratedTraceId() {
        ResponseEntity<JsonNode> response =
                exchange("/api/orders/ORDER-404", HttpMethod.GET, new HttpHeaders(), null);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertEnvelope(response, false, "RESOURCE_NOT_FOUND", false);
        String responseTrace = response.getHeaders().getFirst("X-Trace-Id");
        assertThat(responseTrace).startsWith("trace-");
        assertThat(response.getBody().path("trace_id").asText()).isEqualTo(responseTrace);
    }

    @Test
    void replacesUnsafeCallerTraceId() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Trace-Id", "unsafe trace id");

        ResponseEntity<JsonNode> response =
                exchange("/api/orders/ORDER-003", HttpMethod.GET, headers, null);

        String responseTrace = response.getHeaders().getFirst("X-Trace-Id");
        assertThat(responseTrace).startsWith("trace-");
        assertThat(responseTrace).isNotEqualTo("unsafe trace id");
        assertThat(response.getBody().path("trace_id").asText()).isEqualTo(responseTrace);
    }

    @Test
    void mapsBusinessConflictTo409() {
        ResponseEntity<JsonNode> response =
                exchange(
                        "/api/tasks/TASK-003/review",
                        HttpMethod.POST,
                        writeHeaders("reviewer-001", "REVIEWER", "error-conflict"),
                        reviewBody(99));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertEnvelope(response, false, "BUSINESS_CONFLICT", false);
    }

    @Test
    void hidesSystemExceptionDetailsAndKeeps500NonRetryable() {
        ResponseEntity<JsonNode> response =
                exchange("/api/test/system-error", HttpMethod.GET, new HttpHeaders(), null);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertEnvelope(response, false, "INTERNAL_SERVER_ERROR", false);
        assertThat(response.getBody().path("message").asText())
                .isEqualTo("internal server error");
        assertThat(response.getBody().toString()).doesNotContain("test-sensitive-detail");
    }

    private ResponseEntity<JsonNode> exchange(
            String path, HttpMethod method, HttpHeaders headers, Object body) {
        if (body != null) {
            headers.setContentType(MediaType.APPLICATION_JSON);
        }
        return restTemplate.exchange(
                "http://127.0.0.1:" + port + path,
                method,
                new HttpEntity<>(body, headers),
                JsonNode.class);
    }

    private HttpHeaders writeHeaders(String userId, String role, String idempotencyKey) {
        HttpHeaders headers = new HttpHeaders();
        if (userId != null) {
            headers.set("X-User-Id", userId);
        }
        headers.set("X-User-Role", role);
        headers.set("Idempotency-Key", idempotencyKey);
        return headers;
    }

    private Map<String, Object> reviewBody(long expectedVersion) {
        return Map.of(
                "issueId", "ISSUE-001",
                "status", "REWORK_REQUIRED",
                "reviewComment", "统一异常测试。",
                "expectedVersion", expectedVersion);
    }

    private void assertEnvelope(
            ResponseEntity<JsonNode> response,
            boolean success,
            String code,
            boolean retryable) {
        JsonNode body = response.getBody();
        assertThat(body.path("success").asBoolean()).isEqualTo(success);
        assertThat(body.path("code").asText()).isEqualTo(code);
        assertThat(body.path("message").asText()).isNotBlank();
        assertThat(body.has("data")).isTrue();
        assertThat(body.path("trace_id").asText()).isNotBlank();
        assertThat(body.path("retryable").asBoolean()).isEqualTo(retryable);
    }

    @RestController
    static class TestErrorController {

        @GetMapping("/api/test/system-error")
        Map<String, Object> systemError() {
            throw new IllegalStateException("test-sensitive-detail");
        }
    }
}
