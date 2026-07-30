const assert = require("node:assert/strict");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const test = require("node:test");

const {
  installRuntime,
  parseChecksum,
  releaseAssetUrls,
  validateArchiveEntries,
} = require("../runtime-install");

test("release URLs are immutable and version-pinned", () => {
  const urls = releaseAssetUrls("0.3.12");
  assert.equal(urls.filename, "aetherstack-runtime-0.3.12.tar.gz");
  assert.match(urls.archive, /releases\/download\/v0\.3\.12\/aetherstack-runtime-0\.3\.12\.tar\.gz$/);
  assert.throws(() => releaseAssetUrls("main"), /Invalid/);
});

test("checksum parser binds the digest to the expected asset", () => {
  const digest = "a".repeat(64);
  assert.equal(parseChecksum(`${digest}  aetherstack-runtime-0.3.12.tar.gz\n`, "aetherstack-runtime-0.3.12.tar.gz"), digest);
  assert.throws(() => parseChecksum(`${digest}  another.tar.gz`, "expected.tar.gz"), /does not contain/);
});

test("runtime archive paths reject traversal and absolute targets", () => {
  assert.deepEqual(validateArchiveEntries("docker-compose.yml\naether-hub/server.py\n"), ["docker-compose.yml", "aether-hub/server.py"]);
  assert.throws(() => validateArchiveEntries("../outside.txt"), /unsafe path/);
  assert.throws(() => validateArchiveEntries("C:\\outside.txt"), /unsafe path/);
  assert.throws(() => validateArchiveEntries("/etc/passwd"), /unsafe path/);
});

test("installer verifies checksum and promotes only a complete runtime", async () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-runtime-test-"));
  const archiveBody = Buffer.from("test runtime archive");
  const digest = crypto.createHash("sha256").update(archiveBody).digest("hex");
  const downloader = async (url, destination) => {
    fs.writeFileSync(destination, url.endsWith(".sha256")
      ? `${digest}  aetherstack-runtime-0.3.12.tar.gz\n`
      : archiveBody);
  };
  const runner = async (_file, args) => {
    if (args[0] === "-tzf") return { stdout: "docker-compose.yml\nlitellm_config.yaml\naether-hub/server.py\n", stderr: "" };
    const target = args[args.indexOf("-C") + 1];
    fs.mkdirSync(path.join(target, "aether-hub"), { recursive: true });
    fs.writeFileSync(path.join(target, "docker-compose.yml"), "services: {}\n");
    fs.writeFileSync(path.join(target, "litellm_config.yaml"), "model_list: []\n");
    return { stdout: "", stderr: "" };
  };
  try {
    const result = await installRuntime({ version: "0.3.12", storagePath: temp, downloader, runner });
    assert.equal(result.reused, false);
    assert.equal(result.checksum, digest);
    assert.equal(fs.existsSync(path.join(result.root, "aether-hub")), true);
    const reused = await installRuntime({ version: "0.3.12", storagePath: temp, downloader, runner });
    assert.equal(reused.reused, true);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});

test("installer uses the checksum-verified runtime bundled inside the VSIX without a network request", async () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-runtime-bundled-"));
  const bundled = path.join(temp, "bundle");
  const archiveName = "aetherstack-runtime-0.3.12.tar.gz";
  const archiveBody = Buffer.from("bundled runtime archive");
  const digest = crypto.createHash("sha256").update(archiveBody).digest("hex");
  fs.mkdirSync(bundled, { recursive: true });
  fs.writeFileSync(path.join(bundled, archiveName), archiveBody);
  fs.writeFileSync(path.join(bundled, `${archiveName}.sha256`), `${digest}  ${archiveName}\n`);
  const runner = async (_file, args) => {
    if (args[0] === "-tzf") return { stdout: "docker-compose.yml\nlitellm_config.yaml\naether-hub/server.py\n", stderr: "" };
    const target = args[args.indexOf("-C") + 1];
    fs.mkdirSync(path.join(target, "aether-hub"), { recursive: true });
    fs.writeFileSync(path.join(target, "docker-compose.yml"), "services: {}\n");
    fs.writeFileSync(path.join(target, "litellm_config.yaml"), "model_list: []\n");
    return { stdout: "", stderr: "" };
  };
  const downloader = async () => { throw new Error("network must not be used for a bundled runtime"); };
  try {
    const result = await installRuntime({ version: "0.3.12", storagePath: path.join(temp, "storage"), bundledPath: bundled, downloader, runner });
    assert.equal(result.reused, false);
    assert.equal(result.checksum, digest);
    assert.equal(fs.existsSync(path.join(result.root, "aether-hub")), true);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});

test("installer rejects a checksum mismatch without leaving a runnable directory", async () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "aetherstack-runtime-bad-checksum-"));
  const downloader = async (url, destination) => {
    fs.writeFileSync(destination, url.endsWith(".sha256")
      ? `${"0".repeat(64)}  aetherstack-runtime-0.3.12.tar.gz\n`
      : Buffer.from("tampered runtime"));
  };
  try {
    await assert.rejects(
      () => installRuntime({ version: "0.3.12", storagePath: temp, downloader }),
      /checksum mismatch/i,
    );
    const runtimeBase = path.join(temp, "runtime");
    assert.equal(fs.existsSync(path.join(runtimeBase, "0.3.12")), false);
    assert.deepEqual(fs.readdirSync(runtimeBase), []);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
