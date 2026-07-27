const assert = require("node:assert/strict");
const Module = require("module");
const path = require("path");
const test = require("node:test");

// Regression coverage for the history-desync bug fixed alongside this test:
// this.history was never reset/resynced on newConversation / switchConversation /
// deleteConversation, so stale context leaked across conversations and
// saveConversationSnapshot silently corrupted the wrong conversation's transcript.
test("HubChat resyncs history across new/switch/delete conversation actions", async () => {
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

  const configuration = { get: () => undefined, inspect: () => ({}), update: async () => {} };
  let chatViewProvider = null;
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
      registerCommand: (name, handler) => { registered.set(name, handler); return new Disposable(); },
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
      registerTreeDataProvider: () => new Disposable(),
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
  const registered = new Map();

  const stackControl = {
    SERVICES: [],
    checkServices: async () => ({ checkedAt: new Date().toISOString(), up: false, services: [] }),
    composeDetails: async () => [],
    composeLogs: async () => ({ stdout: "", stderr: "" }),
    findStackRoot: () => null,
    isStackRoot: () => false,
    // Only the hub "/run" endpoint is exercised by this test; everything else 503s.
    request: async (url, options) => {
      if (/\/run$/.test(url)) {
        const goal = (options && options.body && options.body.goal) || "";
        return { status: 200, body: { answer: `reply:${goal}` } };
      }
      return { status: 503, body: {} };
    },
    runCompose: async () => ({ stdout: "", stderr: "" }),
    restartCompose: async () => ({ stdout: "", stderr: "" }),
    selectAvailableModels: () => [],
    startCompose: async () => ({ stdout: "", stderr: "" }),
    stopCompose: async () => ({ stdout: "", stderr: "" }),
    waitForServices: async () => ({ up: false, services: [] }),
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
          start: async () => ({ port: 8767, reused: false }),
          models: async () => ({}),
          stop: () => {},
        }),
      };
    }
    return originalLoad.call(this, request, parent, isMain);
  };

  const subscriptions = [];
  const store = {};
  const context = {
    extensionPath: path.resolve(__dirname, ".."),
    globalState: {
      get: (key, def) => (key in store ? store[key] : def),
      update: async (key, val) => { store[key] = val; },
    },
    secrets: { get: async () => undefined, store: async () => {}, delete: async () => {} },
    subscriptions,
  };

  try {
    delete require.cache[require.resolve("../extension")];
    const extension = require("../extension");
    await extension.activate(context);
    assert.ok(chatViewProvider, "chat view provider was not registered");

    // Wire a minimal fake webview that captures the onDidReceiveMessage handler.
    let handler = null;
    const webview = {
      cspSource: "vscode-resource:",
      onDidReceiveMessage: (fn) => { handler = fn; return new Disposable(); },
      postMessage: async () => {},
    };
    chatViewProvider.resolveWebviewView({ webview, onDidDispose: () => {} });
    assert.equal(typeof handler, "function");

    // Bypass loadServices/network — give HubChat a fixed preset to route to directly.
    chatViewProvider.services = [{ id: "coding", label: "Coding", summary: "sum" }];

    const run = (prompt) => handler({ type: "run", prompt, serviceId: "coding" });

    // --- Conversation A: two turns ---
    await run("A message 1");
    await run("A message 2");
    const aId = chatViewProvider.activeConversationId;
    assert.ok(aId);
    let aEntry = chatViewProvider.conversations.find((item) => item.id === aId);
    assert.equal(aEntry.transcript.length, 4);
    assert.equal(chatViewProvider.history.length, 4);

    // --- Scenario 1: new conversation must not leak A's context ---
    await handler({ type: "newConversation" });
    assert.equal(chatViewProvider.activeConversationId, null);
    assert.deepEqual(chatViewProvider.history, []);
    await run("B message 1");
    const bId = chatViewProvider.activeConversationId;
    assert.notEqual(bId, aId);
    assert.equal(
      chatViewProvider.history.some((item) => String(item.content).includes("A message")),
      false,
      "history leaked conversation A's content into conversation B"
    );
    const bEntry = chatViewProvider.conversations.find((item) => item.id === bId);
    assert.equal(bEntry.transcript.length, 2);
    assert.match(bEntry.title, /B message 1/);
    assert.doesNotMatch(bEntry.title, /A message/);

    // --- Scenario 2: switching to A must not overwrite A's saved transcript ---
    await handler({ type: "switchConversation", id: aId });
    assert.equal(chatViewProvider.activeConversationId, aId);
    assert.equal(chatViewProvider.history.length, 4);
    await run("A message 3");
    aEntry = chatViewProvider.conversations.find((item) => item.id === aId);
    assert.equal(aEntry.transcript.length, 6, "switching back to A did not restore A's history before saving");
    const aValues = aEntry.transcript.map((item) => item.value);
    assert.ok(aValues.some((value) => String(value).includes("A message 1")));
    assert.ok(aValues.some((value) => String(value).includes("A message 2")));
    assert.ok(aValues.some((value) => String(value).includes("A message 3")));
    assert.equal(
      aValues.some((value) => String(value).includes("B message")),
      false,
      "conversation A's transcript was contaminated with conversation B's content"
    );

    // --- Scenario 3: deleting the active conversation must not let it silently revive ---
    await handler({ type: "deleteConversation", id: aId });
    assert.equal(chatViewProvider.activeConversationId, null);
    assert.deepEqual(chatViewProvider.history, []);
    assert.equal(chatViewProvider.conversations.some((item) => item.id === aId), false);
    await run("C message 1");
    assert.equal(
      chatViewProvider.conversations.some((item) => item.transcript.some((v) => String(v.value).includes("A message"))),
      false,
      "deleted conversation A's content reappeared after deletion"
    );
    const cEntry = chatViewProvider.conversations.find((item) => item.id === chatViewProvider.activeConversationId);
    assert.equal(cEntry.transcript.length, 2);
  } finally {
    Module._load = originalLoad;
    for (const disposable of subscriptions.reverse()) disposable.dispose?.();
    delete require.cache[require.resolve("../extension")];
  }
});
