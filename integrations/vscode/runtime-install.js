"use strict";

const crypto = require("crypto");
const fs = require("fs");
const https = require("https");
const path = require("path");
const { execFile } = require("child_process");

const REPOSITORY = "piksliviksi/aetherstack";
const MAX_RUNTIME_BYTES = 200 * 1024 * 1024;
const MAX_CHECKSUM_BYTES = 4096;

function assertVersion(version) {
  const value = String(version || "");
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(value)) {
    throw new Error(`Invalid AetherStack runtime version: ${value || "empty"}`);
  }
  return value;
}

function releaseAssetUrls(version, repository = REPOSITORY) {
  const safeVersion = assertVersion(version);
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) {
    throw new Error("Invalid AetherStack release repository");
  }
  const filename = `aetherstack-runtime-${safeVersion}.tar.gz`;
  const base = `https://github.com/${repository}/releases/download/v${safeVersion}`;
  return {
    filename,
    archive: `${base}/${filename}`,
    checksum: `${base}/${filename}.sha256`,
  };
}

function parseChecksum(text, filename) {
  for (const line of String(text || "").split(/\r?\n/)) {
    const match = /^([a-fA-F0-9]{64})\s+\*?(.+?)\s*$/.exec(line);
    if (match && path.basename(match[2]) === filename) return match[1].toLowerCase();
  }
  throw new Error(`Checksum manifest does not contain ${filename}`);
}

function validateArchiveEntries(text) {
  const entries = String(text || "").split(/\r?\n/).map((entry) => entry.trim()).filter(Boolean);
  if (!entries.length) throw new Error("Runtime archive is empty");
  for (const raw of entries) {
    const entry = raw.replaceAll("\\", "/");
    const parts = entry.split("/").filter(Boolean);
    if (entry.startsWith("/") || /^[A-Za-z]:/.test(entry) || parts.includes("..")) {
      throw new Error(`Runtime archive contains an unsafe path: ${raw}`);
    }
  }
  return entries;
}

function hashFile(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(file);
    stream.on("error", reject);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

function downloadFile(urlString, destination, { maxBytes = MAX_RUNTIME_BYTES, redirects = 5 } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    if (url.protocol !== "https:") {
      reject(new Error("Runtime downloads require HTTPS"));
      return;
    }
    const request = https.get(url, {
      headers: { "User-Agent": "AetherStack-VSCode-Runtime-Installer" },
      timeout: 30_000,
    }, (response) => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        if (redirects <= 0) {
          reject(new Error("Too many runtime download redirects"));
          return;
        }
        const next = new URL(response.headers.location, url).toString();
        downloadFile(next, destination, { maxBytes, redirects: redirects - 1 }).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`Runtime download returned HTTP ${response.statusCode}`));
        return;
      }
      const declared = Number(response.headers["content-length"] || 0);
      if (declared > maxBytes) {
        response.resume();
        reject(new Error("Runtime download exceeds the size limit"));
        return;
      }
      const output = fs.createWriteStream(destination, { flags: "wx", mode: 0o600 });
      let received = 0;
      let settled = false;
      const fail = (error) => {
        if (settled) return;
        settled = true;
        output.destroy();
        fs.rmSync(destination, { force: true });
        reject(error);
      };
      response.on("data", (chunk) => {
        received += chunk.length;
        if (received > maxBytes) {
          response.destroy();
          fail(new Error("Runtime download exceeds the size limit"));
        }
      });
      response.on("error", fail);
      output.on("error", fail);
      output.on("finish", () => {
        if (settled) return;
        settled = true;
        output.close(() => resolve(destination));
      });
      response.pipe(output);
    });
    request.on("timeout", () => request.destroy(new Error("Runtime download timed out")));
    request.on("error", reject);
  });
}

function execFileResult(file, args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(file, args, { windowsHide: true, maxBuffer: 4 * 1024 * 1024, ...options }, (error, stdout, stderr) => {
      if (error) {
        error.detail = String(stderr || stdout || error.message).trim();
        reject(error);
      } else resolve({ stdout: String(stdout || ""), stderr: String(stderr || "") });
    });
  });
}

function isRuntimeRoot(candidate) {
  return ["docker-compose.yml", "litellm_config.yaml", "aether-hub"].every((name) => fs.existsSync(path.join(candidate, name)));
}

function isInside(parent, child) {
  const relative = path.relative(path.resolve(parent), path.resolve(child));
  return relative && !relative.startsWith("..") && !path.isAbsolute(relative);
}

async function installRuntime({ version, storagePath, repository = REPOSITORY, downloader = downloadFile, runner = execFileResult }) {
  const safeVersion = assertVersion(version);
  if (!storagePath) throw new Error("VS Code did not provide an extension storage directory");
  const runtimeBase = path.resolve(storagePath, "runtime");
  const finalDir = path.resolve(runtimeBase, safeVersion);
  fs.mkdirSync(runtimeBase, { recursive: true });
  if (fs.existsSync(finalDir)) {
    if (isRuntimeRoot(finalDir)) return { root: finalDir, reused: true, version: safeVersion };
    throw new Error(`Existing runtime directory is incomplete: ${finalDir}`);
  }

  const nonce = crypto.randomBytes(8).toString("hex");
  const stagingDir = path.resolve(runtimeBase, `.install-${safeVersion}-${nonce}`);
  const archivePath = path.resolve(runtimeBase, `.download-${safeVersion}-${nonce}.tar.gz`);
  const checksumPath = `${archivePath}.sha256`;
  if (![stagingDir, archivePath, checksumPath].every((target) => isInside(runtimeBase, target))) {
    throw new Error("Refusing an unsafe runtime installation path");
  }
  const urls = releaseAssetUrls(safeVersion, repository);

  try {
    await downloader(urls.archive, archivePath, { maxBytes: MAX_RUNTIME_BYTES });
    await downloader(urls.checksum, checksumPath, { maxBytes: MAX_CHECKSUM_BYTES });
    const expected = parseChecksum(fs.readFileSync(checksumPath, "utf8"), urls.filename);
    const actual = await hashFile(archivePath);
    if (actual !== expected) throw new Error(`Runtime checksum mismatch: expected ${expected}, received ${actual}`);

    let listing;
    try {
      listing = await runner("tar", ["-tzf", archivePath], { timeout: 30_000 });
    } catch (error) {
      if (error.code === "ENOENT") throw new Error("The system tar utility is required to install AetherStack Runtime");
      throw new Error(`Cannot inspect runtime archive: ${error.detail || error.message}`);
    }
    validateArchiveEntries(listing.stdout);
    fs.mkdirSync(stagingDir, { recursive: true });
    try {
      await runner("tar", ["-xzf", archivePath, "-C", stagingDir], { timeout: 2 * 60_000 });
    } catch (error) {
      throw new Error(`Cannot extract runtime archive: ${error.detail || error.message}`);
    }
    if (!isRuntimeRoot(stagingDir)) throw new Error("Downloaded archive is not an AetherStack runtime bundle");
    fs.renameSync(stagingDir, finalDir);
    return { root: finalDir, reused: false, version: safeVersion, checksum: actual };
  } finally {
    fs.rmSync(archivePath, { force: true });
    fs.rmSync(checksumPath, { force: true });
    if (fs.existsSync(stagingDir)) fs.rmSync(stagingDir, { recursive: true, force: true });
  }
}

module.exports = {
  MAX_RUNTIME_BYTES,
  REPOSITORY,
  assertVersion,
  downloadFile,
  installRuntime,
  isRuntimeRoot,
  parseChecksum,
  releaseAssetUrls,
  validateArchiveEntries,
};
