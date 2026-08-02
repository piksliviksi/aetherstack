const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const { spawn } = require("child_process");
const { URL } = require("url");

const SERVICES = [
  {
    id: "webui",
    name: "Open WebUI",
    url: "http://127.0.0.1:3000/",
    healthUrl: "http://127.0.0.1:3000/healthz",
  },
  {
    id: "litellm",
    name: "LiteLLM",
    url: "http://127.0.0.1:4000/",
    healthUrl: "http://127.0.0.1:4000/health/liveliness",
  },
  {
    id: "hub",
    name: "Aether Hub",
    url: "http://127.0.0.1:8766/",
    healthUrl: "http://127.0.0.1:8766/api/health",
  },
];

function isStackRoot(candidate) {
  if (!candidate) return false;
  try {
    return (
      fs.statSync(candidate).isDirectory() &&
      fs.existsSync(path.join(candidate, "docker-compose.yml")) &&
      fs.existsSync(path.join(candidate, "aether-hub")) &&
      fs.existsSync(path.join(candidate, "litellm_config.yaml"))
    );
  } catch {
    return false;
  }
}

function parentCandidates(start) {
  const out = [];
  if (!start) return out;
  let current = path.resolve(start);
  while (true) {
    out.push(current);
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return out;
}

function findStackRoot({ configuredPath, rememberedPath, workspacePaths = [], extensionPath, cwd }) {
  const candidates = [configuredPath, rememberedPath];
  for (const workspacePath of workspacePaths) candidates.push(...parentCandidates(workspacePath));
  candidates.push(...parentCandidates(extensionPath));
  candidates.push(...parentCandidates(cwd));

  const seen = new Set();
  for (const candidate of candidates) {
    if (!candidate) continue;
    const resolved = path.resolve(candidate);
    const key = process.platform === "win32" ? resolved.toLowerCase() : resolved;
    if (seen.has(key)) continue;
    seen.add(key);
    if (isStackRoot(resolved)) return resolved;
  }
  return null;
}

function request(urlStr, { headers = {}, timeoutMs = 4000, method = "GET", body = null, signal = null } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlStr);
    const client = url.protocol === "https:" ? https : http;
    const req = client.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        method,
        headers: body == null
          ? headers
          : { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(typeof body === "string" ? body : JSON.stringify(body)), ...headers },
        timeout: timeoutMs,
      },
      (res) => {
        let data = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          if (data.length < 2_000_000) data += chunk;
        });
        res.on("end", () => {
          let body = data;
          try {
            body = data ? JSON.parse(data) : null;
          } catch {
            // Some health endpoints intentionally return text or HTML.
          }
          resolve({
            status: res.statusCode || 0,
            body,
            headers: res.headers,
            requestId: res.headers["x-aetherstack-request-id"] || null,
          });
        });
      }
    );
    req.on("error", reject);
    const abort = () => {
      const error = new Error("request cancelled");
      error.name = "AbortError";
      error.code = "ABORT_ERR";
      req.destroy(error);
    };
    if (signal) {
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
      req.once("close", () => signal.removeEventListener("abort", abort));
    }
    req.on("timeout", () => req.destroy(new Error(`timed out after ${timeoutMs} ms`)));
    if (body != null) req.write(typeof body === "string" ? body : JSON.stringify(body));
    req.end();
  });
}

function requestStream(urlStr, { headers = {}, timeoutMs = 190_000, method = "POST", body = null, signal = null } = {}, onEvent) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlStr);
    const client = url.protocol === "https:" ? https : http;
    const req = client.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        method,
        headers: body == null
          ? headers
          : { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(typeof body === "string" ? body : JSON.stringify(body)), ...headers },
        timeout: timeoutMs,
      },
      (res) => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          let data = "";
          res.setEncoding("utf8");
          res.on("data", (chunk) => { data += chunk; });
          res.on("end", () => {
            let body = data;
            try { body = data ? JSON.parse(data) : null; } catch { /* retain text */ }
            reject(responseError(res.statusCode || 0, body, res.headers));
          });
          return;
        }
        res.setEncoding("utf8");
        let buffer = "";
        let terminal = false;
        res.on("data", (chunk) => {
          buffer += chunk;
          let index;
          while ((index = buffer.indexOf("\n\n")) !== -1) {
            const raw = buffer.slice(0, index);
            buffer = buffer.slice(index + 2);
            const line = raw.split("\n").find((part) => part.startsWith("data:"));
            if (!line) continue;
            let parsed;
            try {
              parsed = JSON.parse(line.slice(5).trim());
            } catch {
              continue; // malformed chunk — skip it, don't let a parse failure abort the stream
            }
            if (parsed && (parsed.type === "done" || parsed.type === "error")) terminal = true;
            onEvent(parsed); // deliberately outside the try/catch above — a bug in the caller's
                              // handler should surface normally, not be silently swallowed as "malformed JSON"
          }
        });
        res.on("end", () => {
          if (terminal) resolve();
          else {
            const error = new Error("AetherStack stream ended before a terminal event.");
            error.name = "AetherStackStreamError";
            error.code = "stream_incomplete";
            error.requestId = res.headers["x-aetherstack-request-id"] || null;
            reject(error);
          }
        });
      }
    );
    req.on("error", reject);
    const abort = () => {
      const error = new Error("request cancelled");
      error.name = "AbortError";
      error.code = "ABORT_ERR";
      req.destroy(error);
    };
    if (signal) {
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
      req.once("close", () => signal.removeEventListener("abort", abort));
    }
    req.on("timeout", () => req.destroy(new Error(`timed out after ${timeoutMs} ms`)));
    if (body != null) req.write(typeof body === "string" ? body : JSON.stringify(body));
    req.end();
  });
}

function responseError(status, body, headers = {}) {
  const detail = body && typeof body === "object" ? body.error || body.detail : body;
  const error = new Error(String(detail || `HTTP ${status}`));
  error.name = "AetherStackHttpError";
  error.status = status;
  error.code = body && typeof body === "object" && body.code
    ? String(body.code)
    : status === 401 ? "unauthorized"
      : status === 404 ? "not_found"
        : status === 504 ? "upstream_timeout"
          : status >= 500 ? "service_unavailable" : "request_failed";
  error.requestId = (body && typeof body === "object" && body.request_id)
    || headers["x-aetherstack-request-id"]
    || null;
  return error;
}

function conciseError(error) {
  if (!error) return "unknown error";
  if (error.code === "ECONNREFUSED") return "connection refused";
  if (error.code === "ENOTFOUND") return "host not found";
  const message = String(error.message || error).replace(/\s+/g, " ").trim();
  return message.length > 800 ? `${message.slice(0, 797)}…` : message;
}

async function checkServices() {
  const services = await Promise.all(
    SERVICES.map(async (service) => {
      try {
        const response = await request(service.healthUrl);
        const ok = response.status >= 200 && response.status < 400;
        return {
          ...service,
          ok,
          inferenceReady: service.id === "hub" ? response.body?.inference_ready !== false : undefined,
          routableModelCount: service.id === "hub" ? Number(response.body?.routable_model_count || 0) : undefined,
          error: ok ? null : `HTTP ${response.status}`,
        };
      } catch (error) {
        return { ...service, ok: false, error: conciseError(error) };
      }
    })
  );
  return {
    checkedAt: new Date().toISOString(),
    up: services.every((service) => service.ok),
    inferenceReady: services.find((service) => service.id === "hub")?.inferenceReady !== false,
    services,
  };
}

// Distinguishes "Docker isn't installed" from "Docker is installed but its
// daemon isn't running" — the two blank-machine failure modes need different
// next steps (install vs. open Docker Desktop / start the service).
async function checkDocker() {
  const locator = process.platform === "win32" ? "where.exe" : "which";
  const found = await execFileResult(locator, ["docker"], { timeout: 5_000 }).catch(() => ({ ok: false }));
  if (!found.ok) return { installed: false, running: false };
  const info = await execFileResult("docker", ["info"], { timeout: 8_000 }).catch(() => ({ ok: false }));
  return { installed: true, running: Boolean(info.ok) };
}

const MAX_CAPTURE_BYTES = 4 * 1024 * 1024;

function appendBoundedOutput(current, chunk, limit = MAX_CAPTURE_BYTES) {
  const next = current + chunk.toString();
  if (Buffer.byteLength(next) <= limit) return next;
  const marker = "\n...[earlier command output truncated; process continued]...\n";
  let tail = next.slice(Math.max(0, next.length - limit));
  while (Buffer.byteLength(marker + tail) > limit && tail.length) {
    tail = tail.slice(Math.max(1, Math.ceil(tail.length * 0.02)));
  }
  return marker + tail;
}

function execFileResult(file, args, options = {}) {
  return new Promise((resolve, reject) => {
    const { timeout = 0, onOutput = null, captureBytes = MAX_CAPTURE_BYTES, ...spawnOptions } = options;
    const child = spawn(file, args, { windowsHide: true, ...spawnOptions });
    let stdout = "";
    let stderr = "";
    let settled = false;
    let timedOut = false;

    const capture = (stream) => (chunk) => {
      if (stream === "stdout") stdout = appendBoundedOutput(stdout, chunk, captureBytes);
      else stderr = appendBoundedOutput(stderr, chunk, captureBytes);
      if (onOutput) onOutput(chunk.toString(), stream);
    };
    child.stdout.on("data", capture("stdout"));
    child.stderr.on("data", capture("stderr"));

    const timer = timeout > 0
      ? setTimeout(() => {
          timedOut = true;
          child.kill();
        }, timeout)
      : null;

    child.once("error", (error) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      error.result = { stdout, stderr, code: error.code || 1 };
      reject(error);
    });
    child.once("close", (code, signal) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      const result = { stdout, stderr, code: code ?? (timedOut ? "ETIMEDOUT" : 1), signal, streamed: Boolean(onOutput) };
      if (code === 0 && !timedOut) {
        resolve(result);
        return;
      }
      const error = new Error(timedOut ? `${file} timed out after ${timeout} ms` : `${file} exited with code ${code ?? signal}`);
      error.code = timedOut ? "ETIMEDOUT" : code;
      error.result = result;
      reject(error);
    });
  });
}

async function startCompose(stackRoot, { onOutput = null } = {}) {
  if (!isStackRoot(stackRoot)) throw new Error(`Not an AetherStack installation: ${stackRoot}`);

  const envFile = path.join(stackRoot, ".env");
  const exampleFile = path.join(stackRoot, ".env.example");
  fs.mkdirSync(path.join(stackRoot, ".aetherstack"), { recursive: true });
  if (!fs.existsSync(envFile) && fs.existsSync(exampleFile)) {
    fs.copyFileSync(exampleFile, envFile, fs.constants.COPYFILE_EXCL);
  }

  const windowsScript = path.join(stackRoot, "start.ps1");
  const unixScript = path.join(stackRoot, "start.sh");
  const progressEnv = { ...process.env, COMPOSE_PROGRESS: "plain", BUILDKIT_PROGRESS: "plain" };
  const command = process.platform === "win32" && fs.existsSync(windowsScript)
    ? { file: "powershell.exe", args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", windowsScript, "-NoBrowser"], env: progressEnv }
    : process.platform !== "win32" && fs.existsSync(unixScript)
      ? { file: "bash", args: [unixScript], env: { ...progressEnv, AETHER_NO_BROWSER: "1" } }
      : null;
  try {
    if (command) {
      return await execFileResult(command.file, command.args, {
        cwd: stackRoot,
        env: command.env,
        onOutput,
        // A first start may need to pull the compact chat and embedding models
        // over a slow connection. The progress UI remains visible throughout.
        timeout: 60 * 60_000,
      });
    }
    await execFileResult("docker", ["info"], { cwd: stackRoot, timeout: 15_000 });
    return await execFileResult("docker", ["compose", "up", "-d", "--build"], {
      cwd: stackRoot,
      timeout: 5 * 60_000,
    });
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error(`${command ? command.file : "Docker"} was not found. Install Docker Desktop (or Docker Engine) and retry.`);
    }
    const raw = (error.result && (error.result.stderr || error.result.stdout)) || "";
    if (/ERROR: Docker not found/i.test(raw)) {
      throw new Error("Docker was not found. Install Docker Desktop (or Docker Engine) and retry.");
    }
    const detail = conciseError(raw);
    throw new Error(`AetherStack startup failed${detail ? `: ${detail}` : ": Docker is not ready"}`);
  }
}

async function runCompose(stackRoot, args, { timeoutMs = 2 * 60_000 } = {}) {
  if (!isStackRoot(stackRoot)) throw new Error(`Not an AetherStack installation: ${stackRoot}`);
  try {
    return await execFileResult("docker", ["compose", ...args], {
      cwd: stackRoot,
      timeout: timeoutMs,
    });
  } catch (error) {
    if (error.code === "ENOENT") throw new Error("Docker was not found.");
    const detail = conciseError(error.result && (error.result.stderr || error.result.stdout));
    throw new Error(`docker compose ${args.join(" ")} failed${detail ? `: ${detail}` : ""}`);
  }
}

async function stopCompose(stackRoot) {
  // Use the platform lifecycle entrypoint so AetherStack-owned host helpers
  // (currently the user-space macOS Ollama process) stop with Compose. Fall
  // back to direct Compose only for incomplete/developer installations.
  const windowsScript = path.join(stackRoot, "stop.ps1");
  const unixScript = path.join(stackRoot, "stop.sh");
  try {
    if (process.platform === "win32" && fs.existsSync(windowsScript)) {
      return await execFileResult("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", windowsScript], {
        cwd: stackRoot,
        timeout: 5 * 60_000,
      });
    }
    if (process.platform !== "win32" && fs.existsSync(unixScript)) {
      return await execFileResult("bash", [unixScript], { cwd: stackRoot, timeout: 5 * 60_000 });
    }
    return await runCompose(stackRoot, ["--profile", "*", "stop"]);
  } catch (error) {
    if (error.code === "ENOENT") throw new Error("Docker lifecycle command was not found.");
    const detail = conciseError(error.result && (error.result.stderr || error.result.stdout));
    throw new Error(`AetherStack stop failed${detail ? `: ${detail}` : ""}`);
  }
}

async function restartCompose(stackRoot) {
  // Run the bootstrap after stopping every profile. It reselects host versus
  // managed Ollama, reapplies changed environment, and ensures required models.
  const stopped = await stopCompose(stackRoot);
  const started = await startCompose(stackRoot);
  return {
    ...started,
    stdout: `${stopped.stdout || ""}${started.stdout || ""}`,
    stderr: `${stopped.stderr || ""}${started.stderr || ""}`,
  };
}

async function composeDetails(stackRoot) {
  if (!isStackRoot(stackRoot)) return [];
  const result = await runCompose(stackRoot, ["ps", "--all", "--format", "json"]);
  const text = result.stdout.trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    return text
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  }
}

async function composeLogs(stackRoot, tail = 100) {
  return runCompose(stackRoot, ["logs", "--no-color", "--tail", String(tail)]);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForServices({ timeoutMs = 90_000, intervalMs = 2_000, onCheck } = {}) {
  const deadline = Date.now() + timeoutMs;
  let status = await checkServices();
  if (onCheck) onCheck(status);
  while (!status.up && Date.now() < deadline) {
    await sleep(Math.min(intervalMs, Math.max(0, deadline - Date.now())));
    status = await checkServices();
    if (onCheck) onCheck(status);
  }
  return status;
}

function selectAvailableModels(matrix, gatewayModelIds = [], healthyModelIds = null, limit = 8) {
  const models = matrix && matrix.models && typeof matrix.models === "object" ? matrix.models : {};
  const gateway = new Set(gatewayModelIds.filter(Boolean));
  const healthy = healthyModelIds === null ? null : new Set(healthyModelIds.filter(Boolean));
  const usable = new Set(["chat", "code", "reason", "vision", "tools"]);
  const available = new Map(
    Object.entries(models).filter(([alias, meta]) => {
      const caps = Array.isArray(meta.capabilities) ? meta.capabilities : [];
      return (
        meta.available === true &&
        caps.some((capability) => usable.has(capability)) &&
        (!gateway.size || gateway.has(alias)) &&
        (healthy === null || healthy.has(alias))
      );
    })
  );

  const priority = ["local-default"];
  const fallbacks = (matrix && matrix.routing && matrix.routing.fallbacks) || {};
  for (const capability of ["chat", "code", "reason", "vision", "fast", "private"]) {
    if (Array.isArray(fallbacks[capability])) priority.push(...fallbacks[capability]);
  }
  priority.push(...available.keys());

  const chosen = [];
  const seen = new Set();
  for (const alias of priority) {
    if (seen.has(alias) || !available.has(alias)) continue;
    seen.add(alias);
    chosen.push({ alias, ...available.get(alias) });
    if (chosen.length >= limit) break;
  }
  return chosen;
}

function normalizeLocalUiUrl(value) {
  let url;
  try {
    url = new URL(value || "http://127.0.0.1:3000/");
  } catch {
    return "http://127.0.0.1:3000/";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return "http://127.0.0.1:3000/";
  if (!["127.0.0.1", "localhost", "::1"].includes(url.hostname)) return "http://127.0.0.1:3000/";
  url.pathname = "/";
  url.search = "";
  url.hash = "";
  return url.toString();
}

module.exports = {
  SERVICES,
  checkDocker,
  checkServices,
  conciseError,
  findStackRoot,
  isStackRoot,
  normalizeLocalUiUrl,
  request,
  requestStream,
  responseError,
  composeDetails,
  composeLogs,
  execFileResult,
  restartCompose,
  runCompose,
  selectAvailableModels,
  startCompose,
  stopCompose,
  waitForServices,
};
