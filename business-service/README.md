# Business Service

Java 21 + Spring Boot 3.5 + Spring Data JPA + Flyway 的遥感数据产线业务服务。M0.2 已实现领域实体、统一状态、DTO、Repository 和 PostgreSQL 表结构，尚未提供订单业务 API 或固定演示数据。

使用 Docker 启动：

```bash
docker compose up --build business-service
```

使用本机 JDK/Maven 测试：

```bash
mvn --file business-service/pom.xml test
```

服务使用以下环境变量连接 PostgreSQL：

```text
SPRING_DATASOURCE_URL
SPRING_DATASOURCE_USERNAME
SPRING_DATASOURCE_PASSWORD
PORT
```

健康检查继续兼容 `GET /health`。
