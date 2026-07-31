package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.productline.business.support.PostgresIntegrationTestSupport;
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
        properties = "demo.faults.enabled=false")
class DemoFaultDisabledIntegrationTest extends PostgresIntegrationTestSupport {

    @LocalServerPort private int port;

    @Autowired private TestRestTemplate restTemplate;

    @Test
    void ignoresFaultHeadersWhenSimulationIsDisabled() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Demo-Fault", "server-error");
        headers.set("X-Demo-Delay-Ms", "999999");

        ResponseEntity<JsonNode> response =
                restTemplate.exchange(
                        "http://127.0.0.1:" + port + "/api/orders/ORDER-003",
                        HttpMethod.GET,
                        new HttpEntity<>(headers),
                        JsonNode.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().path("data").path("orderId").asText())
                .isEqualTo("ORDER-003");
    }
}
