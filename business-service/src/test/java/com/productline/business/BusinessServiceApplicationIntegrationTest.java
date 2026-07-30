package com.productline.business;

import static org.assertj.core.api.Assertions.assertThat;

import com.productline.business.support.PostgresIntegrationTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class BusinessServiceApplicationIntegrationTest extends PostgresIntegrationTestSupport {

    @LocalServerPort private int port;

    @Autowired private TestRestTemplate restTemplate;

    @Test
    void exposesHealthAtTheM01CompatiblePath() {
        String body =
                restTemplate.getForObject(
                        "http://127.0.0.1:" + port + "/health",
                        String.class);

        assertThat(body).contains("\"status\":\"UP\"");
    }
}
