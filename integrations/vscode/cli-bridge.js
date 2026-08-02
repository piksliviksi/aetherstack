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
// System prompts travel as argv, and Windows caps a command line near 32 KiB.
const MAX_SYSTEM_CHARS = 8_000;
// Agentic runs read files before answering, so they outlast a plain chat turn.
const COMMAND_TIMEOUT_MS = Number(process.env.AETHER_CLI_TIMEOUT_MS) || 300_000;
const TERMINAL_FAILURE_COOLDOWN_MS = 15 * 60_000;

// systemPromptFlag / systemPromptPrefix: how each CLI accepts system
// instructions. System messages must never be inlined into the user prompt as
// "SYSTEM:" text — a coding agent reads that as an injected instruction block
// and refuses to answer rather than obeying it.
//
// Verified against each CLI on 2026-07-31:
//   claude  --append-system-prompt <text>      (claude --help)
//   grok    --rules <text>                     (grok --help; appends to system prompt)
//   codex   -c developer_instructions=<text>   (codex has no such flag; -c overrides
//           config.toml. Key acceptance and runtime effect were verified with an
//           authenticated read-only `codex exec` run on 2026-08-02.)
const CLI_DEFINITIONS = {
  "codex-cli": {
    command: "codex",
    label: "Codex CLI",
    provider: "codex-cli",
    capabilities: ["chat", "code", "reason", "tools", "long_context"],
    systemPromptFlag: "-c",
    systemPromptPrefix: "developer_instructions=",
  },
  "claude-cli": {
    command: "claude",
    label: "Claude CLI",
    provider: "claude-cli",
    capabilities: ["chat", "code", "reason", "tools", "long_context", "vision"],
    systemPromptFlag: "--append-system-prompt",
  },
  "grok-cli": {
    command: "grok",
    label: "Grok CLI",
    provider: "grok-cli",
    capabilities: ["chat", "code", "reason", "tools", "long_context"],
    systemPromptFlag: "--rules",
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
  if (!result.ok && command === "codex") return findBundledCodex();
  if (!result.ok && command === "claude") return findBundledClaude();
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

async function trustedBundledExecutable(extensionRoot, candidate, identity) {
  try {
    const manifest = JSON.parse(await fs.promises.readFile(path.join(extensionRoot, "package.json"), "utf8"));
    if (String(manifest.publisher || "").toLowerCase() !== identity.publisher) return null;
    if (String(manifest.name || "").toLowerCase() !== identity.name) return null;
    const candidateInfo = await fs.promises.lstat(candidate);
    if (!candidateInfo.isFile() || candidateInfo.isSymbolicLink()) return null;
    const [realRoot, realCandidate] = await Promise.all([
      fs.promises.realpath(extensionRoot),
      fs.promises.realpath(candidate),
    ]);
    const relative = path.relative(realRoot, realCandidate);
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return null;
    return realCandidate;
  } catch {
    return null;
  }
}

async function findBundledCodex(rootOverrides) {
  const roots = rootOverrides || [
    process.env.VSCODE_EXTENSIONS,
    path.join(os.homedir(), ".vscode", "extensions"),
    path.join(os.homedir(), ".vscode-insiders", "extensions"),
  ].filter(Boolean);
  const platformPrefixes = process.platform === "win32" ? ["windows-"]
    : process.platform === "darwin" ? ["darwin-", "macos-"] : ["linux-"];
  const executable = process.platform === "win32" ? "codex.exe" : "codex";
  for (const root of roots) {
    let extensions;
    try { extensions = (await fs.promises.readdir(root)).filter((name) => /^openai\.chatgpt-/i.test(name)).sort().reverse(); }
    catch { continue; }
    for (const extension of extensions) {
      const binRoot = path.join(root, extension, "bin");
      let platforms;
      try {
        platforms = (await fs.promises.readdir(binRoot))
          .filter((name) => platformPrefixes.some((prefix) => name.startsWith(prefix)));
      }
      catch { continue; }
      for (const platform of platforms) {
        const candidate = path.join(binRoot, platform, executable);
        const trusted = await trustedBundledExecutable(
          path.join(root, extension),
          candidate,
          { publisher: "openai", name: "chatgpt" },
        );
        if (trusted) return trusted;
      }
    }
  }
  return null;
}

async function findBundledClaude(rootOverrides) {
  const roots = rootOverrides || [
    process.env.VSCODE_EXTENSIONS,
    path.join(os.homedir(), ".vscode", "extensions"),
    path.join(os.homedir(), ".vscode-insiders", "extensions"),
  ].filter(Boolean);
  const executable = process.platform === "win32" ? "claude.exe" : "claude";
  for (const root of roots) {
    let extensions;
    try { extensions = (await fs.promises.readdir(root)).filter((name) => /^anthropic\.claude-code-/i.test(name)).sort().reverse(); }
    catch { continue; }
    for (const extension of extensions) {
      const candidate = path.join(root, extension, "resources", "native-binary", executable);
      const trusted = await trustedBundledExecutable(
        path.join(root, extension),
        candidate,
        { publisher: "anthropic", name: "claude-code" },
      );
      if (trusted) return trusted;
    }
  }
  return null;
}

function remoteModels(port, token, refresh) {
  return new Promise((resolve, reject) => {
    const request = http.get({
      hostname: "127.0.0.1",
      port,
      path: `/v1/models${refresh ? "?refresh=1" : ""}`,
      headers: { Authorization: `Bearer ${token}` },
      timeout: 35_000,
    }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { body = (body + chunk).slice(-1024 * 1024); });
      response.on("end", () => {
        if (response.statusCode !== 200) { reject(new Error(`existing host bridge rejected synchronization (HTTP ${response.statusCode})`)); return; }
        try {
          const parsed = JSON.parse(body);
          resolve(Object.fromEntries((parsed.models || []).map((model) => [model.alias, model])));
        } catch (error) { reject(new Error(`existing host bridge returned invalid JSON: ${error.message}`)); }
      });
    });
    request.on("timeout", () => request.destroy(new Error("existing host bridge timed out")));
    request.on("error", reject);
  });
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
    systemPromptFlag: definition.systemPromptFlag || null,
    systemPromptPrefix: definition.systemPromptPrefix || "",
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

// Pull system turns out of the transcript so they can travel via the CLI's own
// system-prompt flag instead of being pasted into the user prompt.
function splitMessages(messages) {
  const items = Array.isArray(messages) ? messages : [];
  const isSystem = (message) => String((message || {}).role || "user") === "system";
  return {
    system: items.filter(isSystem)
      .map((message) => String(message.content || "").trim())
      .filter(Boolean)
      .join("\n\n")
      .slice(-MAX_SYSTEM_CHARS),
    conversation: items.filter((message) => !isSystem(message)),
  };
}

function promptFromMessages(messages) {
  // Defensive: system turns are dropped here too, so no caller can put them
  // back into the user prompt by passing an unsplit message list.
  const items = (Array.isArray(messages) ? messages : [])
    .filter((message) => String((message || {}).role || "user") !== "system")
    .slice(-24);
  // A single user turn is sent verbatim: that is what makes Auto mode a real
  // pass-through rather than a transcript the model has to parse.
  if (items.length === 1 && String((items[0] || {}).role || "user") === "user") {
    return String(items[0].content || "").slice(-MAX_PROMPT_CHARS);
  }
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
  const exact = new Set([
    "PATH", "Path", "HOME", "USER", "LOGNAME", "SHELL",
    "TMPDIR", "TMP", "TEMP", "LANG", "LANGUAGE", "TERM", "COLORTERM",
    "NO_COLOR", "FORCE_COLOR", "CODEX_HOME", "CLAUDE_CONFIG_DIR",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "SYSTEMROOT", "WINDIR",
    "COMSPEC", "PATHEXT", "OS", "PROCESSOR_ARCHITECTURE",
    "__CF_USER_TEXT_ENCODING",
  ]);
  return Object.fromEntries(
    Object.entries(process.env).filter(([name]) => exact.has(name) || name.startsWith("LC_"))
  );
}

function appendBoundedOutput(current, chunk, limit) {
  const next = current + chunk.toString();
  if (Buffer.byteLength(next) <= limit) return next;
  const marker = "\n...[earlier host CLI output truncated; process continued]...\n";
  let tail = next.slice(Math.max(0, next.length - limit));
  while (Buffer.byteLength(marker + tail) > limit && tail.length) {
    tail = tail.slice(Math.max(1, Math.ceil(tail.length * 0.02)));
  }
  return marker + tail;
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
    child.stdout.on("data", (chunk) => {
      stdout = appendBoundedOutput(stdout, chunk, options.stdoutLimit || 4 * 1024 * 1024);
    });
    child.stderr.on("data", (chunk) => {
      stderr = appendBoundedOutput(stderr, chunk, options.stderrLimit || 1024 * 1024);
    });
    child.on("error", (error) => finish(error));
    child.on("close", (code) => {
      if (code === 0 && stdout.trim()) finish(null, stdout.trim());
      else finish(new Error((stderr || stdout || `host CLI exited ${code}`).trim().slice(-2000)));
    });
    child.stdin.end(prompt);
  });
}

// Native system-prompt args when the CLI supports them, else nothing — the
// caller inlines the text instead.
// Some CLIs take `--flag <text>`, codex takes `-c key=<text>`; the prefix covers both.
function systemArgs(model, system) {
  const flag = model.systemPromptFlag;
  if (!flag || !system) return [];
  return [flag, `${model.systemPromptPrefix || ""}${system}`];
}

// Only used when a CLI has no system-prompt flag. Framed as context, never as a
// "SYSTEM:" instruction header.
function inlineSystem(prompt, system) {
  return system ? `Context for this request:\n${system}\n\n---\n\n${prompt}` : prompt;
}

async function runCliModel(model, prompt, options = {}) {
  const cwd = options.cwd || process.cwd();
  const system = String(options.system || "").trim();
  const native = systemArgs(model, system);
  const body = native.length ? prompt : inlineSystem(prompt, system);
  if (model.alias === "codex-cli") {
    const sandbox = options.workspaceWrite ? "workspace-write" : "read-only";
    return spawnWithInput(
      model.commandPath,
      ["exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", sandbox, "--color", "never", ...native, "-"],
      body,
      { cwd }
    );
  }
  if (model.alias === "claude-cli") {
    // Tools stay enabled: with `--tools ""` the model narrates tool calls it
    // cannot run and answers from guesswork. `--permission-mode plan` is the
    // read-only guard (verified: it refuses writes), matching codex's
    // `--sandbox read-only` and grok's `--permission-mode plan`.
    return spawnWithInput(
      model.commandPath,
      ["--print", "--output-format", "text", "--permission-mode", options.workspaceWrite ? "acceptEdits" : "plan", "--no-session-persistence", ...native],
      body,
      { cwd }
    );
  }
  if (model.alias === "grok-cli") {
    const tempDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), "aetherstack-grok-"));
    const promptPath = path.join(tempDir, "prompt.md");
    try {
      await fs.promises.writeFile(promptPath, body, { encoding: "utf8", mode: 0o600 });
      return await spawnWithInput(
        model.commandPath,
        ["--prompt-file", promptPath, "--output-format", "plain", "--permission-mode", options.workspaceWrite ? "acceptEdits" : "plan", "--no-memory", "--no-plan", "--no-subagents", "--max-turns", "8", "--disable-web-search", ...native],
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

function isTerminalProviderFailure(error) {
  return ["provider_limit_reached", "provider_auth_required"].includes(bridgeFailure(error).code);
}

function bridgeFailure(error) {
  const raw = String(error && (error.message || error) || "host CLI failed");
  if (/timed out|\btimeout\b/i.test(raw)) {
    return { status: 504, code: "provider_timeout", message: "The host CLI timed out." };
  }
  if (/not authenticated|authentication required|unauthorized|log(?:ged)?\s*out/i.test(raw)) {
    return { status: 401, code: "provider_auth_required", message: "The host CLI needs authentication." };
  }
  if (/\b402\b|payment required|balance exhausted|usage (?:balance|limit)|session limit|quota|rate limit/i.test(raw)) {
    return { status: 429, code: "provider_limit_reached", message: "The host CLI account limit was reached." };
  }
  if (/too large/i.test(raw)) return { status: 413, code: "request_too_large", message: "The request is too large." };
  if (/Content-Type/i.test(raw)) return { status: 415, code: "unsupported_media_type", message: "Content-Type must be application/json." };
  if (/invalid JSON/i.test(raw)) return { status: 400, code: "invalid_json", message: "The request body is not valid JSON." };
  return { status: 502, code: "provider_execution_failed", message: "The host CLI could not complete the request." };
}

function createCliBridge(options = {}) {
  const token = options.token || crypto.randomBytes(32).toString("hex");
  let port = options.port == null ? DEFAULT_PORT : Number(options.port);
  const cwd = options.cwd || process.cwd();
  let server = null;
  let reusedServer = false;
  let modelCache = { at: 0, models: {} };
  const quarantinedUntil = new Map();

  async function models(refresh = false) {
    if (reusedServer) return remoteModels(port, token, refresh);
    if (!refresh && Date.now() - modelCache.at < 30_000) return modelCache.models;
    const now = Date.now();
    const discovered = await discoverCliModels(options);
    for (const [alias, until] of quarantinedUntil) {
      if (until <= now) quarantinedUntil.delete(alias);
      else delete discovered[alias];
    }
    modelCache = { at: now, models: discovered };
    return modelCache.models;
  }

  async function handler(request, response) {
    if (!authorized(request.headers.authorization, token)) {
      sendJson(response, 401, { error: "Unauthorized.", code: "unauthorized" });
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
        if (!model) { sendJson(response, 404, { error: "Host CLI model is not authenticated or installed.", code: "model_unavailable" }); return; }
        const { system, conversation } = splitMessages(body.messages);
        const prompt = promptFromMessages(conversation);
        if (!prompt.trim()) { sendJson(response, 400, { error: "Messages are required.", code: "invalid_request" }); return; }
        let content;
        try {
          content = await (options.executor || runCliModel)(model, prompt, {
            cwd,
            system,
            workspaceWrite: body.workspace_write === true,
          });
        } catch (error) {
          if (isTerminalProviderFailure(error)) {
            quarantinedUntil.set(model.alias, Date.now() + TERMINAL_FAILURE_COOLDOWN_MS);
            delete modelCache.models[model.alias];
          }
          throw error;
        }
        sendJson(response, 200, {
          id: `host-cli-${Date.now()}`,
          object: "chat.completion",
          model: model.alias,
          choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
          usage: {},
        });
        return;
      }
      sendJson(response, 404, { error: "Not found.", code: "not_found" });
    } catch (error) {
      const failure = bridgeFailure(error);
      console.error(`[cli-bridge] ${failure.code}: ${error.message || error}`);
      sendJson(response, failure.status, { error: failure.message, code: failure.code });
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
      if (reused) {
        server = null;
        reusedServer = true;
      }
      else port = server.address().port;
      return { port, reused };
    },
    stop() {
      if (server) server.close();
      server = null;
      reusedServer = false;
    },
    models,
  };
}

module.exports = {
  CLI_DEFINITIONS,
  createCliBridge,
  discoverCliModels,
  findBundledCodex,
  findBundledClaude,
  promptFromMessages,
  splitMessages,
  runCliModel,
  safeCliEnvironment,
  spawnWithInput,
  trustedBundledExecutable,
  isTerminalProviderFailure,
  bridgeFailure,
};
