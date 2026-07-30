#!/usr/bin/env node

import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..");
const extensionDir = join(repoRoot, "integrations", "vscode");
const distDir = join(repoRoot, "dist");
const version = readFileSync(join(repoRoot, "VERSION"), "utf8").trim();
const output = join(distDir, `aetherstack-${version}.vsix`);
const runtimeName = `aetherstack-runtime-${version}.tar.gz`;
const runtimeArchive = join(distDir, runtimeName);
const runtimeChecksum = `${runtimeArchive}.sha256`;
const bundledRuntimeDir = join(extensionDir, "bundled-runtime");

const verify = spawnSync(process.execPath, [join(scriptDir, "verify-release.mjs")], {
  cwd: repoRoot,
  stdio: "inherit",
});
if (verify.status !== 0) {
  process.exit(verify.status ?? 1);
}

mkdirSync(distDir, { recursive: true });
rmSync(output, { force: true });

const runtime = spawnSync(process.execPath, [join(scriptDir, "package-runtime.mjs")], {
  cwd: repoRoot,
  stdio: "inherit",
});
if (runtime.error || runtime.status !== 0) {
  console.error(`Runtime packaging failed: ${runtime.error?.message ?? `exit ${runtime.status}`}`);
  process.exit(runtime.status ?? 1);
}
rmSync(bundledRuntimeDir, { recursive: true, force: true });
mkdirSync(bundledRuntimeDir, { recursive: true });
copyFileSync(runtimeArchive, join(bundledRuntimeDir, runtimeName));
copyFileSync(runtimeChecksum, join(bundledRuntimeDir, `${runtimeName}.sha256`));

const npmExecPath = process.env.npm_execpath;
const npxCli = npmExecPath ? join(dirname(npmExecPath), "npx-cli.js") : "";
const runner = npxCli && existsSync(npxCli)
  ? { command: process.execPath, prefix: [npxCli] }
  : { command: process.platform === "win32" ? "npx.cmd" : "npx", prefix: [] };
let packaged;
try {
  packaged = spawnSync(
    runner.command,
    [...runner.prefix, "--yes", "@vscode/vsce@3.9.2", "package", "--out", output],
    { cwd: extensionDir, stdio: "inherit", shell: process.platform === "win32" && !runner.prefix.length },
  );
} finally {
  rmSync(bundledRuntimeDir, { recursive: true, force: true });
}
if (packaged.error || packaged.status !== 0) {
  console.error(`VSIX packaging failed: ${packaged.error?.message ?? `exit ${packaged.status}`}`);
  process.exit(packaged.status ?? 1);
}

const size = statSync(output).size;
if (size < 1_000) {
  console.error(`VSIX packaging produced an implausibly small artifact (${size} bytes)`);
  process.exit(1);
}

console.log(`packaged ${output} (${size} bytes)`);
