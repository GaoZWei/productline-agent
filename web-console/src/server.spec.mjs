import { createServer } from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { createWebServer } from "../server.mjs";

const servers = [];
const temporaryDirectories = [];

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => closeServer(server)));
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })),
  );
});

describe("production web server", () => {
  it("提供健康检查、SPA 回退并转发同源业务与诊断请求", async () => {
    const distDirectory = await mkdtemp(join(tmpdir(), "productline-web-"));
    temporaryDirectories.push(distDirectory);
    await writeFile(join(distDirectory, "index.html"), "<main>M0.8 page</main>");

    const upstreamRequests = [];
    const upstream = createServer((request, response) => {
      upstreamRequests.push({
        method: request.method,
        path: request.url,
        userId: request.headers["x-user-id"],
      });
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true }));
    });
    servers.push(upstream);
    const upstreamUrl = await listen(upstream);

    const web = createWebServer({
      distDirectory,
      businessApiUrl: upstreamUrl,
      agentApiUrl: upstreamUrl,
    });
    servers.push(web);
    const webUrl = await listen(web);

    const health = await fetch(`${webUrl}/health`);
    expect(await health.json()).toEqual({ service: "web-console", status: "UP" });

    const api = await fetch(`${webUrl}/business-api/api/orders/ORDER-003`);
    expect(api.status).toBe(200);
    expect(upstreamRequests[0]).toMatchObject({
      method: "GET",
      path: "/api/orders/ORDER-003",
    });

    const diagnosis = await fetch(`${webUrl}/agent-api/api/agent/order-diagnosis`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Id": "reviewer-001" },
      body: JSON.stringify({ order_id: "ORDER-003", user_message: "why" }),
    });
    expect(diagnosis.status).toBe(200);
    expect(upstreamRequests[1]).toEqual({
      method: "POST",
      path: "/api/agent/order-diagnosis",
      userId: "reviewer-001",
    });

    const fallback = await fetch(`${webUrl}/orders/ORDER-003`);
    expect(await fallback.text()).toContain("M0.8 page");
  });

  it("SSE上游不可用时返回事件流专用错误结构", async () => {
    const web = createWebServer({ agentApiUrl: "http://127.0.0.1:1" });
    servers.push(web);
    const webUrl = await listen(web);

    const response = await fetch(
      `${webUrl}/agent-api/api/agent/events/stream-proxy-unavailable`,
      {
        headers: {
          Accept: "text/event-stream",
          "X-User-Id": "reviewer-001",
          "X-User-Role": "REVIEWER",
        },
      },
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      stream_id: "stream-proxy-unavailable",
      trace_id: "web-proxy-unavailable",
      code: "UPSTREAM_UNAVAILABLE",
      message: "诊断服务暂时不可用",
    });
  });
});

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve(`http://127.0.0.1:${address.port}`);
    });
  });
}

function closeServer(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}
