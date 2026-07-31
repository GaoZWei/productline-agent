package com.productline.business.api.fault;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "demo.faults")
public record DemoFaultProperties(
        boolean enabled,
        long maxDelayMs,
        long timeoutDelayMs) {

    public DemoFaultProperties {
        if (maxDelayMs < 0 || maxDelayMs > 60_000) {
            throw new IllegalArgumentException("demo.faults.max-delay-ms must be between 0 and 60000");
        }
        if (timeoutDelayMs < 1 || timeoutDelayMs > 60_000) {
            throw new IllegalArgumentException(
                    "demo.faults.timeout-delay-ms must be between 1 and 60000");
        }
    }
}
