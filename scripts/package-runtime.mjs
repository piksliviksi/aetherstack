#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  lstatSync,
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..");
const distDir = join(repoRoot, "dist");
const version = readFileSync(join(repoRoot, "VERSION"), "utf8").trim();
const filename = `aetherstack-runtime-${version}.tar.gz`;
const output = join(distDir, filename);
const checksum = `${output}.sha256`;

const rootFiles = new Set([
  ".env.example",
  "LICENSE",
  "README.md",
  "VERSION",
  "aetherstack_callback.py",
  "docker-compose.amd.yml",
  "docker-compose.nvidia.yml",
  "docker-compose.yml",
  "litellm_config.yaml",
  "litellm_multi_keys.fragment.yaml",
  "start.bat",
  "start.ps1",
  "start.sh",
  "stop.bat",
  "stop.ps1",
  "stop.sh",
]);
const runtimePrefixes = [
  "aether-amd/",
  "aether-hub/",
  "combos/",
  "open-webui-config/",
  "open-webui-proxy/",
  "pipelines/",
  "project-engine/",
  "scripts/",
];
const releaseOnlyScripts = /^scripts\/(?:package-|verify-)/;

function fail(message) {
  console.error(`runtime packaging failed: ${message}`);
  process.exit(1);
}

const tracked = spawnSync("git", ["ls-files", "--cached", "--stage", "-z"], {
  cwd: repoRoot,
  encoding: "utf8",
});
if (tracked.error || tracked.status !== 0) {
  fail(tracked.error?.message ?? tracked.stderr.trim());
}
const trackedEntries = tracked.stdout.split("\0").filter(Boolean).map((record) => {
  const match = /^(\d{6}) [a-f0-9]+ \d+\t(.+)$/.exec(record);
  if (!match) fail(`cannot parse tracked file record: ${record}`);
  return { mode: match[1], name: match[2] };
});
const entries = trackedEntries.filter(({ name }) => (
  rootFiles.has(name)
  || (runtimePrefixes.some((prefix) => name.startsWith(prefix)) && !releaseOnlyScripts.test(name))
)).sort((left, right) => (left.name < right.name ? -1 : left.name > right.name ? 1 : 0));
const files = entries.map(({ name }) => name);
for (const required of ["VERSION", "docker-compose.yml", "aether-hub/server.py", "aether-hub/inference_runtime.py"]) {
  if (!files.includes(required)) fail(`required tracked runtime file is missing: ${required}`);
}
for (const name of files) {
  const info = lstatSync(join(repoRoot, name));
  if (!info.isFile() || info.isSymbolicLink()) fail(`runtime entry must be a regular file: ${name}`);
}

mkdirSync(distDir, { recursive: true });
rmSync(output, { force: true });
rmSync(checksum, { force: true });

function writeOctal(header, offset, length, value) {
  const encoded = `${Number(value).toString(8).padStart(length - 1, "0")}\0`;
  header.write(encoded, offset, length, "ascii");
}

function tarName(name) {
  if (Buffer.byteLength(name) <= 100) return { name, prefix: "" };
  for (let index = name.lastIndexOf("/"); index > 0; index = name.lastIndexOf("/", index - 1)) {
    const prefix = name.slice(0, index);
    const leaf = name.slice(index + 1);
    if (Buffer.byteLength(prefix) <= 155 && Buffer.byteLength(leaf) <= 100) return { name: leaf, prefix };
  }
  fail(`runtime path exceeds the portable ustar name limit: ${name}`);
}

const tarParts = [];
for (const entry of entries) {
  const content = readFileSync(join(repoRoot, entry.name));
  const header = Buffer.alloc(512);
  const portableName = tarName(entry.name);
  header.write(portableName.name, 0, 100, "utf8");
  writeOctal(header, 100, 8, entry.mode === "100755" ? 0o755 : 0o644);
  writeOctal(header, 108, 8, 0);
  writeOctal(header, 116, 8, 0);
  writeOctal(header, 124, 12, content.length);
  writeOctal(header, 136, 12, 0);
  header.fill(0x20, 148, 156);
  header.write("0", 156, 1, "ascii");
  header.write("ustar\0", 257, 6, "ascii");
  header.write("00", 263, 2, "ascii");
  header.write("root", 265, 32, "ascii");
  header.write("root", 297, 32, "ascii");
  writeOctal(header, 329, 8, 0);
  writeOctal(header, 337, 8, 0);
  header.write(portableName.prefix, 345, 155, "utf8");
  const sum = header.reduce((total, byte) => total + byte, 0);
  header.write(`${sum.toString(8).padStart(6, "0")}\0 `, 148, 8, "ascii");
  tarParts.push(header, content);
  const padding = (512 - (content.length % 512)) % 512;
  if (padding) tarParts.push(Buffer.alloc(padding));
}
tarParts.push(Buffer.alloc(1024));
const archive = gzipSync(Buffer.concat(tarParts), { level: 9, mtime: 0 });
archive[9] = 0xff; // neutral gzip OS byte for cross-platform byte identity
writeFileSync(output, archive);

const size = statSync(output).size;
if (size < 10_000 || size > 200 * 1024 * 1024) fail(`implausible archive size: ${size} bytes`);
const digest = createHash("sha256").update(readFileSync(output)).digest("hex");
writeFileSync(checksum, `${digest}  ${basename(output)}\n`, "utf8");
console.log(`packaged ${output} (${size} bytes)`);
console.log(`sha256 ${digest}`);
