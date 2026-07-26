const assert = require("node:assert/strict");
const Module = require("module");
const fs = require("fs");
const path = require("path");
const test = require("node:test");

test("chat exposes auto service selection, active graph, and model activity state", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "..", "chat.html"), "utf8");
  assert.match(html, /Auto — detect from current task/);
  assert.match(html, /Active preset node graph/);
  assert.match(html, /activeModels/);
  assert.match(html, /activityWords/);
  assert.match(html, /openAdvanced/);
});

test("extension activates and registers lifecycle/control commands", async () => {
  const registered = new Map();
  let treeProvider = null;
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
      workspaceFolders: [{ uri: { fsPath: "D:\\llm\\stack" } }],
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
      showErrorMessage: async () => undefined,
      showInformationMessage: async () => undefined,
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
    findStackRoot: () => "D:\\llm\\stack",
    isStackRoot: () => true,
    request: async () => ({ status: 503, body: {} }),
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
      "aetherstack.openHub",
      "aetherstack.openControlCenter",
      "aetherstack.startAll",
      "aetherstack.stopAll",
      "aetherstack.restartAll",
      "aetherstack.refreshServices",
      "aetherstack.showLogs",
    ]) {
      assert.equal(registered.has(command), true, `${command} was not registered`);
    }
    assert.ok(treeProvider);
    const roots = treeProvider.getChildren();
    assert.ok(roots.some((item) => String(item.label).includes("Open AetherStack Chat")));
    assert.ok(roots.some((item) => String(item.label).includes("AetherStack has service errors")));
    assert.ok(roots.some((item) => item.description === "ERROR: connection refused"));
  } finally {
    Module._load = originalLoad;
    for (const disposable of subscriptions.reverse()) disposable.dispose?.();
    delete require.cache[require.resolve("../extension")];
  }
});
