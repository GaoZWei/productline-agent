# Business Service

M0.1 提供的 Java 可启动骨架。它只暴露 `/health`，不包含领域模型、数据库访问或订单接口。Spring Boot 工程和业务能力将在后续 M0 任务中引入。

使用 Docker 启动：

```bash
docker compose up --build business-service
```

使用本机 JDK 启动：

```bash
cd business-service
javac --release 21 -d out src/Main.java
PORT=8080 java --add-modules jdk.httpserver -cp out Main
```

