package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpTimeoutException;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
            "demo.faults.enabled=true",
            "demo.faults.max-delay-ms=300",
            "demo.faults.timeout-delay-ms=300"
        })
class DemoFaultSimulationIntegrationTest extends PostgresIntegrationTestSupport {

    private static final String ORDER_PATH = "/api/orders/ORDER-003";

    @LocalServerPort private int port;

    @Autowired private TestRestTemplate restTemplate;

    @Test
    void delaysResponseByRequestedBoundedDuration() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Demo-Delay-Ms", "120");

        long startedAt = System.nanoTime();
        ResponseEntity<JsonNode> response = get(ORDER_PATH, headers);
        long elapsedMillis = Duration.ofNanos(System.nanoTime() - startedAt).toMillis();

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().path("data").path("orderId").asText())
                .isEqualTo("ORDER-003");
        assertThat(elapsedMillis).isGreaterThanOrEqualTo(100);
    }

    @Test
    void keepsConnectionOpenLongEnoughForClientTimeout() {
        HttpRequest request =
                HttpRequest.newBuilder(uri(ORDER_PATH))
                        .header("X-Demo-Fault", "timeout")
                        .timeout(Duration.ofMillis(80))
                        .GET()
                        .build();

        try (HttpClient client = HttpClient.newHttpClient()) {
            assertThatThrownBy(
                            () ->
                                    client.send(
                                            request,
                                            HttpResponse.BodyHandlers.discarding()))
                    .isInstanceOf(HttpTimeoutException.class);
        }
    }

    @Test
    void returnsTraceableUnified500ForServerFault() {
        HttpHeaders headers = faultHeaders("server-error", "trace-demo-server-error");

        ResponseEntity<JsonNode> response = get(ORDER_PATH, headers);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertEnvelope(response, "INTERNAL_SERVER_ERROR");
        assertThat(response.getBody().path("trace_id").asText())
                .isEqualTo("trace-demo-server-error");
        assertThat(response.getBody().path("retryable").asBoolean()).isFalse();
    }

    @Test
    void returnsParseableSuccessBodyWithRequiredDataFieldMissing() {
        HttpHeaders headers = faultHeaders("invalid-response", "trace-demo-invalid-response");

        ResponseEntity<JsonNode> response = get(ORDER_PATH, headers);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().path("success").asBoolean()).isTrue();
        assertThat(response.getBody().path("code").asText()).isEqualTo("SUCCESS");
        assertThat(response.getBody().has("data")).isFalse();
        assertThat(response.getBody().path("trace_id").asText())
                .isEqualTo("trace-demo-invalid-response");
    }

    @Test
    void returnsUnified403ForPermissionFault() {
        HttpHeaders headers = faultHeaders("permission-denied", "trace-demo-permission");

        ResponseEntity<JsonNode> response = get(ORDER_PATH, headers);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        assertEnvelope(response, "PERMISSION_DENIED");
        assertThat(response.getBody().path("trace_id").asText())
                .isEqualTo("trace-demo-permission");
    }

    @Test
    void rejectsUnknownFaultAndInvalidDelayAsParameterErrors() {
        ResponseEntity<JsonNode> unknownFault =
                get(ORDER_PATH, faultHeaders("unknown-fault", "trace-demo-unknown"));
        HttpHeaders invalidDelayHeaders = new HttpHeaders();
        invalidDelayHeaders.set("X-Demo-Delay-Ms", "301");
        ResponseEntity<JsonNode> invalidDelay = get(ORDER_PATH, invalidDelayHeaders);

        assertThat(unknownFault.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertEnvelope(unknownFault, "PARAM_VALIDATION_ERROR");
        assertThat(invalidDelay.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertEnvelope(invalidDelay, "PARAM_VALIDATION_ERROR");
    }

    @Test
    void neverInjectsFaultIntoWriteRequests() {
        HttpHeaders headers = faultHeaders("server-error", "trace-demo-write");
        headers.set("X-User-Role", "REVIEWER");
        headers.set("Idempotency-Key", "demo-fault-write-safety");
        Map<String, Object> body =
                Map.of(
                        "issueId", "ISSUE-001",
                        "status", "REWORK_REQUIRED",
                        "reviewComment", "故障模拟不得进入写接口。",
                        "expectedVersion", 0);

        ResponseEntity<JsonNode> response =
                restTemplate.exchange(
                        uri("/api/tasks/TASK-003/review"),
                        HttpMethod.POST,
                        new HttpEntity<>(body, headers),
                        JsonNode.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertEnvelope(response, "PERMISSION_DENIED");
    }

    private ResponseEntity<JsonNode> get(String path, HttpHeaders headers) {
        return restTemplate.exchange(
                uri(path), HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);
    }

    private HttpHeaders faultHeaders(String fault, String traceId) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Demo-Fault", fault);
        headers.set("X-Trace-Id", traceId);
        return headers;
    }

    private URI uri(String path) {
        return URI.create("http://127.0.0.1:" + port + path);
    }

    private void assertEnvelope(ResponseEntity<JsonNode> response, String code) {
        JsonNode body = response.getBody();
        assertThat(body.path("success").asBoolean()).isFalse();
        assertThat(body.path("code").asText()).isEqualTo(code);
        assertThat(body.path("message").asText()).isNotBlank();
        assertThat(body.has("data")).isTrue();
        assertThat(body.path("retryable").asBoolean()).isFalse();
        assertThat(response.getHeaders().getFirst("X-Trace-Id"))
                .isEqualTo(body.path("trace_id").asText());
    }
}
