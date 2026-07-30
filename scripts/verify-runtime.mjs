#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { basename, dirname, extname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..");
const version = readFileSync(join(repoRoot, "VERSION"), "utf8").trim();
const artifact = resolve(process.argv[2] ?? join(repoRoot, "dist", `aetherstack-runtime-${version}.tar.gz`));
const checksumPath = `${artifact}.sha256`;
const require = createRequire(import.meta.url);
const requiredNotice = "Required Notice: Copyright (c) 2026 piksliviksi. AetherStack was originally authored by piksliviksi.";

function fail(message) {
  throw new Error(`runtime verification failed: ${message}`);
}

if (!existsSync(artifact)) fail(`artifact does not exist: ${artifact}`);
if (!existsSync(checksumPath)) fail(`checksum does not exist: ${checksumPath}`);
const expectedChecksum = readFileSync(checksumPath, "utf8").trim().match(/^([a-f0-9]{64})\s+\*?([^\r\n]+)$/i);
if (!expectedChecksum || basename(expectedChecksum[2].trim()) !== basename(artifact)) {
  fail("checksum manifest does not identify the runtime artifact");
}
const actualChecksum = createHash("sha256").update(readFileSync(artifact)).digest("hex");
if (actualChecksum !== expectedChecksum[1].toLowerCase()) fail("SHA-256 checksum mismatch");

const listed = spawnSync("tar", ["-tzf", artifact], { encoding: "utf8" });
if (listed.error || listed.status !== 0) fail(listed.error?.message ?? listed.stderr.trim());
const entries = listed.stdout.split(/\r?\n/).filter(Boolean);
if (!entries.length) fail("archive is empty");
for (const entry of entries) {
  const normalized = entry.replaceAll("\\", "/");
  if (normalized.startsWith("/") || /^[A-Za-z]:/.test(normalized) || normalized.split("/").includes("..")) {
    fail(`unsafe archive path: ${entry}`);
  }
  if (normalized !== ".env.example" && /(?:^|\/)\.env(?:\.|$)/.test(normalized)) fail(`private environment file included: ${entry}`);
  if (/(?:^|\/)\.(?:git|claude|aetherstack)(?:\/|$)/.test(normalized)) fail(`private runtime state included: ${entry}`);
}
for (const required of ["LICENSE", "VERSION", "docker-compose.yml", "aether-hub/server.py", "aether-hub/inference_runtime.py"]) {
  if (!entries.includes(required)) fail(`required entry is missing: ${required}`);
}
const detailed = spawnSync("tar", ["-tvzf", artifact], { encoding: "utf8" });
if (detailed.error || detailed.status !== 0) fail(detailed.error?.message ?? detailed.stderr.trim());
for (const executable of ["start.sh", "stop.sh", "scripts/scan-system.sh"]) {
  const line = detailed.stdout.split(/\r?\n/).find((candidate) => candidate.trimEnd().endsWith(` ${executable}`));
  if (!line || !/^-rwxr-xr-x\b/.test(line)) fail(`runtime entry is not executable: ${executable}`);
}

const destination = mkdtempSync(join(tmpdir(), "aetherstack-runtime-verify-"));
try {
  const extracted = spawnSync("tar", ["-xzf", artifact, "-C", destination], { encoding: "utf8" });
  if (extracted.error || extracted.status !== 0) fail(extracted.error?.message ?? extracted.stderr.trim());
  const textExtensions = new Set([".html", ".js", ".json", ".md", ".ps1", ".py", ".sh", ".txt", ".yaml", ".yml"]);
  const privatePatterns = [
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
    /\bgh[pousr]_[A-Za-z0-9]{20,}\b/,
    /\b[A-Za-z]:\\Users\\[^\\\s]+\\/,
    /\bD:\\llm\\stack\b/i,
  ];
  for (const entry of entries) {
    const source = readFileSync(join(repoRoot, entry));
    const packaged = readFileSync(join(destination, entry));
    if (!source.equals(packaged)) fail(`packaged bytes differ from source: ${entry}`);
    if (textExtensions.has(extname(entry).toLowerCase())) {
      const text = packaged.toString("utf8");
      if (privatePatterns.some((pattern) => pattern.test(text))) {
        fail(`credential or machine-specific path pattern found in ${entry}`);
      }
    }
  }
  if (readFileSync(join(destination, "VERSION"), "utf8").trim() !== version) {
    fail("embedded VERSION does not match the release version");
  }
  const packagedLicense = readFileSync(join(destination, "LICENSE"), "utf8");
  if (!packagedLicense.startsWith("# PolyForm Noncommercial License 1.0.0\n") || !packagedLicense.includes(requiredNotice)) {
    fail("runtime license is missing the PolyForm Noncommercial terms or required original-author notice");
  }
} finally {
  rmSync(destination, { recursive: true, force: true });
}

// Exercise the same checksum/path-validation/promotion code shipped in the
// VSIX against this exact runtime artifact, not a synthetic fixture.
const installerStorage = mkdtempSync(join(tmpdir(), "aetherstack-runtime-install-"));
try {
  const { installRuntime } = require(join(repoRoot, "integrations", "vscode", "runtime-install.js"));
  const installed = await installRuntime({
    version,
    storagePath: installerStorage,
    downloader: async (url, target) => copyFileSync(url.endsWith(".sha256") ? checksumPath : artifact, target),
  });
  if (installed.reused || readFileSync(join(installed.root, "VERSION"), "utf8").trim() !== version) {
    fail("extension installer did not promote the exact runtime artifact");
  }
  const reused = await installRuntime({
    version,
    storagePath: installerStorage,
    downloader: async () => fail("installer downloaded an already verified runtime twice"),
  });
  if (!reused.reused || reused.root !== installed.root) fail("installed runtime was not reusable");
} finally {
  rmSync(installerStorage, { recursive: true, force: true });
}

console.log(`runtime artifact OK: ${basename(artifact)}`);
console.log(`identity: AetherStack runtime ${version}`);
console.log(`contents: ${entries.length} tracked files; source-byte, license, and privacy checks passed`);
console.log("installability: exact archive checksum-verified, promoted, and reused through the shipped installer");
