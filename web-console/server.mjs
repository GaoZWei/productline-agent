import { createServer } from "node:http";
import { readFile } from "node:fs/promises";

const port = Number.parseInt(process.env.PORT ?? "5173", 10);
const indexUrl = new URL("./src/index.html", import.meta.url);

const server = createServer(async (request, response) => {
  if (request.method !== "GET") {
    response.writeHead(405).end();
    return;
  }

  if (request.url === "/health") {
    const body = JSON.stringify({ service: "web-console", status: "UP" });
    response.writeHead(200, {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
    });
    response.end(body);
    return;
  }

  if (request.url === "/") {
    const body = await readFile(indexUrl);
    response.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Length": body.length,
    });
    response.end(body);
    return;
  }

  response.writeHead(404).end();
});

server.listen(port, "0.0.0.0", () => {
  console.log(`web-console listening on 0.0.0.0:${port}`);
});

