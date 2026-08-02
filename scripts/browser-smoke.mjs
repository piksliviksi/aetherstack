import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const browserCandidates = [
  process.env.AETHER_BROWSER_BIN,
  process.platform === "darwin" && "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  process.platform === "darwin" && "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  process.env.PROGRAMFILES_X86 && path.join(process.env.PROGRAMFILES_X86, "Microsoft", "Edge", "Application", "msedge.exe"),
  process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Microsoft", "Edge", "Application", "msedge.exe"),
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);
const browserBinary = browserCandidates.find(fs.existsSync);
if (!browserBinary) throw new Error("Chrome or Microsoft Edge is required for this browser smoke test");

const port = await new Promise((resolve, reject) => {
  const server = net.createServer();
  server.once("error", reject);
  server.listen(0, "127.0.0.1", () => {
    const value = server.address().port;
    server.close(() => resolve(value));
  });
});
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-browser-smoke-"));
const browser = spawn(browserBinary, [
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

let primaryError = null;
try {
  const target = await waitFor(async () => {
    const values = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
    return values.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
  });
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let nextId = 1;
  const pending = new Map();
  let trackedMainFrame = null;
  let mainFrameNavigations = 0;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.method === "Page.frameNavigated" && message.params?.frame?.id === trackedMainFrame) {
      mainFrameNavigations += 1;
    }
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
  trackedMainFrame = (await send("Page.getFrameTree")).frameTree.frame.id;
  await ready();
  await waitFor(() => evaluate("Boolean(document.getElementById('advancedGraph') && state.selected)"));
  assert.equal(await evaluate("document.getElementById('runtime').textContent.includes('Host CLI bridge')"), true, "Host CLI bridge state is hidden");
  assert.equal(await evaluate("[...document.querySelectorAll('header nav a')].map(a=>a.textContent).join('|')"), "Simple|Advanced|WebUI", "Hub navigation order is wrong");
  assert.equal(await evaluate("document.querySelector('header nav a.active')?.textContent"), "Simple", "Simple mode is not highlighted");
  assert.equal(await evaluate("[...document.querySelectorAll('#statusbar .chip')].some(chip => chip.textContent.includes('cloud spend'))"), true, "Cost dashboard chip is missing from the status bar");

  // Follow the real "Advanced" link (not graph.html directly) — it serves a separate,
  // server-rendered page in server.py whose header used to drift from Simple's.
  const advancedHref = await evaluate("document.querySelector('header nav a:nth-child(2)').getAttribute('href')");
  await navigate(`http://127.0.0.1:8766${advancedHref}`);
  assert.equal(await evaluate("[...document.querySelectorAll('header nav a')].map(a=>a.textContent).join('|')"), "Simple|Advanced|WebUI", "Advanced page nav order/labels drifted from Simple");
  assert.equal(await evaluate("document.querySelector('header nav a.active')?.textContent"), "Advanced", "Advanced page is not highlighting itself");
  assert.equal(await evaluate("document.querySelector('header .brand h1')?.textContent"), "AetherStack", "Advanced page header no longer matches Simple's brand block");
  await navigate("http://127.0.0.1:8766/");
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
      deleteInLibrary: Boolean(document.querySelector('#palette #btnDel')),
      deleteInToolbar: Boolean(document.querySelector('#toolbar #btnDel')),
      deleteFits: (() => { const button=document.getElementById('btnDel').getBoundingClientRect(); const palette=document.getElementById('palette').getBoundingClientRect(); return button.top >= palette.top && button.bottom <= palette.bottom; })(),
      descriptions: [...document.querySelectorAll('#palette .ptype')].every(node => node.title.length > 20),
      friendlyLabels: document.getElementById('insp').textContent.includes('Node name') && document.getElementById('insp').textContent.includes('Resolved runtime'),
      rawMakerHidden: !document.getElementById('insp').textContent.includes('maker'),
      profileLoaded: document.querySelector('[data-k="instructions_md"]').value.length > 20,
    };
  })()`);
  assert.ok(inspector.models > 1, "model dropdown was not populated");
  assert.ok(inspector.agents > 1, "agent dropdown was not populated");
  assert.ok(inspector.roles > 0, "role dropdown was not populated");
  assert.equal(inspector.markdown, true, "agent Markdown controls are missing");
  assert.equal(inspector.deleteInLibrary, true, "delete button is not in the Node library");
  assert.equal(inspector.deleteInToolbar, false, "delete button is still in the toolbar");
  assert.equal(inspector.deleteFits, true, "delete button is clipped by the Node library viewport");
  assert.equal(inspector.descriptions, true, "Node library hover descriptions are missing");
  assert.equal(inspector.friendlyLabels, true, "Inspector does not use friendly controls");
  assert.equal(inspector.rawMakerHidden, true, "Inspector leaks a raw maker field");
  assert.equal(inspector.profileLoaded, true, "service behavior profile is not loaded into agent nodes");

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
  const liveMatrix = await fetch("http://127.0.0.1:8766/api/matrix").then((response) => response.json());
  const expectedWebuiAliases = Object.entries(liveMatrix.models || {})
    .filter(([, model]) => model.available && (model.capabilities || []).includes("chat"))
    .map(([alias]) => alias);
  assert.ok(expectedWebuiAliases.length, "capability matrix has no available chat aliases for WebUI verification");

  // The VS Code webview host provides the viewport; loading the same HTML as a
  // local document lets us verify its flex sizing without mocking VS Code APIs.
  const vscodeRoot = path.join(process.cwd(), "integrations", "vscode");
  const renderedChat = fs.readFileSync(path.join(vscodeRoot, "chat.html"), "utf8")
    .replaceAll("{{NONCE}}", "browser-smoke")
    .replaceAll("{{CSP_SOURCE}}", "file:")
    .replace("{{UI_TOKENS}}", fs.readFileSync(path.join(vscodeRoot, "ui-tokens.css"), "utf8"))
    .replace("{{CHAT_RENDER_JS}}", fs.readFileSync(path.join(vscodeRoot, "chat-render.js"), "utf8"));
  const renderedChatPath = path.join(profile, "aetherstack-chat.html");
  fs.writeFileSync(renderedChatPath, renderedChat);
  const chatUrl = pathToFileURL(renderedChatPath).href;
  const checkChatLayout = async (width, height) => {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 500 });
    await navigate(chatUrl);
    return evaluate(`(() => {
      const messages = document.getElementById('messages');
      messages.innerHTML = '<div class="message">' + 'UNBROKEN_TEXT_'.repeat(300) + '</div><div class="message"><pre>' + 'wide-code '.repeat(300) + '</pre></div>';
      const main = document.querySelector('main').getBoundingClientRect();
      const mainStyle = getComputedStyle(document.querySelector('main'));
      const composer = document.querySelector('.composer').getBoundingClientRect();
      const textarea = document.querySelector('textarea').getBoundingClientRect();
      const message = messages.firstElementChild.getBoundingClientRect();
      return {
        viewport: [innerWidth, innerHeight],
        mainBox: [main.top, main.bottom, main.height, mainStyle.paddingBottom],
        composerBox: [composer.top, composer.bottom, composer.height, getComputedStyle(document.querySelector('.composer')).marginBottom],
        bodyFits: document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight,
        transcriptFits: messages.getBoundingClientRect().right <= main.right + 1 && message.right <= messages.getBoundingClientRect().right + 1,
        composerGap: (main.bottom - parseFloat(mainStyle.paddingBottom)) - composer.bottom,
        composerAtBottom: Math.abs((main.bottom - parseFloat(mainStyle.paddingBottom)) - composer.bottom) <= 1,
        composerFits: composer.left >= main.left - 1 && composer.right <= main.right + 1,
        textareaFits: textarea.right <= composer.right + 1,
        transcriptScrolls: messages.scrollHeight > messages.clientHeight,
      };
    })()`);
  };
  const chatDesktop = await checkChatLayout(900, 650);
  const chatMobile = await checkChatLayout(340, 520);
  for (const [name, layout] of Object.entries({ chatDesktop, chatMobile })) {
    assert.equal(layout.bodyFits, true, `${name} overflows the webview`);
    assert.equal(layout.transcriptFits, true, `${name} clips chat text horizontally`);
    assert.equal(layout.composerAtBottom, true, `${name} composer is not attached to the bottom: ${JSON.stringify(layout)}`);
    assert.equal(layout.composerFits, true, `${name} composer exceeds the chat width`);
    assert.equal(layout.textareaFits, true, `${name} textarea exceeds the composer`);
    assert.equal(layout.transcriptScrolls, true, `${name} transcript is not the scrolling region`);
  }
  await send("Emulation.clearDeviceMetricsOverride");

  await navigate("http://127.0.0.1:3000/");
  mainFrameNavigations = 0;
  const webuiModels = await waitFor(() => evaluate(`(async () => {
    const token = localStorage.getItem('token');
    if (!token) return null;
    const response = await fetch('/api/models', {headers:{Authorization:'Bearer '+token}});
    if (!response.ok) return null;
    const body = await response.json();
    return (body.data || []).map(model => model.id);
  })()`), 60000);
  assert.ok(
    expectedWebuiAliases.some((alias) => webuiModels.includes(alias)),
    `Open WebUI did not load a live AetherStack gateway alias (expected one of: ${expectedWebuiAliases.join(", ")})`,
  );
  assert.equal(webuiModels.includes("tinyllama:latest"), false, "Open WebUI still exposes raw Ollama models");
  await new Promise((resolve) => setTimeout(resolve, 10000));
  assert.equal(mainFrameNavigations, 0, `Open WebUI reloaded ${mainFrameNavigations} time(s) after initial render`);
  const webuiStability = await evaluate(`(() => ({
    readyState: document.readyState,
    href: location.href,
    bodyChildren: document.body.children.length,
    fixedFullViewportLayers: [...document.querySelectorAll('body *')].filter((element) => {
      const style = getComputedStyle(element); if (style.position !== 'fixed' || style.display === 'none' || style.visibility === 'hidden') return false;
      const rect = element.getBoundingClientRect(); return rect.width >= innerWidth * .95 && rect.height >= innerHeight * .95;
    }).length,
  }))()`);
  assert.equal(webuiStability.readyState, "complete", "Open WebUI document did not remain complete");
  assert.equal(webuiStability.href, "http://127.0.0.1:3000/", "Open WebUI redirected away from its stable root route");
  assert.ok(webuiStability.bodyChildren > 0, "Open WebUI body was unexpectedly replaced with an empty document");
  assert.ok(webuiStability.fixedFullViewportLayers <= 3, `Open WebUI stacked ${webuiStability.fixedFullViewportLayers} full-viewport layers`);
  console.log(JSON.stringify({ ok: true, inspector, layout, chatDesktop, chatMobile, webuiModels, webuiStability }));
  await send("Browser.close").catch(() => {});
  socket.close();
} catch (error) {
  primaryError = error;
} finally {
  if (process.platform === "win32" && browser.pid) {
    spawnSync("taskkill", ["/PID", String(browser.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
  } else if (!browser.killed) {
    browser.kill();
  }
  await Promise.race([
    new Promise((resolve) => browser.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
  const resolvedProfile = path.resolve(profile);
  const resolvedTmp = path.resolve(os.tmpdir()) + path.sep;
  if (!resolvedProfile.startsWith(resolvedTmp) || !path.basename(resolvedProfile).startsWith("aetherstack-browser-smoke-")) {
    throw new Error(`refusing to remove unexpected browser profile: ${resolvedProfile}`);
  }
  try {
    fs.rmSync(resolvedProfile, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
  } catch (cleanupError) {
    if (primaryError) {
      primaryError.cleanupError = cleanupError;
    } else {
      console.warn(`browser smoke passed but temporary profile cleanup was deferred: ${cleanupError.message}`);
    }
  }
}

if (primaryError) throw primaryError;
