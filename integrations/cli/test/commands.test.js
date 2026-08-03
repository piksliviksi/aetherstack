const assert = require("node:assert/strict");
const test = require("node:test");
const os = require("node:os");
const path = require("node:path");

const commands = require("../lib/commands");

function mockClient(overrides = {}) {
  return {
    listServices: async () => [{ id: "coding", label: "Coding" }],
    getServiceGraph: async (id) => ({ id, title: id, nodes: [{ id: "g", type: "goal", data: {} }], edges: [] }),
    saveServiceGraph: async (id, graph) => ({ ok: true, id, graph }),
    saveGraph: async (graph) => ({ ok: true, id: "new-graph", graph }),
    runServiceStream: async (id, event, onEvent) => {
      onEvent({ type: "status", phase: "planning", run_id: event.run_id });
      onEvent({ type: "delta", text: "partial " });
      onEvent({ type: "done", result: { answer: "the answer", model: "claude-cli" } });
    },
    runGraphStream: async (graph, event, onEvent) => {
      onEvent({ type: "done", result: { answer: "graph answer" } });
    },
    cancelRun: async (runId) => ({ ok: true, run_id: runId, found: true }),
    fromPresetScript: async (text) => ({ id: "imported", nodes: [{ id: "g", type: "goal", data: {} }], edges: [] }),
    toPresetScript: async (graph) => `title: ${graph.title || graph.id}\n`,
    getGdprSettings: async () => ({
      enabled: false,
      retention_days: 30,
      require_cloud_consent: true,
      subprocessors: { cloud_providers: [{ provider: "OpenAI", models: "gpt-*", purpose: "Cloud inference" }], local_note: "local only" },
    }),
    setGdprSettings: async (patch) => ({ enabled: false, retention_days: 30, require_cloud_consent: true, ...patch }),
    gdprConsent: async (sessionId) => ({ session_id: sessionId, consented: true }),
    gdprRevokeConsent: async (sessionId) => ({ session_id: sessionId, consented: false }),
    gdprExport: async (sessionId) => ({ session_id: sessionId, session: { messages: [] } }),
    gdprErase: async (sessionId) => ({ session_id: sessionId, removed: { session: true } }),
    ...overrides,
  };
}

test("listPresets returns whatever the hub reports", async () => {
  const presets = await commands.listPresets(mockClient());
  assert.deepEqual(presets, [{ id: "coding", label: "Coding" }]);
});

test("showTree renders the fetched graph as text", async () => {
  const { text, graph } = await commands.showTree(mockClient(), "coding");
  assert.match(text, /\[goal\]/);
  assert.equal(graph.id, "coding");
});

test("showTree surfaces a hub-reported error instead of rendering garbage", async () => {
  const client = mockClient({ getServiceGraph: async () => ({ error: "unknown service: nope" }) });
  await assert.rejects(commands.showTree(client, "nope"), /unknown service/);
});

test("runPreset streams events and resolves with the final result", async () => {
  const events = [];
  const result = await commands.runPreset(mockClient(), "coding", "do it", { onEvent: (e) => events.push(e.type) });
  assert.deepEqual(events, ["status", "delta", "done"]);
  assert.equal(result.ok, true);
  assert.equal(result.result.answer, "the answer");
});

test("runPreset reports a cancelled run distinctly from a normal result", async () => {
  const client = mockClient({
    runServiceStream: async (id, event, onEvent) => onEvent({ type: "cancelled", run_id: event.run_id }),
  });
  const result = await commands.runPreset(client, "coding", "do it");
  assert.equal(result.cancelled, true);
  assert.equal(result.ok, false);
});

test("runPreset raises on a server-reported error event", async () => {
  const client = mockClient({
    runServiceStream: async (id, event, onEvent) => onEvent({ type: "error", error: "no model available" }),
  });
  await assert.rejects(commands.runPreset(client, "coding", "do it"), /no model available/);
});

test("runGraph runs an unsaved graph the same way runPreset runs a saved one", async () => {
  const result = await commands.runGraph(mockClient(), { nodes: [], edges: [] }, "do it");
  assert.equal(result.result.answer, "graph answer");
});

test("cancelRun forwards to the client", async () => {
  const result = await commands.cancelRun(mockClient(), "run-1");
  assert.equal(result.found, true);
});

test("exportPreset writes the hub's YAML text to disk", async () => {
  const file = path.join(os.tmpdir(), `aetherstack-cli-test-${Date.now()}.yaml`);
  const text = await commands.exportPreset(mockClient(), "coding", file);
  const fs = require("node:fs");
  try {
    assert.equal(fs.readFileSync(file, "utf8"), text);
    assert.match(text, /title: coding/);
  } finally {
    fs.unlinkSync(file);
  }
});

test("exportPreset returns the text without writing a file when no path is given", async () => {
  const text = await commands.exportPreset(mockClient(), "coding");
  assert.match(text, /title: coding/);
});

test("importPreset reads a file, converts it, and saves it as a new graph", async () => {
  const fs = require("node:fs");
  const file = path.join(os.tmpdir(), `aetherstack-cli-import-${Date.now()}.yaml`);
  fs.writeFileSync(file, "title: Imported\n", "utf8");
  try {
    const saved = await commands.importPreset(mockClient(), file);
    assert.equal(saved.id, "new-graph");
  } finally {
    fs.unlinkSync(file);
  }
});

test("buildOrEditPreset opens a blank template in the editor for a new preset and saves it", async () => {
  const written = {};
  const fakeFs = {
    writeFileSync: (file, content) => { written.file = file; written.content = content; },
    readFileSync: () => "title: Edited\n",
    unlinkSync: () => {},
  };
  const fakeSpawnSync = (editor, args) => {
    written.editor = editor;
    written.args = args;
    return { status: 0 };
  };
  const client = mockClient();
  const saved = await commands.buildOrEditPreset(client, { deps: { fs: fakeFs, spawnSync: fakeSpawnSync, editor: "nano" } });
  assert.equal(written.editor, "nano");
  assert.match(written.content, /title: New preset/);
  assert.equal(saved.id, "new-graph");
});

test("buildOrEditPreset with a presetId loads its current script and saves back to that preset", async () => {
  const fakeFs = { writeFileSync: () => {}, readFileSync: () => "title: coding (edited)\n", unlinkSync: () => {} };
  const fakeSpawnSync = () => ({ status: 0 });
  const client = mockClient();
  const saved = await commands.buildOrEditPreset(client, {
    presetId: "coding",
    deps: { fs: fakeFs, spawnSync: fakeSpawnSync, editor: "nano" },
  });
  assert.equal(saved.id, "coding");
});

test("buildOrEditPreset surfaces a non-zero editor exit instead of silently continuing", async () => {
  const fakeFs = { writeFileSync: () => {}, readFileSync: () => "", unlinkSync: () => {} };
  const fakeSpawnSync = () => ({ status: 1 });
  await assert.rejects(
    commands.buildOrEditPreset(mockClient(), { deps: { fs: fakeFs, spawnSync: fakeSpawnSync, editor: "nano" } }),
    /editor exited with status 1/
  );
});

test("buildOrEditPreset cleans up its temp file even when the import fails", async () => {
  let unlinked = false;
  const fakeFs = {
    writeFileSync: () => {},
    readFileSync: () => "not: [valid",
    unlinkSync: () => { unlinked = true; },
  };
  const fakeSpawnSync = () => ({ status: 0 });
  const client = mockClient({ fromPresetScript: async () => ({ error: "invalid preset script YAML" }) });
  await assert.rejects(
    commands.buildOrEditPreset(client, { deps: { fs: fakeFs, spawnSync: fakeSpawnSync, editor: "nano" } })
  );
  assert.equal(unlinked, true);
});

function mockStack(overrides = {}) {
  return {
    resolveStackRoot: (cwd) => cwd || "/fake/root",
    startCompose: async () => ({ code: 0 }),
    stopCompose: async () => ({ code: 0 }),
    checkDocker: async () => ({ installed: true, running: true }),
    checkServices: async () => ({ services: [{ id: "hub", ok: true }] }),
    ...overrides,
  };
}

test("startStack resolves the stack root and starts compose there", async () => {
  const calls = [];
  const stack = mockStack({
    startCompose: async (root, opts) => { calls.push(root); opts.onOutput && opts.onOutput("booting"); },
  });
  const chunks = [];
  const root = await commands.startStack("/my/checkout", { onOutput: (c) => chunks.push(c), stack });
  assert.equal(root, "/my/checkout");
  assert.deepEqual(calls, ["/my/checkout"]);
  assert.deepEqual(chunks, ["booting"]);
});

test("stopStack resolves the stack root and stops compose there", async () => {
  const calls = [];
  const stack = mockStack({ stopCompose: async (root) => calls.push(root) });
  await commands.stopStack("/my/checkout", { stack });
  assert.deepEqual(calls, ["/my/checkout"]);
});

test("stackStatus reports docker and service health together", async () => {
  const stack = mockStack();
  const status = await commands.stackStatus("/my/checkout", { stack });
  assert.equal(status.root, "/my/checkout");
  assert.equal(status.docker.running, true);
  assert.deepEqual(status.services, [{ id: "hub", ok: true }]);
});

test("startStack propagates a clear error when no checkout is found", async () => {
  const stack = mockStack({
    resolveStackRoot: () => { throw new Error("Could not find an AetherStack checkout"); },
  });
  await assert.rejects(commands.startStack("/nowhere", { stack }), /Could not find an AetherStack checkout/);
});

test("gdprStatus returns the hub's settings and subprocessor list", async () => {
  const settings = await commands.gdprStatus(mockClient());
  assert.equal(settings.enabled, false);
  assert.equal(settings.subprocessors.cloud_providers[0].provider, "OpenAI");
});

test("gdprSetSettings forwards the patch to the hub", async () => {
  const calls = [];
  const client = mockClient({ setGdprSettings: async (patch) => { calls.push(patch); return { ...patch }; } });
  await commands.gdprSetSettings(client, { enabled: true });
  assert.deepEqual(calls, [{ enabled: true }]);
});

test("gdprConsent records consent by default and revokes when asked", async () => {
  const calls = [];
  const client = mockClient({
    gdprConsent: async (sid) => { calls.push(["consent", sid]); return { consented: true }; },
    gdprRevokeConsent: async (sid) => { calls.push(["revoke", sid]); return { consented: false }; },
  });
  await commands.gdprConsent(client, "s1");
  await commands.gdprConsent(client, "s1", { revoke: true });
  assert.deepEqual(calls, [["consent", "s1"], ["revoke", "s1"]]);
});

test("gdprExportData and gdprEraseData forward to the hub by session id", async () => {
  const client = mockClient();
  const exported = await commands.gdprExportData(client, "s1");
  assert.equal(exported.session_id, "s1");
  const erased = await commands.gdprEraseData(client, "s1");
  assert.equal(erased.removed.session, true);
});
