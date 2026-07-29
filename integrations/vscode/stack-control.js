const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const { execFile } = require("child_process");
const { URL } = require("url");

const SERVICES = [
  {
    id: "webui",
    name: "Open WebUI",
    url: "http://127.0.0.1:3000/",
    healthUrl: "http://127.0.0.1:3000/",
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
          resolve({ status: res.statusCode || 0, body });
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
          res.on("end", () => reject(new Error(data || `HTTP ${res.statusCode}`)));
          return;
        }
        res.setEncoding("utf8");
        let buffer = "";
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
            onEvent(parsed); // deliberately outside the try/catch above — a bug in the caller's
                              // handler should surface normally, not be silently swallowed as "malformed JSON"
          }
        });
        res.on("end", () => resolve());
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
    services,
  };
}

function execFileResult(file, args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(
      file,
      args,
      { windowsHide: true, maxBuffer: 4 * 1024 * 1024, ...options },
      (error, stdout, stderr) => {
        const result = { stdout: stdout || "", stderr: stderr || "", code: error ? error.code : 0 };
        if (error) {
          error.result = result;
          reject(error);
        } else {
          resolve(result);
        }
      }
    );
  });
}

async function startCompose(stackRoot) {
  if (!isStackRoot(stackRoot)) throw new Error(`Not an AetherStack installation: ${stackRoot}`);

  const envFile = path.join(stackRoot, ".env");
  const exampleFile = path.join(stackRoot, ".env.example");
  fs.mkdirSync(path.join(stackRoot, ".aetherstack"), { recursive: true });
  if (!fs.existsSync(envFile) && fs.existsSync(exampleFile)) {
    fs.copyFileSync(exampleFile, envFile, fs.constants.COPYFILE_EXCL);
  }

  try {
    await execFileResult("docker", ["info"], { cwd: stackRoot, timeout: 15_000 });
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error("Docker was not found. Install Docker Desktop (or Docker Engine) and retry.");
    }
    throw new Error("Docker is installed but its daemon is not ready. Start Docker Desktop or dockerd and retry.");
  }

  try {
    return await execFileResult("docker", ["compose", "up", "-d", "--build"], {
      cwd: stackRoot,
      timeout: 5 * 60_000,
    });
  } catch (error) {
    const detail = conciseError(error.result && (error.result.stderr || error.result.stdout));
    throw new Error(`docker compose up failed${detail ? `: ${detail}` : ""}`);
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
  return runCompose(stackRoot, ["stop"]);
}

async function restartCompose(stackRoot) {
  // `docker compose restart` does not apply changed images, builds, Compose
  // configuration, or environment values. Recreate so the button does what an
  // operator reasonably expects after an AetherStack update.
  return runCompose(stackRoot, ["up", "-d", "--build", "--force-recreate"], {
    timeoutMs: 5 * 60_000,
  });
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
  checkServices,
  conciseError,
  findStackRoot,
  isStackRoot,
  normalizeLocalUiUrl,
  request,
  requestStream,
  composeDetails,
  composeLogs,
  restartCompose,
  runCompose,
  selectAvailableModels,
  startCompose,
  stopCompose,
  waitForServices,
};
