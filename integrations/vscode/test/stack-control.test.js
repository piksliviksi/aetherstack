const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const test = require("node:test");

const { execFileResult, findStackRoot, installCliPackage, normalizeLocalUiUrl, request, requestStream, responseError, selectAvailableModels, startCompose } = require("../stack-control");

function makeStackRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-cli-install-"));
  fs.writeFileSync(path.join(root, "docker-compose.yml"), "");
  fs.writeFileSync(path.join(root, "litellm_config.yaml"), "");
  fs.mkdirSync(path.join(root, "aether-hub"));
  return root;
}

test("installCliPackage refuses a directory that isn't an AetherStack checkout", async () => {
  const notAStack = fs.mkdtempSync(path.join(os.tmpdir(), "not-a-stack-"));
  await assert.rejects(installCliPackage(notAStack), /Not an AetherStack installation/);
});

test("installCliPackage reports a clear error when integrations/cli is missing", async () => {
  const root = makeStackRoot();
  await assert.rejects(installCliPackage(root), /CLI package not found/);
});

test("command execution streams output without killing a cold pull at the capture limit", async () => {
  let streamedBytes = 0;
  const result = await execFileResult(
    process.execPath,
    ["-e", "process.stderr.write('x'.repeat(6 * 1024 * 1024))"],
    { onOutput: (chunk) => { streamedBytes += Buffer.byteLength(chunk); } }
  );
  assert.equal(result.code, 0);
  assert.equal(streamedBytes, 6 * 1024 * 1024);
  assert.ok(Buffer.byteLength(result.stderr) <= 4 * 1024 * 1024);
  assert.match(result.stderr, /earlier command output truncated; process continued/);
});

test("startCompose reports a clean Docker-missing message, not the raw script output", { skip: process.platform !== "win32" }, async () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-nodocker-"));
  fs.mkdirSync(path.join(temp, "aether-hub"), { recursive: true });
  fs.writeFileSync(path.join(temp, "docker-compose.yml"), "services: {}\n");
  fs.writeFileSync(path.join(temp, "litellm_config.yaml"), "model_list: []\n");
  fs.writeFileSync(
    path.join(temp, "start.ps1"),
    [
      'Write-Host "  AetherStack"',
      'Write-Host "  Multi-model LLM control plane"',
      'Write-Host "  ERROR: Docker not found. Install Docker Desktop:"',
      'Write-Host "  https://docs.docker.com/desktop/setup/install/windows-install/"',
      "exit 1",
    ].join("\n"),
  );
  try {
    await assert.rejects(
      startCompose(temp),
      (error) => error.message === "Docker was not found. Install Docker Desktop (or Docker Engine) and retry.",
    );
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});

test("findStackRoot walks up from a workspace nested in AetherStack", () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-extension-"));
  const nested = path.join(temp, "project", "nested");
  fs.mkdirSync(path.join(temp, "aether-hub"), { recursive: true });
  fs.mkdirSync(nested, { recursive: true });
  fs.writeFileSync(path.join(temp, "docker-compose.yml"), "services: {}\n");
  fs.writeFileSync(path.join(temp, "litellm_config.yaml"), "model_list: []\n");
  try {
    assert.equal(findStackRoot({ workspacePaths: [nested] }), temp);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});

test("selectAvailableModels only wires live, gateway-exposed chat models in matrix priority", () => {
  const matrix = {
    models: {
      "local-default": { available: true, capabilities: ["chat", "code"], tier: "local" },
      "cloud-ready": { available: true, capabilities: ["reason"], tier: "cloud" },
      offline: { available: false, capabilities: ["chat"], tier: "cloud" },
      embedding: { available: true, capabilities: ["embed"], tier: "local" },
    },
    routing: { fallbacks: { chat: ["offline", "local-default"], reason: ["cloud-ready"] } },
  };

  assert.deepEqual(
    selectAvailableModels(matrix, ["local-default", "cloud-ready", "offline", "embedding"]).map((model) => model.alias),
    ["local-default", "cloud-ready"]
  );
});

test("selectAvailableModels limits Continue presets to eight entries", () => {
  const models = {};
  for (let index = 0; index < 12; index += 1) {
    models[`model-${index}`] = { available: true, capabilities: ["chat"] };
  }
  assert.equal(selectAvailableModels({ models }, Object.keys(models)).length, 8);
});

test("selectAvailableModels excludes configured models that fail live provider health", () => {
  const matrix = {
    models: {
      local: { available: true, backend: "ollama/tinyllama", capabilities: ["chat"] },
      cloud: { available: true, backend: "openai/gpt-4.1", capabilities: ["chat"] },
    },
  };
  assert.deepEqual(
    selectAvailableModels(matrix, ["local", "cloud"], ["local"]).map((model) => model.alias),
    ["local"]
  );
});

test("normalizeLocalUiUrl strips stale routes and rejects non-local hosts", () => {
  assert.equal(normalizeLocalUiUrl("http://127.0.0.1:3000/error?detail=1#x"), "http://127.0.0.1:3000/");
  assert.equal(normalizeLocalUiUrl("https://example.com/error"), "http://127.0.0.1:3000/");
});

test("request returns HTTP status and parsed JSON without external dependencies", async () => {
  const http = require("http");
  const server = http.createServer((incoming, response) => {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ ok: true, path: incoming.url }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    const result = await request(`http://127.0.0.1:${address.port}/health`);
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, { ok: true, path: "/health" });
  } finally {
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  }
});

test("requestStream parses SSE events as they arrive", async () => {
  const http = require("http");
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write('data: {"type":"delta","text":"a"}\n\n');
    res.write('data: {"type":"delta","text":"b"}\n\n');
    res.write('data: {"type":"done","result":{"answer":"ab"}}\n\n');
    res.end();
  });
  await new Promise((resolve) => server.listen(0, resolve));
  const port = server.address().port;
  const events = [];
  await requestStream(`http://127.0.0.1:${port}/x`, { method: "POST", body: {} }, (event) => events.push(event));
  server.close();
  assert.deepEqual(events, [
    { type: "delta", text: "a" },
    { type: "delta", text: "b" },
    { type: "done", result: { answer: "ab" } },
  ]);
});

test("requestStream rejects on a non-2xx status", async () => {
  const http = require("http");
  const server = http.createServer((req, res) => {
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "boom" }));
  });
  await new Promise((resolve) => server.listen(0, resolve));
  const port = server.address().port;
  await assert.rejects(
    () => requestStream(`http://127.0.0.1:${port}/x`, { method: "POST", body: {} }, () => {}),
    /boom|HTTP 500/
  );
  server.close();
});

test("responseError preserves stable recovery metadata", () => {
  const error = responseError(
    503,
    { error: "A required service is unavailable.", code: "service_unavailable", request_id: "req-123" },
  );
  assert.equal(error.name, "AetherStackHttpError");
  assert.equal(error.status, 503);
  assert.equal(error.code, "service_unavailable");
  assert.equal(error.requestId, "req-123");
});

test("requestStream skips a malformed chunk without aborting the stream", async () => {
  const http = require("http");
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write('data: not valid json\n\n');
    res.write('data: {"type":"delta","text":"ok"}\n\n');
    res.write('data: {"type":"done","result":{"answer":"ok"}}\n\n');
    res.end();
  });
  await new Promise((resolve) => server.listen(0, resolve));
  const port = server.address().port;
  const events = [];
  await requestStream(`http://127.0.0.1:${port}/x`, { method: "POST", body: {} }, (event) => events.push(event));
  server.close();
  assert.deepEqual(events, [{ type: "delta", text: "ok" }, { type: "done", result: { answer: "ok" } }]);
});

test("requestStream rejects EOF without a terminal event", async () => {
  const http = require("http");
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream", "X-AetherStack-Request-ID": "req-stream" });
    res.write('data: {"type":"delta","text":"partial"}\n\n');
    res.end();
  });
  await new Promise((resolve) => server.listen(0, resolve));
  const port = server.address().port;
  await assert.rejects(
    () => requestStream(`http://127.0.0.1:${port}/x`, { method: "POST", body: {} }, () => {}),
    (error) => error.code === "stream_incomplete" && error.requestId === "req-stream"
  );
  server.close();
});

test("request sends bounded JSON POST bodies for Hub service runs", async () => {
  const http = require("http");
  let received = null;
  const server = http.createServer((incoming, response) => {
    let body = "";
    incoming.setEncoding("utf8");
    incoming.on("data", (chunk) => { body += chunk; });
    incoming.on("end", () => {
      received = { method: incoming.method, type: incoming.headers["content-type"], body: JSON.parse(body) };
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    const result = await request(`http://127.0.0.1:${address.port}/api/services/coding/run`, {
      method: "POST",
      body: { goal: "test" },
    });
    assert.equal(result.status, 200);
    assert.deepEqual(received, {
      method: "POST",
      type: "application/json",
      body: { goal: "test" },
    });
  } finally {
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  }
});

test("request cancellation closes an in-flight HTTP request", async () => {
  const http = require("http");
  const server = http.createServer(() => {});
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const controller = new AbortController();
    const pending = request(`http://127.0.0.1:${server.address().port}/wait`, { signal: controller.signal });
    controller.abort();
    await assert.rejects(pending, (error) => error.name === "AbortError" && error.code === "ABORT_ERR");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("stream cancellation closes an in-flight SSE request", async () => {
  const http = require("http");
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    response.write('data: {"type":"delta","text":"started"}\n\n');
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const controller = new AbortController();
    const pending = requestStream(
      `http://127.0.0.1:${server.address().port}/wait`,
      { signal: controller.signal },
      () => controller.abort(),
    );
    await assert.rejects(pending, (error) => error.name === "AbortError" && error.code === "ABORT_ERR");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
