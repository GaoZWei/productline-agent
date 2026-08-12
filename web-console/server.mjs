import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { readFile, stat } from "node:fs/promises";
import { dirname, extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = dirname(fileURLToPath(import.meta.url));
const defaultDistDirectory = join(moduleDirectory, "dist");

export function createWebServer({
  distDirectory = defaultDistDirectory,
  businessApiUrl = process.env.BUSINESS_API_URL ?? "http://localhost:8080",
  agentApiUrl = process.env.AGENT_API_URL ?? "http://localhost:8000",
} = {}) {
  return createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://web-console.local");

      if (url.pathname === "/health") {
        if (request.method !== "GET" && request.method !== "HEAD") {
          response.writeHead(405, { Allow: "GET, HEAD" }).end();
          return;
        }
        sendJson(response, 200, { service: "web-console", status: "UP" }, request.method);
        return;
      }

      if (url.pathname === "/business-api" || url.pathname.startsWith("/business-api/")) {
        proxyServiceRequest(request, response, businessApiUrl, "/business-api", "业务");
        return;
      }

      if (url.pathname === "/agent-api" || url.pathname.startsWith("/agent-api/")) {
        proxyServiceRequest(request, response, agentApiUrl, "/agent-api", "诊断");
        return;
      }

      if (request.method !== "GET" && request.method !== "HEAD") {
        response.writeHead(405, { Allow: "GET, HEAD" }).end();
        return;
      }

      await serveFrontend(url.pathname, request.method, response, distDirectory);
    } catch (error) {
      console.error("web request failed", error);
      if (!response.headersSent) {
        sendJson(response, 500, { code: "WEB_SERVER_ERROR", message: "Web 服务处理请求失败" });
      } else {
        response.destroy();
      }
    }
  });
}

async function serveFrontend(pathname, method, response, distDirectory) {
  const requestedPath = pathname === "/" ? "index.html" : pathname.slice(1);
  const candidate = normalize(join(distDirectory, requestedPath));
  const safeRoot = `${normalize(distDirectory)}${sep}`;
  const isSafePath = candidate.startsWith(safeRoot);
  const filePath = isSafePath && (await isFile(candidate)) ? candidate : join(distDirectory, "index.html");

  const body = await readFile(filePath);
  response.writeHead(200, {
    "Content-Type": contentType(filePath),
    "Content-Length": body.length,
    "Cache-Control": filePath.endsWith("index.html")
      ? "no-cache"
      : "public, max-age=31536000, immutable",
  });
  response.end(method === "HEAD" ? undefined : body);
}

function proxyServiceRequest(clientRequest, clientResponse, serviceUrl, prefix, serviceLabel) {
  const clientUrl = new URL(clientRequest.url ?? "/", "http://web-console.local");
  const upstreamPath = clientUrl.pathname.slice(prefix.length) || "/";
  const upstreamUrl = new URL(`${upstreamPath}${clientUrl.search}`, serviceUrl);
  const requestUpstream = upstreamUrl.protocol === "https:" ? httpsRequest : httpRequest;
  const headers = { ...clientRequest.headers, host: upstreamUrl.host };

  const upstreamRequest = requestUpstream(
    upstreamUrl,
    { method: clientRequest.method, headers },
    (upstreamResponse) => {
      clientResponse.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
      upstreamResponse.pipe(clientResponse);
    },
  );

  upstreamRequest.on("error", (error) => {
    console.error(`${serviceLabel} API proxy failed`, error.message);
    if (!clientResponse.headersSent) {
      sendJson(clientResponse, 502, unavailablePayload(prefix, serviceLabel));
    } else {
      clientResponse.destroy();
    }
  });

  clientRequest.pipe(upstreamRequest);
}

function unavailablePayload(prefix, serviceLabel) {
  const common = {
    code: "UPSTREAM_UNAVAILABLE",
    message: `${serviceLabel}服务暂时不可用`,
    trace_id: "web-proxy-unavailable",
    retryable: true,
  };
  if (prefix === "/agent-api") {
    return { run_id: null, ...common, error_step: null };
  }
  return { success: false, ...common, data: null };
}

function sendJson(response, status, value, method = "GET") {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  response.end(method === "HEAD" ? undefined : body);
}

async function isFile(path) {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
}

function contentType(path) {
  return (
    {
      ".css": "text/css; charset=utf-8",
      ".html": "text/html; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".json": "application/json; charset=utf-8",
      ".svg": "image/svg+xml",
      ".png": "image/png",
      ".ico": "image/x-icon",
    }[extname(path)] ?? "application/octet-stream"
  );
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const port = Number.parseInt(process.env.PORT ?? "5173", 10);
  createWebServer().listen(port, "0.0.0.0", () => {
    console.log(`web-console listening on 0.0.0.0:${port}`);
  });
}
