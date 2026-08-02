"use strict";

const http = require("http");
const https = require("https");
const { URL } = require("url");

const DEFAULT_BASE_URL = process.env.AETHERSTACK_HUB_URL || "http://127.0.0.1:8766";
const DEFAULT_TIMEOUT_MS = 15_000;
const STREAM_TIMEOUT_MS = 20 * 60_000;

function transportFor(url) {
  return url.protocol === "https:" ? https : http;
}

/** One JSON request/response — used for everything except the SSE run endpoints. */
function request(pathname, { method = "GET", body, baseUrl = DEFAULT_BASE_URL, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(pathname, baseUrl);
    const payload = body !== undefined ? Buffer.from(JSON.stringify(body)) : undefined;
    const req = transportFor(url).request(
      url,
      {
        method,
        headers: {
          "Content-Type": "application/json",
          ...(payload ? { "Content-Length": payload.length } : {}),
        },
        timeout: timeoutMs,
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let parsed;
          try {
            parsed = text ? JSON.parse(text) : {};
          } catch {
            parsed = { error: text || `HTTP ${res.statusCode}` };
          }
          if ((res.statusCode || 0) >= 400) {
            const err = new Error(parsed.error || `HTTP ${res.statusCode}`);
            err.status = res.statusCode;
            err.body = parsed;
            reject(err);
            return;
          }
          resolve(parsed);
        });
      }
    );
    req.on("timeout", () => req.destroy(new Error(`request to ${pathname} timed out`)));
    req.on("error", reject);
    if (payload) req.write(payload);
    req.end();
  });
}

/**
 * Reads a POST SSE stream (run/stream endpoints), calling onEvent for each
 * parsed `data:` chunk. Resolves once the connection closes. Mirrors the SSE
 * framing server.py's _send_sse_event() writes: `data: {...}\n\n`.
 */
function requestStream(pathname, { body, baseUrl = DEFAULT_BASE_URL, signal } = {}, onEvent) {
  return new Promise((resolve, reject) => {
    const url = new URL(pathname, baseUrl);
    const payload = Buffer.from(JSON.stringify(body || {}));
    const req = transportFor(url).request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          "Content-Length": payload.length,
        },
        timeout: STREAM_TIMEOUT_MS,
      },
      (res) => {
        if ((res.statusCode || 0) >= 400) {
          const chunks = [];
          res.on("data", (c) => chunks.push(c));
          res.on("end", () => {
            const text = Buffer.concat(chunks).toString("utf8");
            reject(new Error(text || `HTTP ${res.statusCode}`));
          });
          return;
        }
        let buffer = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          buffer += chunk;
          const lines = buffer.split("\n");
          buffer = lines.pop();
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            try {
              onEvent(JSON.parse(line.slice(5).trim()));
            } catch {
              /* skip a malformed chunk without aborting the stream */
            }
          }
        });
        res.on("end", resolve);
        res.on("error", reject);
      }
    );
    req.on("timeout", () => req.destroy(new Error(`stream to ${pathname} timed out`)));
    req.on("error", reject);
    if (signal) {
      if (signal.aborted) req.destroy(new Error("aborted"));
      else signal.addEventListener("abort", () => req.destroy(new Error("aborted")), { once: true });
    }
    req.write(payload);
    req.end();
  });
}

function listServices(opts) {
  return request("/api/services", opts).then((body) => body.services || []);
}

function getServiceGraph(serviceId, opts) {
  return request(`/api/services/${encodeURIComponent(serviceId)}/graph`, opts);
}

function saveServiceGraph(serviceId, graph, opts) {
  return request(`/api/services/${encodeURIComponent(serviceId)}/graph`, { ...opts, method: "POST", body: graph });
}

function saveGraph(graph, opts) {
  return request("/api/graphs", { ...opts, method: "POST", body: graph });
}

function runServiceStream(serviceId, event, onEvent, opts) {
  return requestStream(`/api/services/${encodeURIComponent(serviceId)}/run/stream`, { ...opts, body: event }, onEvent);
}

function runGraphStream(graph, event, onEvent, opts) {
  return requestStream("/api/graphs/run/stream", { ...opts, body: { graph, ...event } }, onEvent);
}

function cancelRun(runId, opts) {
  return request("/api/runs/cancel", { ...opts, method: "POST", body: { run_id: runId } });
}

function fromPresetScript(text, opts) {
  return request("/api/graphs/from-preset-script", { ...opts, method: "POST", body: { text } });
}

function toPresetScript(graph, opts) {
  return request("/api/graphs/to-preset-script", { ...opts, method: "POST", body: { graph } }).then((r) => r.text);
}

module.exports = {
  DEFAULT_BASE_URL,
  request,
  requestStream,
  listServices,
  getServiceGraph,
  saveServiceGraph,
  saveGraph,
  runServiceStream,
  runGraphStream,
  cancelRun,
  fromPresetScript,
  toPresetScript,
};
