"use strict";

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { execFile, spawn } = require("child_process");

const DEFAULT_PORT = 8767;
const MAX_BODY_BYTES = 512 * 1024;
const MAX_PROMPT_CHARS = 100_000;
const COMMAND_TIMEOUT_MS = 180_000;

const CLI_DEFINITIONS = {
  "codex-cli": {
    command: "codex",
    label: "Codex CLI",
    provider: "codex-cli",
    capabilities: ["chat", "code", "reason", "tools", "long_context"],
  },
  "claude-cli": {
    command: "claude",
    label: "Claude CLI",
    provider: "claude-cli",
    capabilities: ["chat", "code", "reason", "tools", "long_context", "vision"],
  },
  "grok-cli": {
    command: "grok",
    label: "Grok CLI",
    provider: "grok-cli",
    capabilities: ["chat", "code", "reason", "tools", "long_context"],
  },
};

function execResult(file, args, options = {}) {
  return new Promise((resolve) => {
    execFile(
      file,
      args,
      { windowsHide: true, timeout: options.timeout || 15_000, maxBuffer: 1024 * 1024, cwd: options.cwd },
      (error, stdout, stderr) => resolve({
        ok: !error,
        code: error ? error.code : 0,
        stdout: String(stdout || ""),
        stderr: String(stderr || ""),
      })
    );
  });
}

async function resolveCommand(command) {
  const locator = process.platform === "win32" ? "where.exe" : "which";
  const result = await execResult(locator, [command]);
  if (!result.ok) return null;
  const candidates = result.stdout.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  if (process.platform !== "win32") return candidates[0] || null;
  const executable = candidates.find((value) => /\.exe$/i.test(value));
  if (executable) return executable;
  const shim = candidates.find((value) => /\.(?:cmd|bat)$/i.test(value));
  if (!shim) return candidates[0] || null;
  try {
    const source = await fs.promises.readFile(shim, "utf8");
    const match = source.match(/"([^"]+\.exe)"/i);
    if (match) {
      const expanded = match[1].replace(/%dp0%/ig, `${path.dirname(shim)}${path.sep}`);
      if (fs.existsSync(expanded)) return expanded;
    }
  } catch { /* fall through to the shim */ }
  return shim;
}

async function detectCli(alias, definition, runner = execResult, resolver = resolveCommand) {
  const commandPath = await resolver(definition.command);
  if (!commandPath) return null;
  let status;
  if (alias === "codex-cli") status = await runner(commandPath, ["login", "status"], { timeout: 15_000 });
  else if (alias === "claude-cli") status = await runner(commandPath, ["auth", "status"], { timeout: 15_000 });
  else status = await runner(commandPath, ["models"], { timeout: 30_000 });
  if (!status.ok) return null;
  if (alias === "codex-cli" && !/logged in|authenticated/i.test(`${status.stdout}\n${status.stderr}`)) return null;
  if (alias === "claude-cli") {
    try {
      const parsed = JSON.parse(status.stdout);
      if (!parsed.loggedIn) return null;
    } catch {
      if (!/logged.?in|authenticated/i.test(`${status.stdout}\n${status.stderr}`)) return null;
    }
  }
  return {
    id: alias,
    alias,
    label: definition.label,
    provider: definition.provider,
    backend: `host-cli/${definition.command}`,
    tier: "subscription",
    cost: "account",
    latency: "medium",
    capabilities: [...definition.capabilities],
    available: true,
    availability_reason: `authenticated ${definition.label} on host`,
    executor: "host_cli",
    commandPath,
  };
}

async function discoverCliModels(options = {}) {
  const entries = await Promise.all(
    Object.entries(CLI_DEFINITIONS).map(async ([alias, definition]) => {
      const model = await detectCli(alias, definition, options.runner || execResult, options.resolver || resolveCommand);
      return model ? [alias, model] : null;
    })
  );
  return Object.fromEntries(entries.filter(Boolean));
}

function promptFromMessages(messages) {
  const items = (Array.isArray(messages) ? messages : []).slice(-24);
  const parts = [];
  let remaining = MAX_PROMPT_CHARS;
  for (let index = items.length - 1; index >= 0 && remaining > 0; index -= 1) {
    const message = items[index] || {};
    const header = `${String(message.role || "user").toUpperCase()}:\n`;
    const separator = parts.length ? 2 : 0;
    const capacity = remaining - header.length - separator;
    if (capacity <= 0) break;
    const content = String(message.content || "");
    parts.unshift(`${header}${content.length > capacity ? content.slice(-capacity) : content}`);
    remaining -= parts[0].length + separator;
  }
  return parts.join("\n\n");
}

function safeCliEnvironment() {
  const allowed = new Set([
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "LANG", "LC_ALL", "TERM", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "GROK_HOME",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
  ]);
  return Object.fromEntries(
    Object.entries(process.env).filter(([name]) => allowed.has(name.toUpperCase()))
  );
}

function spawnWithInput(command, args, prompt, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: safeCliEnvironment(),
      windowsHide: true,
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve(value);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(new Error("host CLI timed out"));
    }, options.timeout || COMMAND_TIMEOUT_MS);
    child.stdout.on("data", (chunk) => { stdout = (stdout + chunk).slice(-4 * 1024 * 1024); });
    child.stderr.on("data", (chunk) => { stderr = (stderr + chunk).slice(-1024 * 1024); });
    child.on("error", (error) => finish(error));
    child.on("close", (code) => {
      if (code === 0 && stdout.trim()) finish(null, stdout.trim());
      else finish(new Error((stderr || stdout || `host CLI exited ${code}`).trim().slice(-2000)));
    });
    child.stdin.end(prompt);
  });
}

async function runCliModel(model, prompt, options = {}) {
  const cwd = options.cwd || process.cwd();
  if (model.alias === "codex-cli") {
    return spawnWithInput(
      model.commandPath,
      ["exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never", "-"],
      prompt,
      { cwd }
    );
  }
  if (model.alias === "claude-cli") {
    return spawnWithInput(
      model.commandPath,
      ["--print", "--output-format", "text", "--permission-mode", "plan", "--no-session-persistence", "--tools", ""],
      prompt,
      { cwd }
    );
  }
  if (model.alias === "grok-cli") {
    const tempDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), "aetherstack-grok-"));
    const promptPath = path.join(tempDir, "prompt.md");
    try {
      await fs.promises.writeFile(promptPath, prompt, { encoding: "utf8", mode: 0o600 });
      return await spawnWithInput(
        model.commandPath,
        ["--prompt-file", promptPath, "--output-format", "plain", "--permission-mode", "plan", "--no-memory", "--max-turns", "1", "--disable-web-search"],
        "",
        { cwd }
      );
    } finally {
      await fs.promises.rm(tempDir, { recursive: true, force: true }).catch(() => {});
    }
  }
  throw new Error("unsupported host CLI model");
}

function sendJson(response, status, value) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
  });
  response.end(body);
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    const contentType = String(request.headers["content-type"] || "").split(";", 1)[0].trim().toLowerCase();
    if (contentType !== "application/json") {
      request.resume();
      reject(new Error("Content-Type must be application/json"));
      return;
    }
    const chunks = [];
    let size = 0;
    let rejected = false;
    request.on("data", (chunk) => {
      if (rejected) return;
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        rejected = true;
        chunks.length = 0;
        reject(new Error("request too large"));
      } else chunks.push(chunk);
    });
    request.on("end", () => {
      if (rejected) return;
      try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}")); }
      catch { reject(new Error("invalid JSON")); }
    });
    request.on("error", (error) => { if (!rejected) reject(error); });
  });
}

function authorized(header, token) {
  const actual = Buffer.from(String(header || ""));
  const expected = Buffer.from(`Bearer ${token}`);
  return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
}

function createCliBridge(options = {}) {
  const token = options.token || crypto.randomBytes(32).toString("hex");
  let port = options.port == null ? DEFAULT_PORT : Number(options.port);
  const cwd = options.cwd || process.cwd();
  let server = null;
  let modelCache = { at: 0, models: {} };

  async function models(refresh = false) {
    if (!refresh && Date.now() - modelCache.at < 30_000) return modelCache.models;
    modelCache = { at: Date.now(), models: await discoverCliModels(options) };
    return modelCache.models;
  }

  async function handler(request, response) {
    if (!authorized(request.headers.authorization, token)) {
      sendJson(response, 401, { error: "unauthorized" });
      return;
    }
    const url = new URL(request.url || "/", `http://127.0.0.1:${port}`);
    try {
      if (request.method === "GET" && (url.pathname === "/health" || url.pathname === "/v1/models")) {
        const available = await models(url.searchParams.get("refresh") === "1");
        const requested = url.searchParams.get("model");
        sendJson(response, 200, {
          ok: requested ? Boolean(available[requested]) : true,
          models: Object.values(available).map(({ commandPath, ...model }) => model),
        });
        return;
      }
      if (request.method === "POST" && url.pathname === "/v1/chat/completions") {
        const body = await readJson(request);
        const available = await models();
        const model = available[String(body.model || "")];
        if (!model) { sendJson(response, 404, { error: "host CLI model is not authenticated or installed" }); return; }
        const prompt = promptFromMessages(body.messages);
        if (!prompt.trim()) { sendJson(response, 400, { error: "messages are required" }); return; }
        const content = await (options.executor || runCliModel)(model, prompt, { cwd });
        sendJson(response, 200, {
          id: `host-cli-${Date.now()}`,
          object: "chat.completion",
          model: model.alias,
          choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
          usage: {},
        });
        return;
      }
      sendJson(response, 404, { error: "not found" });
    } catch (error) {
      const message = error.message || String(error);
      const status = /too large/.test(message) ? 413
        : /Content-Type/.test(message) ? 415
          : /invalid JSON/.test(message) ? 400
            : 500;
      sendJson(response, status, { error: message });
    }
  }

  return {
    token,
    get port() { return port; },
    async start() {
      if (server) return { port, reused: false };
      server = http.createServer((request, response) => { handler(request, response); });
      const reused = await new Promise((resolve, reject) => {
        server.once("error", (error) => {
          if (error && error.code === "EADDRINUSE") resolve(true);
          else reject(error);
        });
      // Docker Desktop reaches this host port through host.docker.internal.
      // Every route still requires the random SecretStorage-backed bearer token.
      server.listen(port, options.host || "0.0.0.0", () => resolve(false));
      });
      if (reused) server = null;
      else port = server.address().port;
      return { port, reused };
    },
    stop() {
      if (server) server.close();
      server = null;
    },
    models,
  };
}

module.exports = {
  CLI_DEFINITIONS,
  createCliBridge,
  discoverCliModels,
  promptFromMessages,
  runCliModel,
  safeCliEnvironment,
};
