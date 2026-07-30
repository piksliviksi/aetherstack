/* AetherStack VS Code extension — scan project AI history + wire multi-LLM gateway */
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { createCliBridge } = require("./cli-bridge");
const { reconcileHostCliBridge } = require("./cli-sync");
const { parseChatInput, commandHelp } = require("./chat-routing");
const { createChatRequestHandler } = require("./chat-participant");
const { capConversations, titleFromTranscript } = require("./conversations");
const { installRuntime: installRuntimeBundle } = require("./runtime-install");
const extensionManifest = require("./package.json");
const {
  SERVICES,
  checkServices,
  composeDetails,
  composeLogs,
  findStackRoot,
  isStackRoot,
  normalizeLocalUiUrl,
  request,
  requestStream,
  runCompose,
  restartCompose,
  selectAvailableModels,
  startCompose,
  stopCompose,
  waitForServices,
} = require("./stack-control");

let secretStorage = null;
let runtimeRefresh = null;
let runtimeRefreshIncludesTechnical = false;
let runtimeRefreshIncludesModels = false;
let modelVerificationCache = null;

const SCAN_GLOBS = [
  "**/.continue/**",
  "**/.claude/**",
  "**/.aider*",
  "**/.waylog/**",
  "**/.aetherstack/**",
  "**/aider.chat.history.md",
  "**/*chat*export*.json",
  "**/*chat-session*.json",
];

function workspaceRoot() {
  const f = vscode.workspace.workspaceFolders;
  return f && f.length ? f[0].uri.fsPath : null;
}

function cfg() {
  const c = vscode.workspace.getConfiguration("aetherstack");
  return {
    baseUrl: c.get("baseUrl") || "http://127.0.0.1:4000/v1",
    chatUiUrl: c.get("chatUiUrl") || "http://127.0.0.1:3000",
    defaultModel: c.get("defaultModel") || "local-default",
    stackPath: c.get("stackPath") || "",
    autoWireModels: c.get("autoWireModels") !== false,
    showActiveModel: c.get("showActiveModel") === true,
  };
}

async function getApiKey() {
  return (
    process.env.AETHERSTACK_API_KEY ||
    (secretStorage ? await secretStorage.get("aetherstack.apiKey") : "") ||
    "sk-aether-local"
  );
}

async function migrateLegacyApiKey(context) {
  const c = vscode.workspace.getConfiguration("aetherstack");
  const legacy = c.inspect("apiKey") || {};
  const value = legacy.workspaceFolderValue || legacy.workspaceValue || legacy.globalValue;
  if (typeof value === "string" && value.trim()) {
    await context.secrets.store("aetherstack.apiKey", value.trim());
  }
  const targets = [
    [legacy.workspaceFolderValue, vscode.ConfigurationTarget.WorkspaceFolder],
    [legacy.workspaceValue, vscode.ConfigurationTarget.Workspace],
    [legacy.globalValue, vscode.ConfigurationTarget.Global],
  ];
  for (const [configured, target] of targets) {
    if (configured !== undefined) await c.update("apiKey", undefined, target);
  }
}

function listDirSafe(p, depth = 0, maxDepth = 3) {
  const out = [];
  if (depth > maxDepth || !fs.existsSync(p)) return out;
  let entries;
  try {
    entries = fs.readdirSync(p, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const full = path.join(p, e.name);
    if (e.isDirectory()) {
      out.push({ type: "dir", path: full, name: e.name });
      out.push(...listDirSafe(full, depth + 1, maxDepth));
    } else {
      let size = 0;
      let mtime = null;
      try {
        const st = fs.statSync(full);
        size = st.size;
        mtime = st.mtime;
      } catch {
        /* ignore */
      }
      out.push({ type: "file", path: full, name: e.name, size, mtime });
    }
  }
  return out;
}

function repositoryPath(root, target) {
  return (path.relative(root, target) || ".").split(path.sep).join("/");
}

function detectSources(root) {
  const sources = [];
  const checks = [
    { id: "continue", rel: ".continue", label: "Continue.dev" },
    { id: "claude", rel: ".claude", label: "Claude / Claude Code" },
    { id: "waylog", rel: ".waylog", label: "WayLog chat archive" },
    { id: "aetherstack", rel: ".aetherstack", label: "AetherStack project notes" },
    { id: "cursor", rel: ".cursor", label: "Cursor project config" },
  ];
  for (const c of checks) {
    const p = path.join(root, c.rel);
    if (fs.existsSync(p)) {
      const files = listDirSafe(p).filter((x) => x.type === "file");
      sources.push({
        ...c,
        path: p,
        fileCount: files.length,
        recent: files
          .filter((f) => f.mtime)
          .sort((a, b) => b.mtime - a.mtime)
          .slice(0, 8)
          .map((f) => ({
            name: repositoryPath(root, f.path),
            mtime: f.mtime.toISOString(),
            size: f.size,
          })),
      });
    }
  }

  // Loose history files in project root
  const loose = [];
  for (const name of ["aider.chat.history.md", ".aider.chat.history.md"]) {
    const p = path.join(root, name);
    if (fs.existsSync(p)) {
      const st = fs.statSync(p);
      loose.push({
        name,
        mtime: st.mtime.toISOString(),
        size: st.size,
      });
    }
  }
  if (loose.length) {
    sources.push({
      id: "aider",
      label: "Aider chat history",
      path: root,
      fileCount: loose.length,
      recent: loose,
    });
  }

  return sources;
}

function guessModelsFromText(text) {
  const models = new Set();
  const patterns = [
    /\b(gpt-4\.1|gpt-4o|gpt-4o-mini|o3|o4-mini|claude-[\w.-]+|grok-[\w.-]+|gemini-[\w.-]+|llama[\w.-]*|qwen[\w.-]*|deepseek[\w.-]*|codex|local-default|local-llama)\b/gi,
  ];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(text)) !== null) models.add(m[1]);
  }
  return [...models];
}

function sampleSourceModels(root, sources) {
  const found = new Set();
  for (const s of sources) {
    for (const f of s.recent || []) {
      const fp = path.isAbsolute(f.name) ? f.name : path.join(root, f.name);
      if (!fs.existsSync(fp) || !fs.statSync(fp).isFile()) continue;
      if (fs.statSync(fp).size > 2_000_000) continue;
      try {
        const text = fs.readFileSync(fp, "utf8").slice(0, 100_000);
        guessModelsFromText(text).forEach((m) => found.add(m));
      } catch {
        /* ignore binary */
      }
    }
  }
  return [...found];
}

function buildOverview(root) {
  const sources = detectSources(root);
  const modelsGuessed = sampleSourceModels(root, sources);
  const c = cfg();
  const safeSources = sources.map((source) => ({
    ...source,
    // Overview files may be committed. Never persist absolute host paths or
    // usernames; recent file names are already workspace-relative.
    path: repositoryPath(root, source.path),
  }));
  // Never persist secrets into overview JSON written on disk
  const overview = {
    generatedAt: new Date().toISOString(),
    workspace: ".",
    aetherstack: {
      baseUrl: c.baseUrl,
      chatUiUrl: c.chatUiUrl,
      defaultModel: c.defaultModel,
    },
    sources: safeSources,
    modelsMentioned: modelsGuessed,
    howToContinue: [
      "Start AetherStack (start.bat / ./start.sh) so LiteLLM :4000 and Open WebUI :3000 are up.",
      "Run command: AetherStack: Wire Continue.dev to AetherStack",
      "Or open Chat UI and paste a summary from .aetherstack/project-overview.md",
      "Pick a model alias (local-default, grok-4.5, gpt-4.1, claude-sonnet-4, …) via Continue or the API.",
    ],
  };
  return overview;
}

function writeOverviewFiles(root, overview) {
  const dir = path.join(root, ".aetherstack");
  fs.mkdirSync(dir, { recursive: true });
  const jsonPath = path.join(dir, "project-overview.json");
  fs.writeFileSync(jsonPath, JSON.stringify(overview, null, 2), "utf8");

  const md = [];
  md.push(`# AetherStack project overview`);
  md.push("");
  md.push(`Generated: ${overview.generatedAt}`);
  md.push(`Workspace: \`${overview.workspace}\` (paths are repository-relative)`);
  md.push("");
  md.push(`## Detected AI history sources`);
  if (!overview.sources.length) {
    md.push("_None found yet._ Use Continue, Claude Code, Aider, WayLog, or save snapshots here.");
  } else {
    for (const s of overview.sources) {
      md.push(`### ${s.label}`);
      md.push(`- Path: \`${s.path}\``);
      md.push(`- Files: ${s.fileCount}`);
      if (s.recent && s.recent.length) {
        md.push(`- Recent:`);
        for (const r of s.recent) {
          md.push(`  - \`${r.name}\` (${r.mtime}${r.size != null ? `, ${r.size} B` : ""})`);
        }
      }
      md.push("");
    }
  }
  md.push(`## Models mentioned in samples`);
  md.push(
    overview.modelsMentioned.length
      ? overview.modelsMentioned.map((m) => `- \`${m}\``).join("\n")
      : "_No model ids detected in sampled files._"
  );
  md.push("");
  md.push(`## Continue with AetherStack`);
  for (const line of overview.howToContinue) md.push(`1. ${line}`);
  md.push("");
  md.push(`Gateway: \`${overview.aetherstack.baseUrl}\``);
  md.push(`Chat UI: \`${overview.aetherstack.chatUiUrl}\``);
  md.push(`Default model: \`${overview.aetherstack.defaultModel}\``);
  md.push("");
  md.push(`---`);
  md.push(
    `_Project metadata for AetherStack. Do not put API keys here. Prefer User settings or env AETHERSTACK_API_KEY._`
  );

  const mdPath = path.join(dir, "project-overview.md");
  fs.writeFileSync(mdPath, md.join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function httpJson(urlStr, headers = {}, timeoutMs = 5000) {
  return request(urlStr, { headers, timeoutMs });
}

async function fetchModels() {
  const { baseUrl } = cfg();
  const apiKey = await getApiKey();
  const url = baseUrl.replace(/\/$/, "") + "/models";
  return httpJson(url, { Authorization: `Bearer ${apiKey}` });
}

function continueConfigYaml(c, models) {
  // OpenAI-compatible → LiteLLM
  // Do NOT write real API keys into workspace files (they get committed).
  // Continue accepts a placeholder; set AETHERSTACK_API_KEY in the environment
  // or put the key only in User settings (not Workspace).
  const keyPlaceholder = "${{ secrets.AETHERSTACK_API_KEY }}";
  const entries = models
    .map((model) => {
      const caps = Array.isArray(model.capabilities) ? model.capabilities : [];
      const roles = caps.includes("code") ? "[chat, edit, apply]" : "[chat]";
      const label = model.alias
        .split(/[-_]/)
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
      return `  - name: ${JSON.stringify(`Aether ${label}`)}
    provider: openai
    model: ${JSON.stringify(model.alias)}
    apiBase: ${JSON.stringify(c.baseUrl)}
    apiKey: ${keyPlaceholder}
    roles: ${roles}`;
    })
    .join("\n\n");
  return `name: AetherStack
version: 1.0.0
schema: v1
# Generated from live Aether Hub capability availability.
# apiBase is safe to commit. Do not put secrets in this file.
# Set env AETHERSTACK_API_KEY=sk-... (default lab: sk-aether-local)
# or configure aetherstack.apiKey in VS Code *User* settings.

models:
${entries}
`;
}

async function fetchAvailableModels({ force = false } = {}) {
  if (!force && modelVerificationCache && Date.now() - modelVerificationCache.checkedAt < 5 * 60_000) {
    return modelVerificationCache.value;
  }
  const apiKey = await getApiKey();
  const [matrixResponse, gatewayResponse] = await Promise.all([
    httpJson("http://127.0.0.1:8766/api/matrix"),
    httpJson("http://127.0.0.1:4000/v1/models", { Authorization: `Bearer ${apiKey}` }),
  ]);
  if (matrixResponse.status !== 200 || !matrixResponse.body || !matrixResponse.body.models) {
    throw new Error(`capability matrix returned HTTP ${matrixResponse.status}`);
  }
  if (gatewayResponse.status !== 200) {
    throw new Error(`gateway model list returned HTTP ${gatewayResponse.status}`);
  }
  const gatewayIds = (gatewayResponse.body.data || []).map((model) => model.id);
  const candidates = selectAvailableModels(matrixResponse.body, gatewayIds, null, 32);
  const hostCliModels = Object.entries(matrixResponse.body.models || {})
    .filter(([, model]) => model.available === true && model.executor === "host_cli")
    .map(([alias, model]) => ({ alias, ...model }));
  const checks = await Promise.all(
    candidates.map(async (model) => {
      try {
        const health = await httpJson(
          `http://127.0.0.1:4000/health?model=${encodeURIComponent(model.alias)}`,
          { Authorization: `Bearer ${apiKey}` },
          30_000
        );
        const body = health.body || {};
        return health.status === 200 && Number(body.healthy_count || 0) > 0 && Number(body.unhealthy_count || 0) === 0
          ? model.alias
          : null;
      } catch {
        return null;
      }
    })
  );
  const gatewayModels = selectAvailableModels(matrixResponse.body, gatewayIds, checks.filter(Boolean));
  const value = {
    matrix: matrixResponse.body,
    models: [...hostCliModels, ...gatewayModels],
    gatewayModels,
    checked: candidates.length,
  };
  modelVerificationCache = { checkedAt: Date.now(), value };
  return value;
}

async function fetchInferenceStatus() {
  const response = await httpJson("http://127.0.0.1:8766/api/inference/status");
  if (response.status !== 200 || !response.body || typeof response.body !== "object") return null;
  return response.body;
}

class OverviewProvider {
  constructor() {
    this._onDidChangeTreeData = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    this.overview = null;
    this.runtime = { checking: true, up: false, services: SERVICES.map((service) => ({ ...service, ok: false, error: "checking" })) };
    this.availableModels = [];
    this.inference = null;
  }
  refresh(overview) {
    if (overview !== undefined) this.overview = overview;
    this._onDidChangeTreeData.fire();
  }
  updateRuntime(runtime, availableModels = this.availableModels, inference = this.inference) {
    this.runtime = runtime;
    this.availableModels = availableModels || [];
    this.inference = inference;
    this._onDidChangeTreeData.fire();
  }
  getTreeItem(el) {
    return el;
  }
  getChildren(el) {
    if (!el) {
      const roots = [
        treeCmd("$(comment-discussion) Open AetherStack Chat", "aetherstack.openChat"),
        treeCmd("$(dashboard) Open Control Center", "aetherstack.openControlCenter"),
        treeCmd("$(play) Start all services", "aetherstack.startAll"),
        treeCmd("$(cloud-download) Install verified runtime", "aetherstack.installRuntime"),
        treeCmd("$(refresh) Refresh authenticated host CLIs", "aetherstack.refreshHostClis"),
      ];
      const summary = new vscode.TreeItem(
        this.runtime.checking
          ? "$(sync~spin) Checking AetherStack…"
          : this.runtime.up
            ? "$(check-all) AetherStack is up"
            : "$(error) AetherStack has service errors",
        vscode.TreeItemCollapsibleState.None
      );
      summary.tooltip = this.runtime.checkedAt ? `Checked ${this.runtime.checkedAt}` : "Checking local services";
      roots.push(summary);
      for (const service of this.runtime.services || []) {
        const item = new vscode.TreeItem(service.url, vscode.TreeItemCollapsibleState.None);
        item.description = service.ok ? "OK" : `ERROR: ${service.error || "not running"}`;
        item.iconPath = new vscode.ThemeIcon(service.ok ? "pass" : "error");
        item.tooltip = `${service.name}\nHealth: ${service.healthUrl}\n${service.ok ? "OK" : service.error}`;
        item.command = { command: "aetherstack.openUrl", title: `Open ${service.name}`, arguments: [service.url] };
        roots.push(item);
      }
      if (cfg().showActiveModel) {
        const active = (this.inference && this.inference.active) || [];
        const current = active.map((entry) => entry.model).filter(Boolean);
        const item = new vscode.TreeItem(
          current.length ? `$(pulse) Running model: ${current.join(", ")}` : "$(circle-outline) Model activity: idle",
          vscode.TreeItemCollapsibleState.None
        );
        item.tooltip = current.length
          ? `Active inference request(s): ${current.join(", ")}`
          : this.inference && this.inference.last
            ? `Last model: ${this.inference.last.model} (${this.inference.last.state})`
            : "No inference has been observed yet.";
        roots.push(item);
      }
      const liveModels = new vscode.TreeItem(
        `Available models (${this.availableModels.length})`,
        vscode.TreeItemCollapsibleState.Collapsed
      );
      liveModels.contextValue = "availableModels";
      roots.push(liveModels);
      const project = new vscode.TreeItem("Project AI tools", vscode.TreeItemCollapsibleState.Collapsed);
      project.contextValue = "projectTools";
      roots.push(project);
      if (this.overview) {
        const src = new vscode.TreeItem(
          `AI history sources (${this.overview.sources.length})`,
          vscode.TreeItemCollapsibleState.Collapsed
        );
        src.contextValue = "sources";
        roots.push(src);
      }
      return roots;
    }
    if (el.contextValue === "availableModels") {
      if (!this.availableModels.length) {
        return [new vscode.TreeItem("No live models reported by capability matrix", vscode.TreeItemCollapsibleState.None)];
      }
      return this.availableModels.map((model) => {
        const item = new vscode.TreeItem(model.alias, vscode.TreeItemCollapsibleState.None);
        item.description = `${model.tier || "unknown"} · ${(model.capabilities || []).join(", ")}`;
        item.tooltip = model.availability_reason || "Available";
        return item;
      });
    }
    if (el.contextValue === "projectTools") {
      const items = [
        treeCmd("Scan Project AI History", "aetherstack.scanProject"),
        treeCmd("Wire available models to Continue.dev", "aetherstack.configureContinue"),
        treeCmd("Open combined AetherStack Chat", "aetherstack.openChat"),
        treeCmd("Open optional Open WebUI", "aetherstack.openChatUI"),
        treeCmd("Open Aether Hub", "aetherstack.openHub"),
        treeCmd("List gateway models", "aetherstack.openModels"),
        treeCmd("Write .vscode settings", "aetherstack.configureWorkspace"),
      ];
      if (this.overview) {
        const models = new vscode.TreeItem(
          `Models mentioned in project (${this.overview.modelsMentioned.length})`,
          vscode.TreeItemCollapsibleState.Collapsed
        );
        models.contextValue = "models";
        items.push(models);
      }
      return items;
    }
    if (!this.overview) return [];
    if (el.contextValue === "sources") {
      if (!this.overview.sources.length) {
        return [new vscode.TreeItem("No AI history folders found", vscode.TreeItemCollapsibleState.None)];
      }
      return this.overview.sources.map((s) => {
        const t = new vscode.TreeItem(
          `${s.label} (${s.fileCount} files)`,
          vscode.TreeItemCollapsibleState.Collapsed
        );
        t.contextValue = "source";
        t.tooltip = s.path;
        t.source = s;
        return t;
      });
    }
    if (el.contextValue === "source" && el.source) {
      return (el.source.recent || []).map((r) => {
        const t = new vscode.TreeItem(r.name, vscode.TreeItemCollapsibleState.None);
        t.description = r.mtime;
        t.command = {
          command: "vscode.open",
          title: "Open",
          arguments: [vscode.Uri.file(path.join(this.overview.workspace, r.name))],
        };
        return t;
      });
    }
    if (el.contextValue === "models") {
      if (!this.overview.modelsMentioned.length) {
        return [new vscode.TreeItem("None detected", vscode.TreeItemCollapsibleState.None)];
      }
      return this.overview.modelsMentioned.map(
        (m) => new vscode.TreeItem(m, vscode.TreeItemCollapsibleState.None)
      );
    }
    return [];
  }
}

function treeCmd(label, command) {
  const t = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
  t.command = { command, title: label };
  return t;
}

function readEnvValue(file, key) {
  if (!fs.existsSync(file)) return "";
  for (const rawLine of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match || match[1] !== key) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    } else {
      value = value.replace(/\s+#.*$/, "").trim();
    }
    return value;
  }
  return "";
}

async function importGatewayKey(context, stackRoot) {
  const key = readEnvValue(path.join(stackRoot, ".env"), "LITELLM_MASTER_KEY");
  if (key) await context.secrets.store("aetherstack.apiKey", key);
  return Boolean(key);
}

function syncContinueGatewayKey(stackRoot) {
  const key = readEnvValue(path.join(stackRoot, ".env"), "LITELLM_MASTER_KEY");
  if (!key || /[\r\n]/.test(key)) return false;
  const continueDir = path.join(os.homedir(), ".continue");
  const envPath = path.join(continueDir, ".env");
  fs.mkdirSync(continueDir, { recursive: true });
  const existing = fs.existsSync(envPath) ? fs.readFileSync(envPath, "utf8") : "";
  const lines = existing ? existing.split(/\r?\n/) : [];
  const next = [];
  let replaced = false;
  for (const line of lines) {
    if (/^\s*AETHERSTACK_API_KEY\s*=/.test(line)) {
      if (!replaced) next.push(`AETHERSTACK_API_KEY=${key}`);
      replaced = true;
    } else if (line || next.length) {
      next.push(line);
    }
  }
  if (!replaced) next.push(`AETHERSTACK_API_KEY=${key}`);
  fs.writeFileSync(envPath, `${next.join(os.EOL).replace(/(?:\r?\n)+$/, "")}${os.EOL}`, { encoding: "utf8", mode: 0o600 });
  try {
    fs.chmodSync(envPath, 0o600);
  } catch {
    // Windows ACLs and some remote filesystems do not implement POSIX modes.
  }
  return true;
}

async function resolveStackRoot(context, prompt = false) {
  const workspacePaths = (vscode.workspace.workspaceFolders || []).map((folder) => folder.uri.fsPath);
  let root = findStackRoot({
    configuredPath: cfg().stackPath,
    rememberedPath: context.globalState.get("aetherstack.stackRoot"),
    workspacePaths,
    extensionPath: context.extensionPath,
    cwd: process.cwd(),
  });
  if (!root && prompt) root = await installManagedRuntime(context);
  if (root) {
    await context.globalState.update("aetherstack.stackRoot", root);
    await importGatewayKey(context, root);
  }
  return root;
}

async function installManagedRuntime(context) {
  if (!context.globalStorageUri || !context.globalStorageUri.fsPath) {
    throw new Error("VS Code did not provide a managed extension storage directory.");
  }
  const result = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `AetherStack: installing verified Runtime ${extensionManifest.version}`,
      cancellable: false,
    },
    () => installRuntimeBundle({
      version: extensionManifest.version,
      storagePath: context.globalStorageUri.fsPath,
      bundledPath: path.join(context.extensionPath, "bundled-runtime"),
    })
  );
  await vscode.workspace
    .getConfiguration("aetherstack")
    .update("stackPath", result.root, vscode.ConfigurationTarget.Global);
  await context.globalState.update("aetherstack.stackRoot", result.root);
  await importGatewayKey(context, result.root);
  vscode.window.showInformationMessage(
    result.reused
      ? `AetherStack Runtime ${result.version} is ready.`
      : `AetherStack Runtime ${result.version} installed and checksum verified.`
  );
  return result.root;
}

async function chooseStackRoot(context) {
  const selection = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    openLabel: "Use this AetherStack installation",
    title: "Choose the folder containing docker-compose.yml and aether-hub",
  });
  if (!selection || !selection.length) return null;
  const root = selection[0].fsPath;
  if (!isStackRoot(root)) {
    vscode.window.showErrorMessage(
      "That folder is not an AetherStack installation. Expected docker-compose.yml, litellm_config.yaml, and aether-hub/."
    );
    return null;
  }
  await vscode.workspace
    .getConfiguration("aetherstack")
    .update("stackPath", root, vscode.ConfigurationTarget.Global);
  await context.globalState.update("aetherstack.stackRoot", root);
  await importGatewayKey(context, root);
  return root;
}

async function writeAvailableContinueConfig({ provider, replaceExisting, openDocument = false }) {
  const root = workspaceRoot();
  if (!root) throw new Error("Open a project folder before wiring Continue.");
  const discovered = await fetchAvailableModels();
  provider.updateRuntime(provider.runtime, discovered.models, provider.inference);
  if (!discovered.gatewayModels.length) {
    throw new Error("No LiteLLM-backed models are available for Continue.dev. Host CLI agents remain available inside AetherStack Chat.");
  }

  const dir = path.join(root, ".continue");
  const confPath = path.join(dir, "config.yaml");
  if (fs.existsSync(confPath) && !replaceExisting) return { written: false, confPath, models: discovered.gatewayModels };
  fs.mkdirSync(dir, { recursive: true });
  if (fs.existsSync(confPath)) {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    fs.copyFileSync(confPath, `${confPath}.bak-${stamp}`);
  }
  fs.writeFileSync(confPath, continueConfigYaml(cfg(), discovered.gatewayModels), "utf8");

  const overview = buildOverview(root);
  writeOverviewFiles(root, overview);
  provider.refresh(overview);
  if (openDocument) {
    const doc = await vscode.workspace.openTextDocument(confPath);
    await vscode.window.showTextDocument(doc, { preview: true });
  }
  return { written: true, confPath, models: discovered.gatewayModels };
}

function nonce() {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let value = "";
  for (let index = 0; index < 32; index += 1) value += alphabet.charAt(Math.floor(Math.random() * alphabet.length));
  return value;
}

class ControlCenter {
  constructor(context, messageHandler, stateProvider) {
    this.context = context;
    this.messageHandler = messageHandler;
    this.stateProvider = stateProvider;
    this.panel = null;
    this.notice = "";
  }

  show() {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.One);
      this.render();
      return;
    }
    this.panel = vscode.window.createWebviewPanel(
      "aetherstack.controlCenter",
      "AetherStack Control Center",
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    const template = fs.readFileSync(path.join(this.context.extensionPath, "control-center.html"), "utf8");
    const token = nonce();
    this.panel.webview.html = template
      .replaceAll("{{NONCE}}", token)
      .replaceAll("{{CSP_SOURCE}}", this.panel.webview.cspSource);
    this.panel.onDidDispose(() => {
      this.panel = null;
    }, null, this.context.subscriptions);
    this.panel.webview.onDidReceiveMessage(async (message) => {
      try {
        await this.messageHandler(message || {});
      } catch (error) {
        this.notice = error.message || String(error);
        vscode.window.showErrorMessage(`AetherStack: ${this.notice}`);
      }
      await this.render();
    }, null, this.context.subscriptions);
  }

  async render(notice) {
    if (notice !== undefined) this.notice = notice;
    if (!this.panel) return;
    const state = await this.stateProvider();
    await this.panel.webview.postMessage({ type: "state", state: { ...state, notice: this.notice } });
  }
}

class HubChat {
  constructor(context) {
    this.context = context;
    this.panel = null;
    this.view = null;
    this.services = [];
    this.activityWords = [];
    this.conversations = this.context.globalState.get("aetherstack.conversations", []);
    this.surfaceStates = new WeakMap();
    this.activeRuns = new WeakMap();
  }

  async hubRequest(pathname, options = {}) {
    const response = await request(`http://127.0.0.1:8766${pathname}`, { timeoutMs: 190_000, ...options });
    if (response.status < 200 || response.status >= 300) {
      const detail = response.body && (response.body.error || response.body.detail);
      throw new Error(detail || `Aether Hub returned HTTP ${response.status}`);
    }
    return response.body || {};
  }

  stateFor(webview = this.activeWebview()) {
    if (!webview) return { history: [], activeConversationId: null, selectedServiceId: "auto" };
    let state = this.surfaceStates.get(webview);
    if (!state) {
      state = { history: [], activeConversationId: null, selectedServiceId: "auto" };
      this.surfaceStates.set(webview, state);
    }
    return state;
  }

  sanitizeTranscript(transcript) {
    return (Array.isArray(transcript) ? transcript : []).slice(-40).flatMap((item) => {
      if (!item || !["user", "assistant"].includes(item.role)) return [];
      const value = String(item.value ?? item.content ?? "").slice(0, 200_000);
      return [{ role: item.role, value }];
    });
  }

  async hydrateSurface(webview, message = {}) {
    const state = this.stateFor(webview);
    const requestedId = typeof message.conversationId === "string" ? message.conversationId : null;
    let entry = requestedId ? this.conversations.find((item) => item.id === requestedId) : null;
    const restored = this.sanitizeTranscript(message.transcript);
    if (!entry && restored.length) {
      const now = Date.now();
      entry = {
        id: `${now}-${Math.random().toString(36).slice(2, 10)}`,
        title: titleFromTranscript(restored),
        transcript: restored,
        selectedServiceId: String(message.serviceId || "auto"),
        updatedAt: now,
      };
      this.conversations = capConversations([...this.conversations, entry]);
      await this.context.globalState.update("aetherstack.conversations", this.conversations);
    }
    state.activeConversationId = entry ? entry.id : null;
    state.history = (entry ? this.sanitizeTranscript(entry.transcript) : restored)
      .map((item) => ({ role: item.role, content: item.value }));
    state.selectedServiceId = String((entry && entry.selectedServiceId) || message.serviceId || "auto");
    await webview.postMessage({
      type: "conversationSwitched",
      id: state.activeConversationId,
      transcript: state.history.map((item) => ({ role: item.role, value: item.content })),
      serviceId: state.selectedServiceId,
    });
  }

  async saveConversationSnapshot(transcript, webview = this.activeWebview()) {
    if (!transcript.length) return;
    const state = this.stateFor(webview);
    const now = Date.now();
    const title = titleFromTranscript(transcript);
    let entry = this.conversations.find((item) => item.id === state.activeConversationId);
    if (!entry) {
      entry = { id: `${now}-${Math.random().toString(36).slice(2, 10)}`, title, updatedAt: now };
      this.conversations.push(entry);
      state.activeConversationId = entry.id;
    }
    entry.transcript = this.sanitizeTranscript(transcript);
    entry.selectedServiceId = state.selectedServiceId;
    if (!entry.customTitle) entry.title = title;
    entry.updatedAt = now;
    this.conversations = capConversations(this.conversations);
    await this.context.globalState.update("aetherstack.conversations", this.conversations);
  }

  conversationSummaries() {
    return capConversations(this.conversations).map(({ id, title, updatedAt }) => ({ id, title, updatedAt }));
  }

  async loadServices(force = false, webview = this.activeWebview()) {
    const pathname = force ? "/api/services/refresh" : "/api/services";
    const options = force ? { method: "POST", body: {} } : {};
    const body = await this.hubRequest(pathname, options);
    this.services = Array.isArray(body.services) ? body.services : [];
    try {
      const activity = await this.hubRequest("/api/activity-words");
      this.activityWords = Array.isArray(activity.words) ? activity.words.filter((item) => item.enabled !== false) : [];
    } catch {
      this.activityWords = [];
    }
    await this.postState(this.services.length ? "" : "No capability-matched services are currently available.", false, webview);
  }

  activeWebview() {
    return (this.view && this.view.webview) || (this.panel && this.panel.webview) || null;
  }

  async hasVisionModel() {
    try {
      const matrix = await this.hubRequest("/api/matrix");
      return Object.values(matrix.models || {}).some(
        (model) => model.available && model.executor !== "host_cli" && (model.capabilities || []).includes("vision")
      );
    } catch {
      return false;
    }
  }

  async run(message, webview = this.activeWebview()) {
    if (!webview) throw new Error("AetherStack Chat view is not available.");
    this.activeRuns.get(webview)?.abort();
    const controller = new AbortController();
    this.activeRuns.set(webview, controller);
    await webview.postMessage({ type: "busy", value: true });
    let inferenceTimer = null;
    try {
      const state = this.stateFor(webview);
      const requestedService = String(message.serviceId || state.selectedServiceId || "auto");
      const parsed = parseChatInput(
        message.prompt,
        requestedService,
        this.services.map((service) => service.id)
      );
      if (parsed.action === "error") throw new Error(parsed.message);
      if (parsed.action === "help" || parsed.action === "presets") {
        const content = parsed.action === "help"
          ? commandHelp(this.services)
          : this.services.map((service) => `/${service.id} — ${service.label}: ${service.summary}`).join("\n");
        await webview.postMessage({ type: "command", content });
        return;
      }
      if (parsed.action === "select") {
        state.selectedServiceId = parsed.serviceId;
        await webview.postMessage({
          type: "route",
          selection: parsed.serviceId === "auto"
            ? { service_id: "", label: "Automatic routing", confidence: "ready", source: "slash-command" }
            : { service_id: parsed.serviceId, label: (this.services.find((item) => item.id === parsed.serviceId) || {}).label, confidence: "fixed", source: "slash-command" },
        });
        const entry = this.conversations.find((item) => item.id === state.activeConversationId);
        if (entry) {
          entry.selectedServiceId = state.selectedServiceId;
          entry.updatedAt = Date.now();
          await this.context.globalState.update("aetherstack.conversations", this.conversations);
        }
        await webview.postMessage({ type: "command", content: parsed.serviceId === "auto" ? "Automatic intent routing is active." : `Preset selected: ${parsed.serviceId}.` });
        return;
      }
      const prompt = String(parsed.prompt || "").trim();
      if (!prompt) throw new Error("Enter a goal first.");
      const attachments = Array.isArray(message.attachments) ? message.attachments : [];
      if (attachments.some((item) => item.type === "image") && !(await this.hasVisionModel())) {
        throw new Error("No vision-capable model is currently available for the attached image.");
      }
      let serviceId = parsed.serviceId;
      state.selectedServiceId = parsed.serviceId;
      let selection;
      if (serviceId === "auto") {
        selection = await this.hubRequest("/api/services/classify", {
          method: "POST",
          body: { goal: prompt },
          signal: controller.signal,
        });
        serviceId = String(selection.service_id || "");
        if (!this.services.some((service) => service.id === serviceId)) {
          throw new Error("AetherStack could not map this request to an available service preset.");
        }
        selection.source = "intent-analysis";
      } else if (parsed.command) {
        const service = this.services.find((item) => item.id === serviceId) || {};
        selection = { service_id: serviceId, label: service.label || serviceId, confidence: "fixed", source: "slash-command" };
      }
      if (selection) await webview.postMessage({ type: "route", selection });
      await webview.postMessage({ type: "inferenceSetting", enabled: cfg().showActiveModel });
      const publishInference = async () => {
        if (!cfg().showActiveModel) return;
        try {
          const inference = await fetchInferenceStatus();
          await webview.postMessage({ type: "inference", inference });
        } catch {
          /* The normal service result will still report the models used. */
        }
      };
      if (cfg().showActiveModel) {
        inferenceTimer = setInterval(publishInference, 1200);
        await publishInference();
      }
      const requestBody = {
        goal: prompt,
        lean_mode: ["off", "balanced", "strict"].includes(message.leanMode) ? message.leanMode : "balanced",
        token_saver: Boolean(message.tokenSaver),
        history: state.history.slice(-8),
        attachments,
      };
      let result = null;
      let streamedText = "";
      try {
        await requestStream(
          `http://127.0.0.1:8766/api/services/${encodeURIComponent(serviceId)}/run/stream`,
          { method: "POST", body: requestBody, signal: controller.signal },
          (event) => {
            if (event.type === "delta") {
              streamedText += event.text || "";
              webview.postMessage({ type: "delta", text: event.text || "" });
            } else if (event.type === "done") {
              result = event.result;
            }
            // event.type === "error" (an application-level failure reported by the server after
            // the stream started) is deliberately not thrown here — see the note at the top of
            // this task. result stays null, so the `if (!result)` fallback below correctly
            // triggers a non-streaming retry regardless of whether this was a transport failure
            // (caught by the outer try/catch via requestStream's own reject) or an application-
            // level error event (which resolves requestStream normally but leaves result unset).
          }
        );
      } catch (error) {
        if (error && error.name === "AbortError") throw error;
        // transport-level failure (connection reset, timeout, non-2xx from requestStream's own
        // reject path) — fall through to the non-streaming retry below.
      }
      if (!result) {
        if (streamedText) {
          await webview.postMessage({ type: "deltaInterrupted" });
        }
        result = await this.hubRequest(`/api/services/${encodeURIComponent(serviceId)}/run`, {
          method: "POST",
          body: requestBody,
          signal: controller.signal,
        });
      }
      if (selection) result.selection = selection;
      state.history.push({ role: "user", content: prompt }, { role: "assistant", content: result.answer || "" });
      await this.saveConversationSnapshot(
        state.history.map((entry) => ({ role: entry.role, value: entry.content })),
        webview
      );
      await webview.postMessage({ type: "conversationIdentity", id: state.activeConversationId, serviceId: state.selectedServiceId });
      await webview.postMessage({ type: "conversations", items: this.conversationSummaries() });
      await webview.postMessage({ type: "result", result, streamed: Boolean(streamedText) });
    } finally {
      this.activeRuns.delete(webview);
      if (inferenceTimer) clearInterval(inferenceTimer);
      await webview.postMessage({ type: "inference", inference: { active: [], activeCount: 0 } });
      await webview.postMessage({ type: "busy", value: false });
    }
  }

  async postState(notice = "", error = false, webview = this.activeWebview()) {
    if (!webview) return;
    await webview.postMessage({
      type: "state",
      services: this.services,
      activityWords: this.activityWords,
      showActiveModel: cfg().showActiveModel,
      cwd: workspaceRoot() || "",
      notice,
      error,
    });
  }

  configureWebview(webview) {
    webview.options = { enableScripts: true };
    const template = fs.readFileSync(path.join(this.context.extensionPath, "chat.html"), "utf8");
    const renderScript = fs.readFileSync(path.join(this.context.extensionPath, "chat-render.js"), "utf8");
    webview.html = template
      .replaceAll("{{NONCE}}", nonce())
      .replaceAll("{{CSP_SOURCE}}", webview.cspSource)
      .replace("{{CHAT_RENDER_JS}}", () => renderScript);
    webview.onDidReceiveMessage(async (message) => {
      try {
        if (message.type === "ready") {
          await this.hydrateSurface(webview, message);
          await this.loadServices(false, webview);
        }
        else if (message.type === "refresh") await this.loadServices(true, webview);
        else if (message.type === "run") await this.run(message, webview);
        else if (message.type === "cancel") this.activeRuns.get(webview)?.abort();
        else if (message.type === "openAdvanced") await vscode.env.openExternal(vscode.Uri.parse("http://127.0.0.1:8766/advanced"));
        else if (message.type === "action") {
          if (message.action === "toggleActiveModel") {
            await vscode.workspace.getConfiguration("aetherstack")
              .update("showActiveModel", Boolean(message.value), vscode.ConfigurationTarget.Global);
            await webview.postMessage({ type: "inferenceSetting", enabled: Boolean(message.value) });
            return;
          }
          const commands = {
            openControlCenter: ["aetherstack.openControlCenter"],
            openSettings: ["workbench.action.openSettings", "@ext:AetherStack.aetherstack"],
            setApiKey: ["aetherstack.setApiKey"],
            refreshHostClis: ["aetherstack.refreshHostClis"],
            configureWorkspace: ["aetherstack.configureWorkspace"],
          };
          const invocation = commands[message.action];
          if (!invocation) throw new Error("Unknown AetherStack action");
          await vscode.commands.executeCommand(...invocation);
        }
        else if (message.type === "openEditor") this.showPanel();
        else if (message.type === "listConversations") {
          await webview.postMessage({ type: "conversations", items: this.conversationSummaries() });
        } else if (message.type === "newConversation") {
          const state = this.stateFor(webview);
          state.activeConversationId = null;
          state.history = [];
          state.selectedServiceId = "auto";
          await webview.postMessage({ type: "conversationSwitched", id: null, transcript: [], serviceId: "auto" });
        } else if (message.type === "switchConversation") {
          const state = this.stateFor(webview);
          const entry = this.conversations.find((item) => item.id === message.id);
          state.activeConversationId = entry ? entry.id : null;
          state.history = entry ? this.sanitizeTranscript(entry.transcript).map((item) => ({ role: item.role, content: item.value })) : [];
          state.selectedServiceId = String((entry && entry.selectedServiceId) || "auto");
          await webview.postMessage({ type: "conversationSwitched", id: state.activeConversationId, transcript: entry ? entry.transcript : [], serviceId: state.selectedServiceId });
        } else if (message.type === "deleteConversation") {
          const state = this.stateFor(webview);
          this.conversations = this.conversations.filter((item) => item.id !== message.id);
          await this.context.globalState.update("aetherstack.conversations", this.conversations);
          if (state.activeConversationId === message.id) {
            state.activeConversationId = null;
            state.history = [];
            state.selectedServiceId = "auto";
            await webview.postMessage({ type: "conversationSwitched", id: null, transcript: [], serviceId: "auto" });
          }
          await webview.postMessage({ type: "conversations", items: this.conversationSummaries() });
        } else if (message.type === "renameConversation") {
          const entry = this.conversations.find((item) => item.id === message.id);
          if (!entry) return;
          const title = await vscode.window.showInputBox({
            title: "Rename AetherStack conversation",
            value: entry.title,
            prompt: "Conversation name",
            validateInput: (value) => value.trim() ? null : "Enter a name.",
          });
          if (title === undefined) return;
          entry.title = title.trim().slice(0, 80);
          entry.customTitle = true;
          entry.updatedAt = Date.now();
          this.conversations = capConversations(this.conversations);
          await this.context.globalState.update("aetherstack.conversations", this.conversations);
          await webview.postMessage({ type: "conversations", items: this.conversationSummaries() });
        } else if (message.type === "updateConversation") {
          const state = this.stateFor(webview);
          const entry = this.conversations.find((item) => item.id === state.activeConversationId);
          if (!entry) return;
          entry.transcript = this.sanitizeTranscript(message.transcript);
          entry.selectedServiceId = String(message.serviceId || state.selectedServiceId || "auto");
          entry.updatedAt = Date.now();
          this.conversations = capConversations(this.conversations);
          await this.context.globalState.update("aetherstack.conversations", this.conversations);
        }
      } catch (error) {
        await webview.postMessage({ type: "error", message: error.message || String(error) });
      }
    }, null, this.context.subscriptions);
  }

  resolveWebviewView(view) {
    this.view = view;
    this.configureWebview(view.webview);
    view.onDidDispose(() => { if (this.view === view) this.view = null; }, null, this.context.subscriptions);
  }

  async show() {
    await vscode.commands.executeCommand("aetherstack.chatView.focus");
    if (this.view) this.loadServices(false, this.view.webview).catch((error) => this.postState(error.message, true, this.view.webview));
  }

  showPanel() {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.One);
      this.loadServices(false, this.panel.webview).catch((error) => this.postState(error.message, true, this.panel.webview));
      return;
    }
    this.panel = vscode.window.createWebviewPanel(
      "aetherstack.chat",
      "AetherStack Chat",
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    this.configureWebview(this.panel.webview);
    this.panel.onDidDispose(() => { this.panel = null; }, null, this.context.subscriptions);
  }
}

/**
 * @param {vscode.ExtensionContext} context
 */
async function activate(context) {
  secretStorage = context.secrets;
  await migrateLegacyApiKey(context);
  const provider = new OverviewProvider();
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("aetherstack.overview", provider)
  );
  const output = vscode.window.createOutputChannel("AetherStack");
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.command = "aetherstack.openControlCenter";
  statusBar.show();
  context.subscriptions.push(output, statusBar);

  let bridgeToken = await context.secrets.get("aetherstack.cliBridgeToken");
  const cliBridge = createCliBridge({ token: bridgeToken || undefined, cwd: workspaceRoot() || process.cwd() });
  if (!bridgeToken) {
    bridgeToken = cliBridge.token;
    await context.secrets.store("aetherstack.cliBridgeToken", bridgeToken);
  }
  process.env.AETHER_CLI_BRIDGE_TOKEN = bridgeToken;
  process.env.AETHER_CLI_BRIDGE_URL = "http://host.docker.internal:8767";
  try {
    const bridgeState = await cliBridge.start();
    output.appendLine(`[cli-bridge] ${bridgeState.reused ? "reusing existing" : "started"} host bridge on port ${bridgeState.port}`);
  } catch (error) {
    output.appendLine(`[cli-bridge] unavailable: ${error.message || error}`);
  }
  context.subscriptions.push(new vscode.Disposable(() => cliBridge.stop()));

  let stackRoot = await resolveStackRoot(context, false);
  let containers = [];
  let technicalError = "";
  let stackActionInProgress = null;
  const hubChat = new HubChat(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("aetherstack.chatView", hubChat, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  if (typeof vscode.chat?.createChatParticipant === "function") {
    try {
      const participant = vscode.chat.createChatParticipant("aetherstack.chat", createChatRequestHandler(hubChat));
      participant.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "icon.png");
      context.subscriptions.push(participant);
    } catch (error) {
      output.appendLine(`[chat-participant] registration failed: ${error.message || error}`);
    }
  } else {
    output.appendLine("[chat-participant] vscode.chat.createChatParticipant is unavailable on this VS Code build; AetherStack chat stays webview-only.");
  }

  function updateStatusBar() {
    const active = cfg().showActiveModel && provider.inference && Array.isArray(provider.inference.active)
      ? provider.inference.active.map((entry) => entry.model).filter(Boolean)
      : [];
    if (active.length) {
      statusBar.text = `$(pulse) AetherStack: ${active.join(", ")}`;
      statusBar.tooltip = `Inference running on ${active.join(", ")}`;
    } else if (provider.runtime.checking) {
      statusBar.text = "$(sync~spin) AetherStack: Checking";
      statusBar.tooltip = "Checking AetherStack services";
    } else if (provider.runtime.up) {
      statusBar.text = "$(check-all) AetherStack: Up";
      statusBar.tooltip = "All AetherStack services are healthy";
    } else {
      statusBar.text = "$(error) AetherStack: Error";
      statusBar.tooltip = (provider.runtime.services || [])
        .filter((service) => !service.ok)
        .map((service) => `${service.name}: ${service.error}`)
        .join("\n");
    }
  }

  async function refreshRuntime(includeTechnical = false, includeModels = false) {
    if (runtimeRefresh) {
      const hadTechnical = runtimeRefreshIncludesTechnical;
      const hadModels = runtimeRefreshIncludesModels;
      const result = await runtimeRefresh;
      if ((includeTechnical && !hadTechnical) || (includeModels && !hadModels)) {
        return refreshRuntime(includeTechnical, includeModels);
      }
      return result;
    }
    runtimeRefreshIncludesTechnical = includeTechnical;
    runtimeRefreshIncludesModels = includeModels;
    runtimeRefresh = (async () => {
      const runtime = await checkServices();
      let models = provider.availableModels;
      let inference = provider.inference;
      if (runtime.up && includeModels) {
        try {
          models = (await fetchAvailableModels()).models;
        } catch (error) {
          output.appendLine(`[models] ${error.message}`);
          models = [];
        }
        if (cfg().showActiveModel) {
          try {
            inference = await fetchInferenceStatus();
          } catch (error) {
            output.appendLine(`[inference] ${error.message}`);
            inference = null;
          }
        } else {
          inference = null;
        }
      } else if (!runtime.up) {
        models = [];
        inference = null;
      }
      if (runtime.up && !includeModels && cfg().showActiveModel) {
        try {
          inference = await fetchInferenceStatus();
        } catch (error) {
          output.appendLine(`[inference] ${error.message}`);
          inference = null;
        }
      } else if (!cfg().showActiveModel) {
        inference = null;
      }
      provider.updateRuntime(runtime, models, inference);
      updateStatusBar();

      if (includeTechnical) {
        stackRoot = await resolveStackRoot(context, false);
        if (stackRoot) {
          try {
            containers = await composeDetails(stackRoot);
            technicalError = "";
          } catch (error) {
            containers = [];
            technicalError = error.message;
          }
        } else {
          containers = [];
          technicalError = "Choose the local AetherStack installation folder to inspect Docker Compose.";
        }
      }
      return runtime;
    })();
    try {
      return await runtimeRefresh;
    } finally {
      runtimeRefresh = null;
      runtimeRefreshIncludesTechnical = false;
      runtimeRefreshIncludesModels = false;
    }
  }

  async function reconcileCliProviders(notify = false) {
    stackRoot = await resolveStackRoot(context, false);
    if (!stackRoot) {
      const reason = "Install or choose AetherStack Runtime before refreshing host CLIs.";
      if (notify) vscode.window.showWarningMessage(reason);
      return { changed: false, reason, aliases: [] };
    }
    try {
      const result = await reconcileHostCliBridge({ stackRoot, cliBridge, request, runCompose });
      output.appendLine(`[cli-bridge] ${result.reason}${result.aliases.length ? `: ${result.aliases.join(", ")}` : ""}`);
      modelVerificationCache = null;
      await refreshRuntime(false, true);
      await hubChat.loadServices(true).catch((error) => output.appendLine(`[cli-bridge] Chat service refresh failed: ${error.message}`));
      if (notify) {
        const aliases = result.aliases.length ? result.aliases.join(", ") : "none";
        vscode.window.showInformationMessage(`AetherStack host CLI providers refreshed: ${aliases}.`);
      }
      return result;
    } catch (error) {
      output.appendLine(`[cli-bridge] Hub synchronization failed: ${error.message || error}`);
      if (notify) vscode.window.showErrorMessage(`Cannot refresh AetherStack host CLIs: ${error.message || error}`);
      throw error;
    }
  }

  async function runStackAction(action) {
    if (stackActionInProgress) {
      vscode.window.showWarningMessage(`AetherStack is already ${stackActionInProgress}.`);
      return;
    }
    stackActionInProgress = { start: "starting", stop: "stopping", restart: "restarting" }[action] || action;
    const integrationWarnings = [];
    try {
      stackRoot = await resolveStackRoot(context, true);
      if (!stackRoot) return;
      output.appendLine(`\n[${new Date().toISOString()}] ${action} in ${stackRoot}`);
      if (action === "start" || action === "restart") {
        output.appendLine("First installation can download several gigabytes. Image layers, model pulls, and health checks follow below.");
        output.show(true);
      }
      const actionVerb = { start: "starting", stop: "stopping", restart: "restarting" }[action];
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: `AetherStack: ${actionVerb} all services`,
          cancellable: false,
        },
        async (progress) => {
          if (action === "start") {
            let lastProgressAt = 0;
            const result = await startCompose(stackRoot, {
              onOutput: (chunk) => {
                output.append(chunk);
                const now = Date.now();
                if (now - lastProgressAt < 750) return;
                const line = chunk
                  .split(/[\r\n]+/)
                  .map((part) => part.replace(/\x1b\[[0-9;]*m/g, "").trim())
                  .filter(Boolean)
                  .at(-1);
                if (!line) return;
                lastProgressAt = now;
                progress.report({ message: line.length > 140 ? `${line.slice(0, 137)}…` : line });
              },
            });
            if (!result.streamed) {
              output.append(result.stdout);
              output.append(result.stderr);
            }
          } else if (action === "stop") {
            const result = await stopCompose(stackRoot);
            output.append(result.stdout);
            output.append(result.stderr);
          } else if (action === "restart") {
            const result = await restartCompose(stackRoot);
            output.append(result.stdout);
            output.append(result.stderr);
          }

          if (action !== "stop") {
            progress.report({ message: "Waiting for 3000, 4000, and 8766…" });
            const status = await waitForServices({
              onCheck: (current) => {
                provider.updateRuntime(current, provider.availableModels, provider.inference);
                updateStatusBar();
              },
            });
            if (!status.up) {
              const failures = status.services
                .filter((service) => !service.ok)
                .map((service) => `${service.url} — ${service.error}`)
                .join("; ");
              throw new Error(`services did not become healthy: ${failures}`);
            }
            // startCompose may have created .env from .env.example on first run.
            // Import and sync only after that file is guaranteed to exist.
            try {
              await importGatewayKey(context, stackRoot);
            } catch (error) {
              integrationWarnings.push(`SecretStorage import: ${error.message || error}`);
            }
            if (cfg().autoWireModels) {
              try {
                syncContinueGatewayKey(stackRoot);
              } catch (error) {
                integrationWarnings.push(`Continue key sync: ${error.message || error}`);
              }
            }
          }
        }
      );

      if (action !== "stop") modelVerificationCache = null;
      if (action !== "stop") {
        try {
          await reconcileCliProviders(false);
        } catch (error) {
          integrationWarnings.push(`Host CLI refresh: ${error.message || error}`);
        }
      }
      await refreshRuntime(true, action !== "stop");
      if (action === "start" || action === "restart") {
        let wiring = "";
        if (cfg().autoWireModels && workspaceRoot()) {
          try {
            const result = await writeAvailableContinueConfig({ provider, replaceExisting: false });
            wiring = result.written
              ? ` Wired ${result.models.length} available model(s) to Continue.`
              : " Existing Continue config was preserved.";
          } catch (error) {
            wiring = ` Model wiring: ${error.message}`;
          }
        }
        vscode.window.showInformationMessage(
          `AetherStack is up. http://127.0.0.1:3000/ OK · http://127.0.0.1:4000/ OK · http://127.0.0.1:8766/ OK.${wiring}${integrationWarnings.length ? ` Optional integration warnings: ${integrationWarnings.join("; ")}` : ""}`
        );
      } else {
        vscode.window.showInformationMessage("AetherStack services stopped.");
      }
    } catch (error) {
      output.appendLine(`[error] ${error.message}`);
      output.show(true);
      await refreshRuntime(true);
      vscode.window.showErrorMessage(`AetherStack ${action} failed: ${error.message}`);
    } finally {
      stackActionInProgress = null;
      await controlCenter.render();
    }
  }

  const controlCenter = new ControlCenter(
    context,
    async (message) => {
      const commands = {
        start: "aetherstack.startAll",
        stop: "aetherstack.stopAll",
        restart: "aetherstack.restartAll",
        refresh: "aetherstack.refreshServices",
        logs: "aetherstack.showLogs",
        choosePath: "aetherstack.chooseStackPath",
        installRuntime: "aetherstack.installRuntime",
        refreshHostClis: "aetherstack.refreshHostClis",
      };
      if (commands[message.type]) await vscode.commands.executeCommand(commands[message.type]);
      else if (message.type === "openUrl" && message.url) await vscode.commands.executeCommand("aetherstack.openUrl", message.url);
      else if (message.type === "showActiveModel") {
        await vscode.workspace
          .getConfiguration("aetherstack")
          .update("showActiveModel", Boolean(message.value), vscode.ConfigurationTarget.Global);
        await refreshRuntime(false);
      } else if (message.type === "ready") {
        await refreshRuntime(true);
      }
    },
    async () => ({
      runtime: provider.runtime,
      models: provider.availableModels,
      inference: provider.inference,
      showActiveModel: cfg().showActiveModel,
      stackPath: stackRoot,
      containers,
      technicalError,
      busy: stackActionInProgress,
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.openChat", async () => {
      await hubChat.show();
      const hub = (await checkServices()).services.find((service) => service.id === "hub");
      if (!hub || !hub.ok) {
        vscode.window.showWarningMessage(
          `Aether Hub is not ready: ${(hub && hub.error) || "not running"}. Start all services and retry.`
        );
      }
    }),
    vscode.commands.registerCommand("aetherstack.openChatEditor", () => hubChat.showPanel()),
    vscode.commands.registerCommand("aetherstack.openHub", () =>
      vscode.env.openExternal(vscode.Uri.parse("http://127.0.0.1:8766/"))
    ),
    vscode.commands.registerCommand("aetherstack.openControlCenter", async () => {
      controlCenter.show();
      await refreshRuntime(true);
      await controlCenter.render();
    }),
    vscode.commands.registerCommand("aetherstack.startAll", () => runStackAction("start")),
    vscode.commands.registerCommand("aetherstack.stopAll", () => runStackAction("stop")),
    vscode.commands.registerCommand("aetherstack.restartAll", () => runStackAction("restart")),
    vscode.commands.registerCommand("aetherstack.installRuntime", async () => {
      try {
        stackRoot = await installManagedRuntime(context);
        await refreshRuntime(true, true);
        await controlCenter.render(`AetherStack Runtime ${extensionManifest.version} is ready at ${stackRoot}.`);
      } catch (error) {
        const detail = error.message || String(error);
        output.appendLine(`[runtime-install] ${detail}`);
        output.show(true);
        vscode.window.showErrorMessage(`AetherStack Runtime installation failed: ${detail}`);
      }
    }),
    vscode.commands.registerCommand("aetherstack.refreshHostClis", () => reconcileCliProviders(true)),
    vscode.commands.registerCommand("aetherstack.refreshServices", async () => {
      modelVerificationCache = null;
      try {
        await reconcileCliProviders(false);
      } catch {
        // The normal service refresh below still reports the actionable state.
      }
      const runtime = await refreshRuntime(true, true);
      const failures = runtime.services
        .filter((service) => !service.ok)
        .map((service) => `${service.url} — ${service.error}`);
      const notice = failures.length ? `Service errors: ${failures.join("; ")}` : "AetherStack is up. All service endpoints are OK.";
      await controlCenter.render(notice);
      if (failures.length) vscode.window.showErrorMessage(`AetherStack: ${notice}`);
    }),
    vscode.commands.registerCommand("aetherstack.chooseStackPath", async () => {
      const chosen = await chooseStackRoot(context);
      if (chosen) stackRoot = chosen;
      await refreshRuntime(true);
    }),
    vscode.commands.registerCommand("aetherstack.openUrl", (url) => {
      if (typeof url === "string" && /^https?:\/\/127\.0\.0\.1(?::\d+)?\//.test(url)) {
        return vscode.env.openExternal(vscode.Uri.parse(url));
      }
      return undefined;
    }),
    vscode.commands.registerCommand("aetherstack.showLogs", async () => {
      stackRoot = await resolveStackRoot(context, true);
      if (!stackRoot) return;
      try {
        const result = await composeLogs(stackRoot, 100);
        output.appendLine(`\n[${new Date().toISOString()}] Last 100 Compose log lines`);
        output.append(result.stdout);
        output.append(result.stderr);
        output.show(true);
      } catch (error) {
        vscode.window.showErrorMessage(`Cannot read AetherStack logs: ${error.message}`);
      }
    })
  );

  const monitor = setInterval(async () => {
    try {
      await refreshRuntime(false);
      await controlCenter.render();
    } catch (error) {
      output.appendLine(`[monitor] ${error.message}`);
    }
  }, 10000);
  context.subscriptions.push(new vscode.Disposable(() => clearInterval(monitor)));
  await refreshRuntime(false, true);
  // Views and commands are now registered. Slow CLI login probes must not make
  // AetherStack appear missing during extension activation.
  void reconcileCliProviders(false).catch(() => {});

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.scanProject", async () => {
      const root = workspaceRoot();
      if (!root) {
        vscode.window.showErrorMessage("Open a folder/workspace first.");
        return;
      }
      const overview = buildOverview(root);
      const { mdPath } = writeOverviewFiles(root, overview);
      provider.refresh(overview);
      vscode.window.showInformationMessage(
        `AetherStack: found ${overview.sources.length} AI source(s). Overview → .aetherstack/project-overview.md`
      );
      const doc = await vscode.workspace.openTextDocument(mdPath);
      await vscode.window.showTextDocument(doc, { preview: true });
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.showOverview", async () => {
      const root = workspaceRoot();
      if (!root) return;
      const md = path.join(root, ".aetherstack", "project-overview.md");
      if (!fs.existsSync(md)) {
        await vscode.commands.executeCommand("aetherstack.scanProject");
        return;
      }
      const doc = await vscode.workspace.openTextDocument(md);
      await vscode.window.showTextDocument(doc, { preview: true });
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.configureContinue", async () => {
      const root = workspaceRoot();
      if (!root) {
        vscode.window.showErrorMessage("Open a folder first.");
        return;
      }
      const localStack = await resolveStackRoot(context, true);
      if (!localStack) return;
      const dir = path.join(root, ".continue");
      const confPath = path.join(dir, "config.yaml");
      if (fs.existsSync(confPath)) {
        const choice = await vscode.window.showWarningMessage(
          "Continue config already exists. Replace it with currently available AetherStack models? A backup will be kept.",
          { modal: true },
          "Replace"
        );
        if (choice !== "Replace") return;
      }
      try {
        syncContinueGatewayKey(localStack);
        const result = await writeAvailableContinueConfig({
          provider,
          replaceExisting: true,
          openDocument: true,
        });
        vscode.window.showInformationMessage(
          `Wired ${result.models.length} available capability-matrix model(s) to Continue.dev.`
        );
      } catch (error) {
        vscode.window.showErrorMessage(`Cannot wire Continue models: ${error.message}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.configureWorkspace", async () => {
      const root = workspaceRoot();
      if (!root) return;
      const dir = path.join(root, ".vscode");
      fs.mkdirSync(dir, { recursive: true });
      const c = cfg();
      const uri = vscode.Uri.file(root);
      const aetherCfg = vscode.workspace.getConfiguration("aetherstack", uri);
      await aetherCfg.update("baseUrl", c.baseUrl, vscode.ConfigurationTarget.Workspace);
      await aetherCfg.update("chatUiUrl", c.chatUiUrl, vscode.ConfigurationTarget.Workspace);
      await aetherCfg.update("defaultModel", c.defaultModel, vscode.ConfigurationTarget.Workspace);
      await vscode.workspace
        .getConfiguration("openai", uri)
        .update("baseUrl", c.baseUrl, vscode.ConfigurationTarget.Workspace);

      const recPath = path.join(dir, "extensions.json");
      let rec = { recommendations: [] };
      if (fs.existsSync(recPath)) {
        try {
          rec = JSON.parse(fs.readFileSync(recPath, "utf8"));
        } catch {
          vscode.window.showWarningMessage(
            "Preserved .vscode/extensions.json because it contains JSONC or invalid JSON; add Continue.continue manually."
          );
          rec = null;
        }
      }
      const want = ["Continue.continue", "AetherStack.aetherstack"];
      if (rec) {
        rec.recommendations = rec.recommendations || [];
        for (const id of want) {
          if (!rec.recommendations.includes(id)) rec.recommendations.push(id);
        }
        fs.writeFileSync(recPath, JSON.stringify(rec, null, 2), "utf8");
      }

      vscode.window.showInformationMessage(
        "Updated .vscode settings without writing an API key."
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.setApiKey", async () => {
      const value = await vscode.window.showInputBox({
        prompt: "AetherStack LiteLLM API key",
        password: true,
        ignoreFocusOut: true,
      });
      if (value === undefined) return;
      if (value.trim()) await context.secrets.store("aetherstack.apiKey", value.trim());
      else await context.secrets.delete("aetherstack.apiKey");
      vscode.window.showInformationMessage(
        value.trim() ? "AetherStack API key stored in VS Code SecretStorage." : "AetherStack API key cleared."
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.openChatUI", async () => {
      const url = normalizeLocalUiUrl(cfg().chatUiUrl);
      const webui = (await checkServices()).services.find((service) => service.id === "webui");
      if (!webui || !webui.ok) {
        vscode.window.showErrorMessage(
          `Open WebUI is not ready: ${(webui && webui.error) || "not running"}. Start all services and retry.`
        );
        return;
      }
      await vscode.env.openExternal(vscode.Uri.parse(url));
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.openModels", async () => {
      try {
        const res = await fetchModels();
        if (res.status === 401) {
          vscode.window.showErrorMessage(
            "LiteLLM 401: set aetherstack.apiKey (default sk-aether-local) and ensure stack is running."
          );
          return;
        }
        const ids = (res.body && res.body.data ? res.body.data : []).map((m) => m.id);
        if (!ids.length) {
          vscode.window.showWarningMessage("No models returned. Is AetherStack running on :4000?");
          return;
        }
        const pick = await vscode.window.showQuickPick(ids, {
          placeHolder: "AetherStack models (from LiteLLM)",
        });
        if (pick) {
          await vscode.workspace
            .getConfiguration("aetherstack")
            .update("defaultModel", pick, vscode.ConfigurationTarget.Workspace);
          vscode.window.showInformationMessage(`Default model set to ${pick}`);
        }
      } catch (e) {
        vscode.window.showErrorMessage(
          `Cannot reach AetherStack gateway: ${e.message}. Start the stack first (start.bat on Windows, ./start.sh on macOS/Linux).`
        );
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.openProjectEngine", async () => {
      const root = workspaceRoot();
      let url = "http://127.0.0.1:8765/";
      if (root) url += `?project=${encodeURIComponent(root)}`;
      vscode.env.openExternal(vscode.Uri.parse(url));
      vscode.window.showInformationMessage(
        "Opened Project Engine. If offline, run: project-engine/start-engine.ps1 (or start-engine.sh)"
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.saveSnapshot", async () => {
      const root = workspaceRoot();
      if (!root) return;
      const note = await vscode.window.showInputBox({
        prompt: "Short note about this session / what you were building",
        placeHolder: "e.g. Fixed auth on LiteLLM; next: wire Cline",
      });
      if (note === undefined) return;
      const model = cfg().defaultModel;
      const dir = path.join(root, ".aetherstack", "snapshots");
      fs.mkdirSync(dir, { recursive: true });
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const file = path.join(dir, `${stamp}.md`);
      fs.writeFileSync(
        file,
        `# Snapshot ${stamp}\n\n- Model focus: \`${model}\`\n- Note: ${note}\n- Gateway: \`${cfg().baseUrl}\`\n`,
        "utf8"
      );
      const overview = buildOverview(root);
      writeOverviewFiles(root, overview);
      provider.refresh(overview);
      vscode.window.showInformationMessage(`Saved ${path.relative(root, file)}`);
    })
  );
}

function deactivate() {}

module.exports = { activate, buildOverview, deactivate, writeOverviewFiles };
