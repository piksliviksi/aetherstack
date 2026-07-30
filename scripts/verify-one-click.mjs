#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const version = readFileSync(path.join(repoRoot, "VERSION"), "utf8").trim();
const options = {
  vsix: path.join(repoRoot, "dist", `aetherstack-${version}.vsix`),
  chatOnly: false,
  restart: false,
  requireAccelerator: false,
  keep: false,
  evidence: "",
};

for (let index = 2; index < process.argv.length; index += 1) {
  const argument = process.argv[index];
  if (argument === "--vsix") options.vsix = path.resolve(process.argv[++index] || "");
  else if (argument === "--evidence") options.evidence = path.resolve(process.argv[++index] || "");
  else if (argument === "--chat-only") options.chatOnly = true;
  else if (argument === "--restart") options.restart = true;
  else if (argument === "--require-accelerator") options.requireAccelerator = true;
  else if (argument === "--keep") options.keep = true;
  else throw new Error(`unknown argument: ${argument}`);
}

if (!existsSync(options.vsix)) throw new Error(`VSIX not found: ${options.vsix}`);
if (options.requireAccelerator && (process.platform !== "darwin" || process.arch !== "arm64")) {
  throw new Error("--require-accelerator requires native Apple Silicon macOS");
}

function findCode() {
  if (process.env.AETHERSTACK_CODE_APP && process.env.AETHERSTACK_CODE_CLI_JS) {
    return {
      app: path.resolve(process.env.AETHERSTACK_CODE_APP),
      cliJs: path.resolve(process.env.AETHERSTACK_CODE_CLI_JS),
    };
  }
  const candidates = process.platform === "win32"
    ? [
        process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Programs", "Microsoft VS Code", "Code.exe"),
        process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Microsoft VS Code", "Code.exe"),
      ]
    : process.platform === "darwin"
      ? ["/Applications/Visual Studio Code.app/Contents/MacOS/Electron"]
      : ["/usr/share/code/code", "/usr/share/code-insiders/code-insiders", "/snap/code/current/usr/share/code/code"];
  const app = candidates.filter(Boolean).find(existsSync);
  if (!app) throw new Error("VS Code application binary was not found; set AETHERSTACK_CODE_APP and AETHERSTACK_CODE_CLI_JS");
  let cliJs;
  if (process.platform === "win32") {
    const installRoot = path.dirname(app);
    const launcher = path.join(installRoot, "bin", "code.cmd");
    if (existsSync(launcher)) {
      const match = /%~dp0\.\.\\([^\\"\s]+)\\resources\\app\\out\\cli\.js/i.exec(readFileSync(launcher, "utf8"));
      if (match) cliJs = path.join(installRoot, match[1], "resources", "app", "out", "cli.js");
    }
    cliJs ||= readdirSync(installRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => path.join(installRoot, entry.name, "resources", "app", "out", "cli.js"))
      .find(existsSync);
  } else {
    cliJs = process.platform === "darwin"
      ? path.resolve(path.dirname(app), "..", "Resources", "app", "out", "cli.js")
      : path.join(path.dirname(app), "resources", "app", "out", "cli.js");
  }
  if (!existsSync(cliJs)) throw new Error(`VS Code CLI module was not found: ${cliJs}`);
  return { app, cliJs };
}

function cleanElectronEnvironment(overrides = {}) {
  const env = { ...process.env, ...overrides };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_NO_ATTACH_CONSOLE;
  return env;
}

function runCodeCli(code, args, env) {
  const result = spawnSync(code.app, [code.cliJs, ...args], {
    env: { ...env, ELECTRON_RUN_AS_NODE: "1" },
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout: 10 * 60_000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`VS Code CLI failed: ${result.error?.message || result.stderr || result.stdout || `exit ${result.status}`}`);
  }
  if (result.stdout.trim()) process.stdout.write(result.stdout);
  if (result.stderr.trim()) process.stderr.write(result.stderr);
}

function waitForExit(child, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`VS Code Extension Host exceeded ${Math.round(timeoutMs / 60_000)} minutes`));
    }, timeoutMs);
    child.once("error", (error) => { clearTimeout(timer); reject(error); });
    child.once("close", (code, signal) => {
      clearTimeout(timer);
      if (code === 0) resolve();
      else reject(new Error(`VS Code Extension Host exited with ${code ?? signal}`));
    });
  });
}

function portAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.listen({ host: "127.0.0.1", port }, () => server.close(() => resolve(true)));
  });
}

const code = findCode();
const testRoot = mkdtempSync(path.join(os.tmpdir(), `aetherstack-one-click-${version}-`));
const userData = path.join(testRoot, "user-data");
const extensions = path.join(testRoot, "extensions");
const workspace = path.join(testRoot, "empty-workspace");
const resultPath = path.join(testRoot, "evidence.json");
mkdirSync(workspace, { recursive: true });
const composeProject = process.env.COMPOSE_PROJECT_NAME || `aetherstacke2e${Date.now()}`;
const baseEnv = cleanElectronEnvironment({
  COMPOSE_PROJECT_NAME: composeProject,
  AETHERSTACK_E2E_VERSION: version,
  AETHERSTACK_E2E_RESULT: resultPath,
  AETHERSTACK_E2E_CHAT_ONLY: options.chatOnly ? "1" : "0",
  AETHERSTACK_E2E_RESTART: options.restart ? "1" : "0",
  AETHERSTACK_E2E_REQUIRE_ACCELERATOR: options.requireAccelerator ? "1" : "0",
  AETHERSTACK_E2E_STOP: options.chatOnly ? "0" : "1",
});

let evidence = null;
let extensionPath = null;
try {
  if (!options.chatOnly) {
    for (const port of [3000, 4000, 8766]) {
      if (!await portAvailable(port)) {
        throw new Error(`clean one-click test requires free loopback port ${port}; stop the existing service before retrying`);
      }
    }
  }
  console.log(`[one-click] installing exact VSIX ${options.vsix}`);
  runCodeCli(code, [
    "--user-data-dir", userData,
    "--extensions-dir", extensions,
    "--install-extension", options.vsix,
    "--force",
  ], baseEnv);
  extensionPath = readdirSync(extensions, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.toLowerCase().startsWith("aetherstack.aetherstack-"))
    .map((entry) => path.join(extensions, entry.name))
    .find((candidate) => {
      try { return JSON.parse(readFileSync(path.join(candidate, "package.json"), "utf8")).version === version; }
      catch { return false; }
    });
  if (!extensionPath) throw new Error(`installed AetherStack ${version} was not found in ${extensions}`);

  const applicationArgs = [
    "--new-window",
    "--skip-welcome",
    "--skip-release-notes",
    "--disable-workspace-trust",
    "--disable-extension=github.copilot",
    "--disable-extension=github.copilot-chat",
    "--user-data-dir", userData,
    "--extensions-dir", extensions,
    "--extensionDevelopmentPath", extensionPath,
    "--extensionTestsPath", path.join(repoRoot, "integrations", "vscode", "test", "e2e", "extension-host.js"),
    workspace,
  ];
  const executable = process.platform === "linux" && !process.env.DISPLAY && spawnSync("which", ["xvfb-run"], { encoding: "utf8" }).status === 0
    ? "xvfb-run"
    : code.app;
  const executableArgs = executable === "xvfb-run" ? ["-a", code.app, ...applicationArgs] : applicationArgs;
  console.log(`[one-click] launching isolated Extension Host (${process.platform}/${process.arch})`);
  const child = spawn(executable, executableArgs, { env: baseEnv, stdio: "inherit" });
  await waitForExit(child, 70 * 60_000);
  if (!existsSync(resultPath)) throw new Error("Extension Host exited without evidence.json");
  evidence = JSON.parse(readFileSync(resultPath, "utf8"));
  if (evidence.version !== version) throw new Error(`evidence version ${evidence.version} does not match ${version}`);
  const report = { ...evidence, composeProject };
  if (options.evidence) {
    mkdirSync(path.dirname(options.evidence), { recursive: true });
    writeFileSync(options.evidence, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
} finally {
  const managedRuntime = path.join(
    userData,
    "User",
    "globalStorage",
    "aetherstack.aetherstack",
    "runtime",
    version,
  );
  const cleanupRoot = evidence?.stackPath && existsSync(evidence.stackPath)
    ? evidence.stackPath
    : existsSync(managedRuntime)
      ? managedRuntime
      : null;
  if (!options.keep && !options.chatOnly && cleanupRoot) {
    const cleanup = spawnSync("docker", ["compose", "--profile", "*", "down", "--volumes", "--remove-orphans"], {
      cwd: cleanupRoot,
      env: baseEnv,
      encoding: "utf8",
      timeout: 10 * 60_000,
    });
    if (cleanup.status !== 0) process.stderr.write(`[one-click] cleanup warning: ${cleanup.stderr || cleanup.stdout}\n`);
  }
  if (!options.keep) rmSync(testRoot, { recursive: true, force: true });
  else console.log(`[one-click] preserved test state at ${testRoot}`);
}
