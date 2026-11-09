package com.productline.business.support;

import java.net.URI;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;

public abstract class PostgresIntegrationTestSupport {

    private static final String NATIVE_URL = System.getProperty("business.test.jdbc-url");
    private static final PostgreSQLContainer<?> POSTGRES;

    static {
        if (NATIVE_URL == null) {
            POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine")
                    .withDatabaseName("business_service_test").withUsername("test").withPassword("test");
            POSTGRES.start();
        } else {
            // 无Docker时只允许显式提供的环回隔离测试库，禁止误迁移开发或运行库。
            URI address = URI.create(NATIVE_URL.startsWith("jdbc:") ? NATIVE_URL.substring(5) : "invalid:");
            if (!"postgresql".equals(address.getScheme())
                    || !("127.0.0.1".equals(address.getHost()) || "localhost".equals(address.getHost()))
                    || address.getPort() < 1 || address.getPort() > 65535
                    || address.getUserInfo() != null || address.getQuery() != null || address.getFragment() != null
                    || !address.getPath().matches("/business_service_test_[a-z0-9_]+")) {
                throw new IllegalArgumentException("native tests require an explicit loopback disposable test database");
            }
            POSTGRES = null;
        }
    }

    protected static String databaseUrl() {
        return NATIVE_URL == null ? POSTGRES.getJdbcUrl() : NATIVE_URL;
    }

    protected static String databaseUsername() {
        return NATIVE_URL == null ? POSTGRES.getUsername() : "test";
    }

    protected static String databasePassword() {
        return NATIVE_URL == null ? POSTGRES.getPassword() : "test";
    }

    @DynamicPropertySource
    static void configurePostgres(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", PostgresIntegrationTestSupport::databaseUrl);
        registry.add("spring.datasource.username", PostgresIntegrationTestSupport::databaseUsername);
        registry.add("spring.datasource.password", PostgresIntegrationTestSupport::databasePassword);
    }
}
