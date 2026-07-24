/* AetherStack VS Code extension — scan project AI history + wire multi-LLM gateway */
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const { URL } = require("url");

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
    apiKey: c.get("apiKey") || "sk-aether-local",
    chatUiUrl: c.get("chatUiUrl") || "http://127.0.0.1:3000",
    defaultModel: c.get("defaultModel") || "local-default",
  };
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
            name: path.relative(root, f.path),
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
  const overview = {
    generatedAt: new Date().toISOString(),
    workspace: root,
    aetherstack: cfg(),
    sources,
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
  md.push(`Workspace: \`${overview.workspace}\``);
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
  md.push(`_This file is local project metadata for AetherStack. Safe to commit if you want team continuity._`);

  const mdPath = path.join(dir, "project-overview.md");
  fs.writeFileSync(mdPath, md.join("\n"), "utf8");
  return { jsonPath, mdPath };
}

function httpJson(urlStr, headers = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const lib = u.protocol === "https:" ? https : http;
    const req = lib.request(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname + u.search,
        method: "GET",
        headers,
        timeout: 5000,
      },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          try {
            resolve({ status: res.statusCode, body: JSON.parse(data) });
          } catch {
            resolve({ status: res.statusCode, body: data });
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
    req.end();
  });
}

async function fetchModels() {
  const { baseUrl, apiKey } = cfg();
  const url = baseUrl.replace(/\/$/, "") + "/models";
  return httpJson(url, { Authorization: `Bearer ${apiKey}` });
}

function continueConfigYaml(c) {
  // OpenAI-compatible → LiteLLM
  return `name: AetherStack
version: 1.0.0
schema: v1

models:
  - name: Aether local-default
    provider: openai
    model: local-default
    apiBase: ${c.baseUrl}
    apiKey: ${c.apiKey}
    roles: [chat, edit, apply]

  - name: Aether Grok 4.5
    provider: openai
    model: grok-4.5
    apiBase: ${c.baseUrl}
    apiKey: ${c.apiKey}
    roles: [chat, edit, apply]

  - name: Aether GPT-4.1
    provider: openai
    model: gpt-4.1
    apiBase: ${c.baseUrl}
    apiKey: ${c.apiKey}
    roles: [chat, edit, apply]

  - name: Aether Claude Sonnet 4
    provider: openai
    model: claude-sonnet-4
    apiBase: ${c.baseUrl}
    apiKey: ${c.apiKey}
    roles: [chat, edit, apply]

  - name: Aether Gemini 2.5 Pro
    provider: openai
    model: gemini-2.5-pro
    apiBase: ${c.baseUrl}
    apiKey: ${c.apiKey}
    roles: [chat, edit, apply]
`;
}

class OverviewProvider {
  constructor() {
    this._onDidChangeTreeData = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    this.overview = null;
  }
  refresh(overview) {
    this.overview = overview;
    this._onDidChangeTreeData.fire();
  }
  getTreeItem(el) {
    return el;
  }
  getChildren(el) {
    if (!this.overview) {
      const item = new vscode.TreeItem(
        "Run: AetherStack: Scan Project AI History",
        vscode.TreeItemCollapsibleState.None
      );
      item.command = { command: "aetherstack.scanProject", title: "Scan" };
      return [item];
    }
    if (!el) {
      const roots = [];
      const src = new vscode.TreeItem(
        `Sources (${this.overview.sources.length})`,
        vscode.TreeItemCollapsibleState.Expanded
      );
      src.contextValue = "sources";
      roots.push(src);
      const models = new vscode.TreeItem(
        `Models mentioned (${this.overview.modelsMentioned.length})`,
        vscode.TreeItemCollapsibleState.Collapsed
      );
      models.contextValue = "models";
      roots.push(models);
      const cont = new vscode.TreeItem("Continue with AetherStack", vscode.TreeItemCollapsibleState.Collapsed);
      cont.contextValue = "continue";
      roots.push(cont);
      return roots;
    }
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
    if (el.contextValue === "continue") {
      return [
        treeCmd("Wire Continue.dev", "aetherstack.configureContinue"),
        treeCmd("Open Chat UI", "aetherstack.openChatUI"),
        treeCmd("List gateway models", "aetherstack.openModels"),
        treeCmd("Write .vscode settings", "aetherstack.configureWorkspace"),
      ];
    }
    return [];
  }
}

function treeCmd(label, command) {
  const t = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
  t.command = { command, title: label };
  return t;
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  const provider = new OverviewProvider();
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("aetherstack.overview", provider)
  );

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
      const dir = path.join(root, ".continue");
      fs.mkdirSync(dir, { recursive: true });
      const confPath = path.join(dir, "config.yaml");
      fs.writeFileSync(confPath, continueConfigYaml(cfg()), "utf8");
      // Also refresh overview
      const overview = buildOverview(root);
      writeOverviewFiles(root, overview);
      provider.refresh(overview);
      vscode.window.showInformationMessage(
        "Wrote .continue/config.yaml → AetherStack LiteLLM. Install Continue extension if needed."
      );
      const doc = await vscode.workspace.openTextDocument(confPath);
      await vscode.window.showTextDocument(doc, { preview: true });
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.configureWorkspace", async () => {
      const root = workspaceRoot();
      if (!root) return;
      const dir = path.join(root, ".vscode");
      fs.mkdirSync(dir, { recursive: true });
      const settingsPath = path.join(dir, "settings.json");
      let settings = {};
      if (fs.existsSync(settingsPath)) {
        try {
          settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
        } catch {
          settings = {};
        }
      }
      const c = cfg();
      settings["aetherstack.baseUrl"] = c.baseUrl;
      settings["aetherstack.apiKey"] = c.apiKey;
      settings["aetherstack.chatUiUrl"] = c.chatUiUrl;
      settings["aetherstack.defaultModel"] = c.defaultModel;
      // Common OpenAI-compatible extension keys
      settings["openai.baseUrl"] = c.baseUrl;
      fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2), "utf8");

      const recPath = path.join(dir, "extensions.json");
      let rec = { recommendations: [] };
      if (fs.existsSync(recPath)) {
        try {
          rec = JSON.parse(fs.readFileSync(recPath, "utf8"));
        } catch {
          /* keep default */
        }
      }
      const want = ["Continue.continue", "piksliviksi.aetherstack"];
      rec.recommendations = rec.recommendations || [];
      for (const id of want) {
        if (!rec.recommendations.includes(id)) rec.recommendations.push(id);
      }
      fs.writeFileSync(recPath, JSON.stringify(rec, null, 2), "utf8");

      vscode.window.showInformationMessage("Wrote .vscode/settings.json + extensions.json for AetherStack.");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aetherstack.openChatUI", () => {
      vscode.env.openExternal(vscode.Uri.parse(cfg().chatUiUrl));
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
          `Cannot reach AetherStack gateway: ${e.message}. Run start.bat / ./start.sh first.`
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

module.exports = { activate, deactivate };
