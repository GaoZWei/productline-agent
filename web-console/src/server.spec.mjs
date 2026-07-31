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
  it("提供健康检查、SPA 回退并将同源业务请求转发给 Java", async () => {
    const distDirectory = await mkdtemp(join(tmpdir(), "productline-web-"));
    temporaryDirectories.push(distDirectory);
    await writeFile(join(distDirectory, "index.html"), "<main>M0.8 page</main>");

    let upstreamPath;
    const upstream = createServer((request, response) => {
      upstreamPath = request.url;
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true }));
    });
    servers.push(upstream);
    const upstreamUrl = await listen(upstream);

    const web = createWebServer({ distDirectory, businessApiUrl: upstreamUrl });
    servers.push(web);
    const webUrl = await listen(web);

    const health = await fetch(`${webUrl}/health`);
    expect(await health.json()).toEqual({ service: "web-console", status: "UP" });

    const api = await fetch(`${webUrl}/business-api/api/orders/ORDER-003`);
    expect(api.status).toBe(200);
    expect(upstreamPath).toBe("/api/orders/ORDER-003");

    const fallback = await fetch(`${webUrl}/orders/ORDER-003`);
    expect(await fallback.text()).toContain("M0.8 page");
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
