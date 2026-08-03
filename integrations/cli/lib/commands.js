"use strict";

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const { renderTree } = require("./tree");

function genRunId() {
  return crypto.randomUUID ? crypto.randomUUID() : `run-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const BLANK_PRESET_SCRIPT = `title: New preset
goal: Describe the goal…
master:
  # model: claude-sonnet-4   # omit to auto-resolve from live capabilities
  prompt: Plan the work and delegate to workers.
workers:
  - label: Worker 1
    prompt: Do the work.
# parallel:
#   - label: Survey
#     branches: 3
#     prompt: Independently investigate the approach.
# audit:
#   prompt: Check the work for correctness and regressions.
# tester:
#   prompt: Run and verify the tests.
`;

async function listPresets(client) {
  return client.listServices();
}

async function showTree(client, presetId, opts) {
  const graph = await client.getServiceGraph(presetId);
  if (graph.error) throw new Error(graph.error);
  return { graph, text: renderTree(graph, opts) };
}

/** Runs a preset (or "auto") and streams status/delta events to onEvent as they arrive. */
async function runPreset(client, presetId, goal, { onEvent = () => {}, sessionId, runId } = {}) {
  const id = runId || genRunId();
  let result = null;
  let cancelled = false;
  let streamError = null;
  await client.runServiceStream(
    presetId,
    { goal, session_id: sessionId || `cli-${id}`, run_id: id },
    (event) => {
      if (event.type === "done") result = event.result;
      else if (event.type === "cancelled") cancelled = true;
      else if (event.type === "error") streamError = event.error || "run failed";
      onEvent(event);
    }
  );
  if (cancelled) return { ok: false, cancelled: true, runId: id };
  if (streamError) throw new Error(streamError);
  return { ok: true, result, runId: id };
}

/** Runs an arbitrary (not-yet-saved) graph — used for "run a script before saving it". */
async function runGraph(client, graph, goal, { onEvent = () => {}, sessionId, runId } = {}) {
  const id = runId || genRunId();
  let result = null;
  let cancelled = false;
  let streamError = null;
  await client.runGraphStream(
    graph,
    { goal, session_id: sessionId || `cli-${id}`, run_id: id },
    (event) => {
      if (event.type === "done") result = event.result;
      else if (event.type === "cancelled") cancelled = true;
      else if (event.type === "error") streamError = event.error || "run failed";
      onEvent(event);
    }
  );
  if (cancelled) return { ok: false, cancelled: true, runId: id };
  if (streamError) throw new Error(streamError);
  return { ok: true, result, runId: id };
}

async function cancelRun(client, runId) {
  return client.cancelRun(runId);
}

/** Writes a preset's YAML script to a file (or returns it, when no path given). */
async function exportPreset(client, presetId, filePath) {
  const graph = await client.getServiceGraph(presetId);
  if (graph.error) throw new Error(graph.error);
  const text = await client.toPresetScript(graph);
  if (filePath) fs.writeFileSync(filePath, text, "utf8");
  return text;
}

/** Imports a preset script from a file and saves it as a new custom graph. */
async function importPreset(client, filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  const graph = await client.fromPresetScript(text);
  if (graph.error) throw new Error(graph.error);
  const saved = await client.saveGraph(graph);
  if (saved.error) throw new Error(saved.error);
  return saved;
}

/**
 * Build or edit a preset by opening it as YAML in $EDITOR, then importing the
 * saved result. When presetId is given, edits that preset's current tree and
 * saves back to it; otherwise starts from a blank template and saves as a new
 * custom graph. `deps` is injectable for tests (fs/spawnSync/env/tmpdir).
 */
async function buildOrEditPreset(client, { presetId, deps = {} } = {}) {
  const _fs = deps.fs || fs;
  const _spawnSync = deps.spawnSync || spawnSync;
  const editor = deps.editor || process.env.VISUAL || process.env.EDITOR || "vi";
  const tmpDir = deps.tmpDir || os.tmpdir();

  let startText = BLANK_PRESET_SCRIPT;
  if (presetId) {
    const graph = await client.getServiceGraph(presetId);
    if (graph.error) throw new Error(graph.error);
    startText = await client.toPresetScript(graph);
  }

  const tmpFile = path.join(tmpDir, `aetherstack-preset-${genRunId()}.yaml`);
  _fs.writeFileSync(tmpFile, startText, "utf8");
  try {
    const proc = _spawnSync(editor, [tmpFile], { stdio: "inherit" });
    if (proc.error) throw proc.error;
    if (proc.status !== 0) throw new Error(`editor exited with status ${proc.status}`);
    const edited = _fs.readFileSync(tmpFile, "utf8");
    const graph = await client.fromPresetScript(edited);
    if (graph.error) throw new Error(graph.error);
    const saved = presetId ? await client.saveServiceGraph(presetId, graph) : await client.saveGraph(graph);
    if (saved.error) throw new Error(saved.error);
    return saved;
  } finally {
    try {
      _fs.unlinkSync(tmpFile);
    } catch {
      /* best-effort cleanup */
    }
  }
}

/**
 * Starts/stops the local AetherStack stack (Docker Compose) directly — no Hub
 * connection needed, since there's nothing to talk to until this succeeds.
 * `stack` is injectable for tests; defaults to lib/stack.js.
 */
async function startStack(cwd, { onOutput, stack = require("./stack") } = {}) {
  const root = stack.resolveStackRoot(cwd);
  await stack.startCompose(root, { onOutput });
  return root;
}

async function stopStack(cwd, { onOutput, stack = require("./stack") } = {}) {
  const root = stack.resolveStackRoot(cwd);
  await stack.stopCompose(root);
  return root;
}

async function stackStatus(cwd, { stack = require("./stack") } = {}) {
  const root = stack.resolveStackRoot(cwd);
  const [docker, serviceReport] = await Promise.all([stack.checkDocker(), stack.checkServices()]);
  return { root, docker, services: serviceReport.services || [] };
}

async function gdprStatus(client) {
  return client.getGdprSettings();
}

async function gdprSetSettings(client, patch) {
  return client.setGdprSettings(patch);
}

async function gdprConsent(client, sessionId, { revoke = false } = {}) {
  return revoke ? client.gdprRevokeConsent(sessionId) : client.gdprConsent(sessionId);
}

async function gdprExportData(client, sessionId) {
  return client.gdprExport(sessionId);
}

async function gdprEraseData(client, sessionId) {
  return client.gdprErase(sessionId);
}

module.exports = {
  BLANK_PRESET_SCRIPT,
  genRunId,
  listPresets,
  showTree,
  runPreset,
  runGraph,
  cancelRun,
  exportPreset,
  importPreset,
  buildOrEditPreset,
  startStack,
  stopStack,
  stackStatus,
  gdprStatus,
  gdprSetSettings,
  gdprConsent,
  gdprExportData,
  gdprEraseData,
};
