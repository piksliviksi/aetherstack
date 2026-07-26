import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const edgeCandidates = [
  process.env.PROGRAMFILES_X86 && path.join(process.env.PROGRAMFILES_X86, "Microsoft", "Edge", "Application", "msedge.exe"),
  process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Microsoft", "Edge", "Application", "msedge.exe"),
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);
const edge = edgeCandidates.find(fs.existsSync);
if (!edge) throw new Error("Microsoft Edge is required for this browser smoke test");

const port = await new Promise((resolve, reject) => {
  const server = net.createServer();
  server.once("error", reject);
  server.listen(0, "127.0.0.1", () => {
    const value = server.address().port;
    server.close(() => resolve(value));
  });
});
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-browser-smoke-"));
const browser = spawn(edge, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  "http://127.0.0.1:8766/",
], { stdio: "ignore", windowsHide: true });

const waitFor = async (fn, timeout = 15000) => {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    try { const value = await fn(); if (value) return value; } catch (error) { lastError = error; }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw lastError || new Error("browser smoke timeout");
};

try {
  const target = await waitFor(async () => {
    const values = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
    return values.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
  });
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let nextId = 1;
  const pending = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message)); else resolve(message.result);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "browser evaluation failed");
    return result.result.value;
  };
  const ready = () => waitFor(() => evaluate("document.readyState === 'complete'"));
  const navigate = async (url) => { await send("Page.navigate", { url }); await ready(); };
  await send("Runtime.enable");
  await send("Page.enable");
  await ready();
  await waitFor(() => evaluate("Boolean(document.getElementById('advancedGraph') && state.selected)"));
  await evaluate("localStorage.clear(); advancedPanel.open=true; advancedPanel.dispatchEvent(new Event('toggle')); true");
  assert.equal(await evaluate("localStorage.getItem(HUB_GRAPH_OPEN_KEY)"), "1");

  await navigate("http://127.0.0.1:8766/graph?service=research");
  await waitFor(() => evaluate("Boolean(graph.nodes && graph.nodes.length && liveChoices.models.length)"));
  const inspector = await evaluate(`(() => {
    const agent = graph.nodes.find(node => AGENT_NODE_TYPES.has(node.type));
    select(agent.id);
    return {
      models: document.querySelectorAll('[data-k="model"] option').length,
      agents: document.querySelectorAll('#inspectorAgent option').length,
      roles: document.querySelectorAll('[data-k="role"] option').length,
      markdown: Boolean(document.getElementById('agentMdFile') && document.querySelector('[data-k="instructions_md"]')),
    };
  })()`);
  assert.ok(inspector.models > 1, "model dropdown was not populated");
  assert.ok(inspector.agents > 1, "agent dropdown was not populated");
  assert.ok(inspector.roles > 0, "role dropdown was not populated");
  assert.equal(inspector.markdown, true, "agent Markdown controls are missing");

  const layout = await evaluate(`(() => {
    const node = graph.nodes[0];
    node.x += 111; saveGraphLayout();
    const expectedX = node.x;
    const wrap = canvasWrap; const rect = wrap.getBoundingClientRect();
    wrap.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:rect.left+20, clientY:rect.top+20}));
    window.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:rect.left+95, clientY:rect.top+60}));
    window.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:rect.left+95, clientY:rect.top+60}));
    return { expectedX, cameraX: camera.x, cameraY: camera.y };
  })()`);
  assert.notEqual(layout.cameraX, 0, "blank-canvas drag did not pan horizontally");
  assert.notEqual(layout.cameraY, 0, "blank-canvas drag did not pan vertically");

  await navigate("http://127.0.0.1:8766/");
  await waitFor(() => evaluate("Boolean(state.selected)"));
  assert.equal(await evaluate("document.getElementById('advancedGraph').open"), true, "Hub graph expansion was not restored");
  await navigate("http://127.0.0.1:8766/graph?service=research");
  await waitFor(() => evaluate("Boolean(graph.nodes && graph.nodes.length)"));
  assert.equal(await evaluate("graph.nodes[0].x"), layout.expectedX, "node position was not restored");
  assert.equal(await evaluate("camera.x"), layout.cameraX, "camera position was not restored");
  socket.close();
  console.log(JSON.stringify({ ok: true, inspector, layout }));
} finally {
  if (!browser.killed) browser.kill();
  await Promise.race([
    new Promise((resolve) => browser.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
  const resolvedProfile = path.resolve(profile);
  const resolvedTmp = path.resolve(os.tmpdir()) + path.sep;
  if (!resolvedProfile.startsWith(resolvedTmp) || !path.basename(resolvedProfile).startsWith("aetherstack-browser-smoke-")) {
    throw new Error(`refusing to remove unexpected browser profile: ${resolvedProfile}`);
  }
  fs.rmSync(resolvedProfile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
