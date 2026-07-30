const assert = require("node:assert/strict");
const Module = require("module");
const fs = require("fs");
const path = require("path");
const test = require("node:test");

test("chat exposes compact actions, dynamic presets, and model activity state", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "..", "chat.html"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.resolve(__dirname, "..", "package.json"), "utf8"));
  assert.match(html, /Auto — analyze my request/);
  assert.match(html, /Active preset node graph/);
  assert.match(html, /activeModels/);
  assert.match(html, /activityWords/);
  assert.match(html, /openAdvanced/);
  assert.match(html, /Ask anything, or use \/research/);
  assert.match(html, /message.type === 'route'/);
  assert.match(html, /vscode\.getState/);
  assert.doesNotMatch(html, /history-rail|historyToggle|historyRail/);
  assert.doesNotMatch(html, /class="header-actions"|id="historyMenuButton"|id="historyMenu"/);
  assert.equal(
    (manifest.contributes.menus["view/title"] || []).some((item) => item.when === "view == aetherstack.chatView"),
    false,
    "AetherStack still contributes buttons to the Chat view title area",
  );
  assert.match(html, /id="actionMenu" hidden[\s\S]*id="menuFilter"[\s\S]*id="showActiveModel"[\s\S]*id="setApiKey"[\s\S]*id="openSettings"[\s\S]*id="presetMenuList"/);
  assert.match(html, /id="activeModels"[\s\S]*id="send"/);
  assert.match(html, /Answering:|Used:/);
  assert.match(html, /Rename conversation/);
  assert.match(html, /function applyMenuFilter/);
  assert.match(html, /ICON_PATHS/);
  assert.doesNotMatch(html, /rgba\(|#[0-9a-f]{3,8}/i);
  assert.match(html, /function renderIdleLogo/);
  assert.match(html, /requestAnimationFrame\(renderIdleLogo\)/);
  assert.match(html, /prefers-reduced-motion/);
  const inlineScripts = [...html.matchAll(/<script nonce="\{\{NONCE\}\}">([\s\S]*?)<\/script>/g)];
  assert.ok(inlineScripts.length >= 2);
  assert.doesNotThrow(() => new Function(inlineScripts.at(-1)[1]));
});

test("one-button startup delegates to the platform bootstrap scripts", () => {
  const control = fs.readFileSync(path.resolve(__dirname, "..", "stack-control.js"), "utf8");
  assert.match(control, /start\.ps1/);
  assert.match(control, /start\.sh/);
  assert.match(control, /AETHER_NO_BROWSER/);
  assert.match(control, /COMPOSE_PROGRESS: "plain"/);
  assert.match(control, /stop\.ps1/);
  assert.match(control, /stop\.sh/);
  assert.match(control, /\["--profile", "\*", "stop"\]/);
  assert.match(control, /powershell\.exe/);
  const compose = fs.readFileSync(path.resolve(__dirname, "..", "..", "..", "docker-compose.yml"), "utf8");
  assert.match(compose, /AETHER_OLLAMA_PORT:-11434/);
  assert.match(compose, /RAG_EMBEDDING_ENGINE=ollama/);
  assert.match(compose, /RAG_EMBEDDING_MODEL=nomic-embed-text/);
  assert.doesNotMatch(compose, /container_name:/);
  assert.match(fs.readFileSync(path.resolve(__dirname, "..", "..", "..", "start.ps1"), "utf8"), /Select-FallbackOllamaPort/);
  const unixStart = fs.readFileSync(path.resolve(__dirname, "..", "..", "..", "start.sh"), "utf8");
  assert.match(unixStart, /select_fallback_port/);
  assert.match(unixStart, /start_macos_host_ollama/);
  assert.match(unixStart, /Ollama-darwin\.zip/);
  assert.match(unixStart, /codesign --verify --deep --strict/);
  const unixStop = fs.readFileSync(path.resolve(__dirname, "..", "..", "..", "stop.sh"), "utf8");
  assert.match(unixStop, /managed-ollama\.pid/);
  const artifactTest = fs.readFileSync(path.resolve(__dirname, "e2e", "extension-host.js"), "utf8");
  assert.match(artifactTest, /AETHERSTACK_ONE_CLICK_OK/);
  assert.match(artifactTest, /AETHERSTACK_E2E_REQUIRE_ACCELERATOR/);
  assert.match(artifactTest, /size_vram/);
  const oneClickVerifier = fs.readFileSync(path.resolve(__dirname, "..", "..", "..", "scripts", "verify-one-click.mjs"), "utf8");
  assert.match(oneClickVerifier, /bin", "code\.cmd/);
  assert.match(oneClickVerifier, /extensionDevelopmentPath/);
  assert.match(oneClickVerifier, /--install-extension/);
  assert.match(oneClickVerifier, /empty-workspace/);
  assert.match(oneClickVerifier, /clean one-click test requires free loopback port/);
  assert.match(oneClickVerifier, /const cleanupRoot = evidence\?\.stackPath/);
  const extension = fs.readFileSync(path.resolve(__dirname, "..", "extension.js"), "utf8");
  assert.match(extension, /if \(!root && prompt\) root = await installManagedRuntime\(context\)/);
  assert.match(extension, /bundled-runtime/);
});

test("extension activates and registers lifecycle/control commands", async () => {
  const registered = new Map();
  let treeProvider = null;
  let chatViewProvider = null;
  let cliBridgeStarted = false;
  class Disposable {
    constructor(dispose = () => {}) {
      this.dispose = dispose;
    }
  }
  class EventEmitter {
    constructor() {
      this.event = () => new Disposable();
    }
    fire() {}
  }
  class TreeItem {
    constructor(label, collapsibleState) {
      this.label = label;
      this.collapsibleState = collapsibleState;
    }
  }

  const configuration = {
    get: () => undefined,
    inspect: () => ({}),
    update: async () => {},
  };
  const vscode = {
    ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
    Disposable,
    EventEmitter,
    ProgressLocation: { Notification: 1 },
    StatusBarAlignment: { Left: 1 },
    ThemeIcon: class ThemeIcon { constructor(id) { this.id = id; } },
    TreeItem,
    TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
    Uri: { file: (fsPath) => ({ fsPath }), parse: (value) => ({ value }) },
    ViewColumn: { One: 1 },
    commands: {
      registerCommand: (name, handler) => {
        registered.set(name, handler);
        return new Disposable();
      },
      executeCommand: async (name, ...args) => registered.get(name)?.(...args),
    },
    env: { openExternal: async () => {} },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: "D:\\workspace\\aetherstack" } }],
      getConfiguration: () => configuration,
      onDidChangeConfiguration: () => new Disposable(),
      openTextDocument: async () => ({}),
    },
    window: {
      createOutputChannel: () => ({ append: () => {}, appendLine: () => {}, show: () => {}, dispose: () => {} }),
      createStatusBarItem: () => ({ show: () => {}, dispose: () => {} }),
      registerTreeDataProvider: (_name, provider) => {
        treeProvider = provider;
        return new Disposable();
      },
      registerWebviewViewProvider: (name, provider) => {
        if (name === "aetherstack.chatView") chatViewProvider = provider;
        return new Disposable();
      },
      showErrorMessage: async () => undefined,
      showInformationMessage: async () => undefined,
      showWarningMessage: async () => undefined,
      withProgress: async (_options, task) => task({ report: () => {} }),
    },
  };
  const serviceStatus = {
    checkedAt: new Date().toISOString(),
    up: false,
    services: [
      { id: "webui", name: "Open WebUI", url: "http://127.0.0.1:3000/", healthUrl: "http://127.0.0.1:3000/", ok: false, error: "connection refused" },
      { id: "litellm", name: "LiteLLM", url: "http://127.0.0.1:4000/", healthUrl: "http://127.0.0.1:4000/health/liveliness", ok: false, error: "connection refused" },
      { id: "hub", name: "Aether Hub", url: "http://127.0.0.1:8766/", healthUrl: "http://127.0.0.1:8766/api/health", ok: false, error: "connection refused" },
    ],
  };
  const stackControl = {
    SERVICES: serviceStatus.services,
    checkServices: async () => serviceStatus,
    composeDetails: async () => [],
    composeLogs: async () => ({ stdout: "", stderr: "" }),
    findStackRoot: () => "D:\\workspace\\aetherstack",
    isStackRoot: () => true,
    request: async () => ({ status: 503, body: {} }),
    runCompose: async () => ({ stdout: "", stderr: "" }),
    restartCompose: async () => ({ stdout: "", stderr: "" }),
    selectAvailableModels: () => [],
    startCompose: async () => ({ stdout: "", stderr: "" }),
    stopCompose: async () => ({ stdout: "", stderr: "" }),
    waitForServices: async () => serviceStatus,
  };

  const originalLoad = Module._load;
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "vscode") return vscode;
    if (request === "./stack-control" && parent && parent.filename.endsWith("extension.js")) return stackControl;
    if (request === "./cli-bridge" && parent && parent.filename.endsWith("extension.js")) {
      return {
        createCliBridge: () => ({
          token: "test-token",
          port: 8767,
          start: async () => { cliBridgeStarted = true; return { port: 8767, reused: false }; },
          models: async () => ({ "codex-cli": {} }),
          stop: () => {},
        }),
      };
    }
    return originalLoad.call(this, request, parent, isMain);
  };

  const subscriptions = [];
  const context = {
    extensionPath: path.resolve(__dirname, ".."),
    globalState: { get: () => undefined, update: async () => {} },
    secrets: { get: async () => undefined, store: async () => {}, delete: async () => {} },
    subscriptions,
  };
  try {
    delete require.cache[require.resolve("../extension")];
    const extension = require("../extension");
    await extension.activate(context);
    for (const command of [
      "aetherstack.openChat",
      "aetherstack.openChatEditor",
      "aetherstack.openHub",
      "aetherstack.openControlCenter",
      "aetherstack.startAll",
      "aetherstack.stopAll",
      "aetherstack.restartAll",
      "aetherstack.refreshServices",
      "aetherstack.refreshHostClis",
      "aetherstack.installRuntime",
      "aetherstack.showLogs",
    ]) {
      assert.equal(registered.has(command), true, `${command} was not registered`);
    }
    assert.ok(treeProvider);
    assert.ok(chatViewProvider);
    assert.equal(typeof chatViewProvider.resolveWebviewView, "function");
    assert.equal(cliBridgeStarted, true);
    const roots = treeProvider.getChildren();
    assert.ok(roots.some((item) => String(item.label).includes("Open AetherStack Chat")));
    assert.ok(roots.some((item) => String(item.label).includes("AetherStack has service errors")));
    assert.ok(roots.some((item) => item.description === "ERROR: connection refused"));

    const temp = fs.mkdtempSync(path.join(require("os").tmpdir(), "aetherstack-overview-"));
    try {
      fs.mkdirSync(path.join(temp, ".claude"), { recursive: true });
      fs.writeFileSync(path.join(temp, ".claude", "session.md"), "# Local session\n");
      const overview = extension.buildOverview(temp);
      assert.equal(overview.workspace, ".");
      assert.equal(overview.sources[0].path, ".claude");
      assert.equal(overview.sources[0].recent[0].name, ".claude/session.md");
      assert.equal(JSON.stringify(overview).includes(temp), false, "overview leaked an absolute workspace path");
    } finally {
      fs.rmSync(temp, { recursive: true, force: true });
    }
  } finally {
    Module._load = originalLoad;
    for (const disposable of subscriptions.reverse()) disposable.dispose?.();
    delete require.cache[require.resolve("../extension")];
  }
});
