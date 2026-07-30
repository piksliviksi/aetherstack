#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..");
const expectedLicense = "PolyForm-Noncommercial-1.0.0";
const requiredNotice = "Required Notice: Copyright (c) 2026 piksliviksi. AetherStack was originally authored by piksliviksi.";

function fail(message) {
  console.error(`release verification failed: ${message}`);
  process.exitCode = 1;
}

function read(relativePath) {
  return readFileSync(join(repoRoot, relativePath), "utf8");
}

const version = read("VERSION").trim();
if (!/^\d+\.\d+\.\d+$/.test(version)) {
  fail(`VERSION must be a stable x.y.z value, got ${JSON.stringify(version)}`);
}

let extensionPackage;
try {
  extensionPackage = JSON.parse(read("integrations/vscode/package.json"));
} catch (error) {
  fail(`integrations/vscode/package.json is invalid JSON: ${error.message}`);
}

if (extensionPackage) {
  if (extensionPackage.version !== version) {
    fail(`extension version ${extensionPackage.version} does not match VERSION ${version}`);
  }
  if (extensionPackage.name !== "aetherstack" || extensionPackage.publisher !== "AetherStack") {
    fail("extension identity must remain AetherStack.aetherstack");
  }
  if (extensionPackage.license !== expectedLicense) {
    fail(`extension license must be ${expectedLicense}, got ${JSON.stringify(extensionPackage.license)}`);
  }

  const requiredScripts = ["test", "verify:release", "package:vsix", "verify:vsix", "package:runtime", "verify:runtime", "release:check"];
  for (const name of requiredScripts) {
    if (!extensionPackage.scripts?.[name]) {
      fail(`extension package is missing the ${name} script`);
    }
  }
}

const rootLicense = read("LICENSE");
const vscodeLicense = read("integrations/vscode/LICENSE");
if (rootLicense !== vscodeLicense) {
  fail("root and VS Code extension license files must be byte-identical");
}
if (!rootLicense.startsWith("# PolyForm Noncommercial License 1.0.0\n") || !rootLicense.includes(requiredNotice)) {
  fail("license must contain the canonical PolyForm Noncommercial title and required original-author notice");
}

const compose = read("docker-compose.yml");
const composeVersions = [
  ...compose.matchAll(/AETHERSTACK_VERSION=\$\{AETHERSTACK_VERSION:-([^}\s]+)\}/g),
].map((match) => match[1]);
if (composeVersions.length !== 1) {
  fail(`expected one Compose AETHERSTACK_VERSION default, found ${composeVersions.length}`);
} else if (composeVersions[0] !== version) {
  fail(`Compose version ${composeVersions[0]} does not match VERSION ${version}`);
}

const changelog = read("integrations/vscode/CHANGELOG.md");
const escapedVersion = version.replaceAll(".", "\\.");
const headings = changelog.match(new RegExp(`^## ${escapedVersion}(?:\\s|$)`, "gm")) ?? [];
if (headings.length !== 1) {
  fail(`expected one CHANGELOG heading for ${version}, found ${headings.length}`);
}

const trackedVsix = spawnSync("git", ["ls-files", "--", "*.vsix"], {
  cwd: repoRoot,
  encoding: "utf8",
});
if (trackedVsix.error || trackedVsix.status !== 0) {
  fail(`could not inspect tracked VSIX files: ${trackedVsix.error?.message ?? trackedVsix.stderr.trim()}`);
} else if (trackedVsix.stdout.trim()) {
  fail(`VSIX binaries must be Release assets, not tracked source files:\n${trackedVsix.stdout.trim()}`);
}

if (!process.exitCode) {
  console.log(`release identity OK: AetherStack.aetherstack ${version}`);
  console.log(`license policy OK: ${expectedLicense}; required original-author notice present`);
  console.log("repository artifact policy OK: no tracked VSIX binaries");
}
