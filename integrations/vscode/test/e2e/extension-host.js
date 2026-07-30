const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const vscode = require("vscode");

function request(url, { method = "GET", headers = {}, body = null, timeoutMs = 10_000 } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { method, headers, timeout: timeoutMs }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.once("end", () => resolve({
        status: response.statusCode || 0,
        body: Buffer.concat(chunks).toString("utf8"),
      }));
    });
    req.once("error", reject);
    req.once("timeout", () => req.destroy(new Error(`timed out after ${timeoutMs} ms`)));
    if (body) req.write(body);
    req.end();
  });
}

async function checkEndpoints(endpoints) {
  const statuses = Object.fromEntries(
    await Promise.all(endpoints.map(async (url) => [url, (await request(url)).status]))
  );
  for (const [url, status] of Object.entries(statuses)) {
    assert.ok(status >= 200 && status < 400, `${url} returned HTTP ${status}`);
  }
  return statuses;
}

function envValue(stackPath, key) {
  const envPath = path.join(stackPath, ".env");
  const line = fs.readFileSync(envPath, "utf8")
    .split(/\r?\n/)
    .filter((candidate) => new RegExp(`^\\s*${key}\\s*=`).test(candidate))
    .at(-1);
  if (!line) return "";
  return line.split("=", 2)[1].trim().replace(/^['"]|['"]$/g, "");
}

function ollamaHostUrl(stackPath) {
  const configured = process.env.OLLAMA_BASE_URL || envValue(stackPath, "OLLAMA_BASE_URL") || "http://host.docker.internal:11434";
  if (/^https?:\/\/ollama(?::11434)?\/?$/i.test(configured)) {
    const port = process.env.AETHER_OLLAMA_PORT || envValue(stackPath, "AETHER_OLLAMA_PORT") || "11434";
    return { url: `http://127.0.0.1:${port}`, managedContainer: true };
  }
  return {
    url: configured
      .replace("host.docker.internal", "127.0.0.1")
      .replace("gateway.docker.internal", "127.0.0.1")
      .replace(/\/$/, ""),
    managedContainer: false,
  };
}

async function proveInference(stackPath) {
  const apiKey = envValue(stackPath, "LITELLM_MASTER_KEY") || "sk-aether-local";
  const payload = JSON.stringify({
    model: "local-default",
    messages: [{ role: "user", content: "Reply with exactly AETHERSTACK_ONE_CLICK_OK" }],
    temperature: 0,
    max_tokens: 32,
  });
  const completion = await request("http://127.0.0.1:4000/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(payload),
    },
    body: payload,
    timeoutMs: 5 * 60_000,
  });
  assert.equal(completion.status, 200, `real inference returned HTTP ${completion.status}: ${completion.body.slice(0, 500)}`);
  const parsed = JSON.parse(completion.body);
  const content = parsed.choices?.[0]?.message?.content?.trim() || "";
  assert.match(content, /AETHERSTACK_ONE_CLICK_OK/, `real inference returned an unexpected answer: ${content}`);

  const ollama = ollamaHostUrl(stackPath);
  const loadedResponse = await request(`${ollama.url}/api/ps`, { timeoutMs: 30_000 });
  assert.equal(loadedResponse.status, 200, `Ollama process inspection returned HTTP ${loadedResponse.status}`);
  const loaded = JSON.parse(loadedResponse.body).models || [];
  assert.ok(loaded.length > 0, "Ollama did not report a loaded model after inference");

  if (process.env.AETHERSTACK_E2E_REQUIRE_ACCELERATOR === "1") {
    assert.equal(process.platform, "darwin", "accelerator proof is currently defined for native macOS");
    assert.equal(process.arch, "arm64", "Metal proof requires an Apple Silicon VS Code process");
    assert.equal(ollama.managedContainer, false, "Metal proof requires host Ollama, not the Docker CPU fallback");
    assert.ok(
      loaded.some((model) => Number(model.size_vram || 0) > 0),
      `Ollama reported no GPU-resident model memory: ${JSON.stringify(loaded)}`
    );
  }

  return {
    requestedModel: "local-default",
    returnedModel: parsed.model || "",
    content,
    usage: parsed.usage || null,
    ollamaUrl: ollama.url,
    managedContainer: ollama.managedContainer,
    loadedModels: loaded.map((model) => ({
      name: model.name || model.model || "",
      size: Number(model.size || 0),
      sizeVram: Number(model.size_vram || 0),
    })),
    platform: {
      os: process.platform,
      arch: process.arch,
      release: os.release(),
      cpu: os.cpus()[0]?.model || "unknown",
    },
  };
}

async function run() {
  const expectedVersion = process.env.AETHERSTACK_E2E_VERSION;
  const resultPath = process.env.AETHERSTACK_E2E_RESULT;
  assert.ok(expectedVersion, "AETHERSTACK_E2E_VERSION is required");
  assert.ok(resultPath, "AETHERSTACK_E2E_RESULT is required");

  const startedAt = Date.now();
  const extension = vscode.extensions.getExtension("aetherstack.aetherstack");
  assert.ok(extension, "the packaged AetherStack extension was not discovered");
  assert.equal(extension.packageJSON.version, expectedVersion);
  await extension.activate();
  assert.equal(extension.isActive, true);

  if (process.env.AETHERSTACK_E2E_CHAT_ONLY === "1") {
    await vscode.commands.executeCommand("aetherstack.openChatEditor");
    await new Promise((resolve) => setTimeout(resolve, 1_000));
    const chatTab = vscode.window.tabGroups.all
      .flatMap((group) => group.tabs)
      .find((tab) => tab.label === "AetherStack Chat")?.label;
    assert.equal(chatTab, "AetherStack Chat", "AetherStack Chat editor did not open");
    fs.mkdirSync(path.dirname(resultPath), { recursive: true });
    fs.writeFileSync(resultPath, JSON.stringify({
      version: extension.packageJSON.version,
      extensionPath: extension.extensionPath,
      chatTab,
      durationMs: Date.now() - startedAt,
    }, null, 2));
    const holdMs = Number(process.env.AETHERSTACK_E2E_HOLD_MS || 0);
    if (holdMs > 0) await new Promise((resolve) => setTimeout(resolve, holdMs));
    return;
  }

  await vscode.commands.executeCommand("aetherstack.startAll");

  const endpoints = [
    "http://127.0.0.1:3000/",
    "http://127.0.0.1:4000/health/liveliness",
    "http://127.0.0.1:8766/api/health",
  ];
  const statuses = await checkEndpoints(endpoints);
  let restartStatuses;
  if (process.env.AETHERSTACK_E2E_RESTART === "1") {
    await vscode.commands.executeCommand("aetherstack.restartAll");
    restartStatuses = await checkEndpoints(endpoints);
  }

  const configuration = vscode.workspace.getConfiguration("aetherstack");
  const stackPath = configuration.get("stackPath");
  assert.ok(stackPath, "startAll did not persist the managed Runtime path");
  assert.ok(fs.existsSync(path.join(stackPath, "docker-compose.yml")));
  const installedVersion = fs.readFileSync(path.join(stackPath, "VERSION"), "utf8").trim();
  assert.strictEqual(installedVersion, expectedVersion, "managed Runtime version does not match the extension");
  const inference = await proveInference(stackPath);

  let chatTab;
  if (process.env.AETHERSTACK_E2E_CHAT === "1") {
    await vscode.commands.executeCommand("aetherstack.openChatEditor");
    await new Promise((resolve) => setTimeout(resolve, 1_000));
    chatTab = vscode.window.tabGroups.all
      .flatMap((group) => group.tabs)
      .find((tab) => tab.label === "AetherStack Chat")?.label;
    assert.equal(chatTab, "AetherStack Chat", "AetherStack Chat editor did not open");
  }

  let stopped = false;
  if (process.env.AETHERSTACK_E2E_STOP === "1") {
    await vscode.commands.executeCommand("aetherstack.stopAll");
    stopped = true;
  }

  fs.mkdirSync(path.dirname(resultPath), { recursive: true });
  fs.writeFileSync(
    resultPath,
    JSON.stringify(
      {
        version: extension.packageJSON.version,
        extensionPath: extension.extensionPath,
        stackPath,
        statuses,
        restartStatuses,
        inference,
        chatTab,
        stopped,
        durationMs: Date.now() - startedAt,
      },
      null,
      2
    )
  );
}

module.exports = { run };
