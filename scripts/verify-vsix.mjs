#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { inflateRawSync } from "node:zlib";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..");
const expectedVersion = readFileSync(join(repoRoot, "VERSION"), "utf8").trim();
const expectedLicense = "PolyForm-Noncommercial-1.0.0";
const requiredNotice = "Required Notice: Copyright (c) 2026 piksliviksi. AetherStack was originally authored by piksliviksi.";
const artifact = resolve(process.argv[2] ?? join(repoRoot, "dist", `aetherstack-${expectedVersion}.vsix`));

function abort(message) {
  throw new Error(`VSIX verification failed: ${message}`);
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function parseZip(buffer) {
  const minimum = Math.max(0, buffer.length - 65_557);
  let eocd = -1;
  for (let offset = buffer.length - 22; offset >= minimum; offset -= 1) {
    if (buffer.readUInt32LE(offset) === 0x06054b50) {
      eocd = offset;
      break;
    }
  }
  if (eocd < 0) abort("ZIP end-of-central-directory record is missing");

  const entryCount = buffer.readUInt16LE(eocd + 10);
  const centralSize = buffer.readUInt32LE(eocd + 12);
  const centralOffset = buffer.readUInt32LE(eocd + 16);
  if (entryCount === 0xffff || centralOffset === 0xffffffff || centralSize === 0xffffffff) {
    abort("unexpected ZIP64 archive");
  }
  if (centralOffset + centralSize > eocd) abort("central directory extends beyond the archive");

  const entries = new Map();
  let cursor = centralOffset;
  for (let index = 0; index < entryCount; index += 1) {
    if (buffer.readUInt32LE(cursor) !== 0x02014b50) abort(`invalid central-directory entry ${index}`);
    const method = buffer.readUInt16LE(cursor + 10);
    const expectedCrc = buffer.readUInt32LE(cursor + 16);
    const compressedSize = buffer.readUInt32LE(cursor + 20);
    const uncompressedSize = buffer.readUInt32LE(cursor + 24);
    const nameLength = buffer.readUInt16LE(cursor + 28);
    const extraLength = buffer.readUInt16LE(cursor + 30);
    const commentLength = buffer.readUInt16LE(cursor + 32);
    const localOffset = buffer.readUInt32LE(cursor + 42);
    const name = buffer.subarray(cursor + 46, cursor + 46 + nameLength).toString("utf8");

    if (!name || name.startsWith("/") || name.includes("\\") || name.split("/").includes("..")) {
      abort(`unsafe archive path ${JSON.stringify(name)}`);
    }
    if (entries.has(name)) abort(`duplicate archive entry ${name}`);
    entries.set(name, { method, expectedCrc, compressedSize, uncompressedSize, localOffset });
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  if (cursor !== centralOffset + centralSize) abort("central-directory size does not match parsed entries");
  return entries;
}

if (!existsSync(artifact)) abort(`artifact does not exist: ${artifact}`);
const archive = readFileSync(artifact);
const entries = parseZip(archive);

function extract(name) {
  const entry = entries.get(name);
  if (!entry) abort(`required entry is missing: ${name}`);
  const offset = entry.localOffset;
  if (archive.readUInt32LE(offset) !== 0x04034b50) abort(`invalid local header for ${name}`);
  const nameLength = archive.readUInt16LE(offset + 26);
  const extraLength = archive.readUInt16LE(offset + 28);
  const start = offset + 30 + nameLength + extraLength;
  const compressed = archive.subarray(start, start + entry.compressedSize);
  let content;
  if (entry.method === 0) content = compressed;
  else if (entry.method === 8) content = inflateRawSync(compressed);
  else abort(`unsupported compression method ${entry.method} for ${name}`);

  if (content.length !== entry.uncompressedSize) abort(`size mismatch for ${name}`);
  if (crc32(content) !== entry.expectedCrc) abort(`CRC mismatch for ${name}`);
  return content;
}

const required = [
  "[Content_Types].xml",
  "extension.vsixmanifest",
  "extension/package.json",
  "extension/extension.js",
  "extension/chat-participant.js",
  "extension/chat-render.js",
  "extension/chat-routing.js",
  "extension/chat.html",
  "extension/cli-bridge.js",
  "extension/cli-sync.js",
  "extension/control-center.html",
  "extension/conversations.js",
  "extension/runtime-install.js",
  "extension/stack-control.js",
  "extension/media/icon.png",
  "extension/media/icon.svg",
  "extension/readme.md",
  "extension/changelog.md",
  "extension/LICENSE.txt",
];
for (const name of required) extract(name);

const sourceParityFiles = [
  "extension.js",
  "chat-participant.js",
  "chat-render.js",
  "chat-routing.js",
  "chat.html",
  "cli-bridge.js",
  "cli-sync.js",
  "control-center.html",
  "conversations.js",
  "runtime-install.js",
  "stack-control.js",
  "media/icon.png",
  "media/icon.svg",
];
for (const relativePath of sourceParityFiles) {
  const source = readFileSync(join(repoRoot, "integrations", "vscode", relativePath));
  if (!source.equals(extract(`extension/${relativePath}`))) {
    abort(`packaged runtime file differs from the current source: ${relativePath}`);
  }
}

const prohibitedPath = /(?:^|\/)(?:\.env(?:\.|$)|\.git(?:\/|$)|\.pytest_cache(?:\/|$)|\.vscode(?:-test)?(?:\/|$)|test(?:\/|$))/i;
for (const name of entries.keys()) {
  if (prohibitedPath.test(name) || name.toLowerCase().endsWith(".vsix")) {
    abort(`prohibited file was packaged: ${name}`);
  }
}

const packageJson = JSON.parse(extract("extension/package.json").toString("utf8"));
if (packageJson.name !== "aetherstack" || packageJson.publisher !== "AetherStack") {
  abort(`unexpected extension identity ${packageJson.publisher}.${packageJson.name}`);
}
if (packageJson.version !== expectedVersion) {
  abort(`package version ${packageJson.version} does not match VERSION ${expectedVersion}`);
}
if (packageJson.license !== expectedLicense) {
  abort(`package license ${JSON.stringify(packageJson.license)} does not match ${expectedLicense}`);
}
const packagedLicense = extract("extension/LICENSE.txt").toString("utf8");
if (!packagedLicense.startsWith("# PolyForm Noncommercial License 1.0.0\n") || !packagedLicense.includes(requiredNotice)) {
  abort("packaged license is missing the PolyForm Noncommercial terms or required original-author notice");
}
const commands = new Set((packageJson.contributes?.commands ?? []).map((entry) => entry.command));
for (const command of [
  "aetherstack.openChat",
  "aetherstack.openControlCenter",
  "aetherstack.startAll",
  "aetherstack.installRuntime",
  "aetherstack.refreshHostClis",
]) {
  if (!commands.has(command)) abort(`required corrective-release command is missing: ${command}`);
}
if (!(packageJson.contributes?.viewsContainers?.secondarySidebar ?? []).some((entry) => entry.id === "aetherstack")) {
  abort("AetherStack Chat is not discoverable in the Secondary Side Bar");
}
if (!(packageJson.contributes?.viewsContainers?.activitybar ?? []).some((entry) => entry.id === "aetherstack-ops")) {
  abort("AetherStack operations are not discoverable in the Activity Bar");
}
if (!(packageJson.contributes?.chatParticipants ?? []).some((entry) => entry.id === "aetherstack.chat")) {
  abort("native AetherStack Chat participant is missing");
}
for (const relativeTarget of [packageJson.main, packageJson.icon]) {
  const cleanTarget = String(relativeTarget ?? "").replace(/^\.\//, "");
  if (!cleanTarget || !entries.has(`extension/${cleanTarget}`)) {
    abort(`manifest target is absent from VSIX: ${relativeTarget}`);
  }
}

const vsixManifest = extract("extension.vsixmanifest").toString("utf8");
const identity = vsixManifest.match(/<Identity\b[^>]*\bId="([^"]+)"[^>]*\bVersion="([^"]+)"[^>]*\bPublisher="([^"]+)"/i);
if (!identity) abort("could not read Identity from extension.vsixmanifest");
if (identity[1] !== "aetherstack" || identity[2] !== expectedVersion || identity[3] !== "AetherStack") {
  abort(`VSIX identity is ${identity[3]}.${identity[1]} ${identity[2]}, expected AetherStack.aetherstack ${expectedVersion}`);
}

const textExtensions = new Set([".html", ".js", ".json", ".md", ".ps1", ".sh", ".svg", ".txt", ".xml", ".yaml", ".yml"]);
const secretPatterns = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/,
  /\b[A-Za-z]:\\Users\\[^\\\s]+\\/,
  /\/(?:home|Users)\/[^/\s]+\//,
];
for (const name of entries.keys()) {
  if (!textExtensions.has(extname(name).toLowerCase())) continue;
  const content = extract(name).toString("utf8");
  for (const pattern of secretPatterns) {
    if (pattern.test(content)) abort(`private credential or machine-specific path pattern found in ${name}`);
  }
}

console.log(`VSIX artifact OK: ${basename(artifact)}`);
console.log(`identity: AetherStack.aetherstack ${expectedVersion}`);
console.log(`contents: ${entries.size} entries; runtime bytes and license match source; private/test files absent`);
