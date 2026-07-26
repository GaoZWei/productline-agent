import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

/**
 * Dependency-free M0.1 entry point.
 *
 * <p>The Spring Boot application and domain APIs are introduced by later M0 tasks.
 */
public final class Main {
    private static final byte[] HEALTH_BODY =
            "{\"service\":\"business-service\",\"status\":\"UP\"}"
                    .getBytes(StandardCharsets.UTF_8);

    private Main() {
    }

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        server.createContext("/health", Main::handleHealth);     // 注册 health 接口
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor()); // 使用 JDK 21 虚拟线程执行请求
        server.start();
        System.out.printf("business-service listening on 0.0.0.0:%d%n", port);
    }

    private static void handleHealth(HttpExchange exchange) throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {    // 非 GET 请求返回 405 Not Allowed */
            exchange.sendResponseHeaders(405, -1);
            exchange.close();
            return;
        }

        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, HEALTH_BODY.length);
        exchange.getResponseBody().write(HEALTH_BODY);
        exchange.close();
    }
}

