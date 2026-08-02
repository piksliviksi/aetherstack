const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { createCliBridge, discoverCliModels, findBundledClaude, findBundledCodex, promptFromMessages, splitMessages, safeCliEnvironment, spawnWithInput, runCliModel } = require("../cli-bridge");

const resolver = async (command) => `C:\\tools\\${command}.exe`;
const runner = async (_command, args) => {
  if (args[0] === "login") return { ok: true, stdout: "Logged in using ChatGPT", stderr: "" };
  if (args[0] === "auth") return { ok: true, stdout: JSON.stringify({ loggedIn: true, authMethod: "claude.ai" }), stderr: "" };
  return { ok: true, stdout: "grok-code\ngrok-4", stderr: "" };
};

test("discovers only authenticated host CLI models with capability metadata", async () => {
  const models = await discoverCliModels({ resolver, runner });
  assert.deepEqual(Object.keys(models).sort(), ["claude-cli", "codex-cli", "grok-cli"]);
  assert.equal(models["codex-cli"].executor, "host_cli");
  assert.ok(models["claude-cli"].capabilities.includes("vision"));
  assert.equal(models["grok-cli"].commandPath, "C:\\tools\\grok.exe");
});

test("bridge requires its bearer token and exposes OpenAI-compatible completions", async () => {
  const bridge = createCliBridge({
    token: "unit-test-token",
    port: 0,
    resolver,
    runner,
    executor: async (model, prompt) => `${model.alias}: ${prompt === "hello" ? "ok" : "bad"}`,
  });
  const state = await bridge.start();
  try {
    const base = `http://127.0.0.1:${state.port}`;
    const denied = await fetch(`${base}/v1/models`);
    assert.equal(denied.status, 401);
    const models = await fetch(`${base}/v1/models`, { headers: { Authorization: "Bearer unit-test-token" } }).then((response) => response.json());
    assert.equal(models.models.length, 3);
    assert.equal(models.models.some((model) => Object.hasOwn(model, "commandPath")), false);

    const completion = await fetch(`${base}/v1/chat/completions`, {
      method: "POST",
      headers: { Authorization: "Bearer unit-test-token", "Content-Type": "application/json" },
      body: JSON.stringify({ model: "claude-cli", messages: [{ role: "user", content: "hello" }] }),
    }).then((response) => response.json());
    assert.equal(completion.model, "claude-cli");
    assert.equal(completion.choices[0].message.content, "claude-cli: ok");
  } finally {
    bridge.stop();
  }
});

test("default bind is loopback-only when no host is given", async () => {
  const bridge = createCliBridge({
    token: "loopback-default-token",
    port: 0,
    resolver,
    runner,
  });
  const state = await bridge.start();
  try {
    assert.equal(bridge.host, "127.0.0.1");
  } finally {
    bridge.stop();
  }
});

test("bridge quarantines a provider after a terminal account failure", async () => {
  const bridge = createCliBridge({
    token: "quarantine-token",
    port: 0,
    host: "127.0.0.1",
    resolver,
    runner,
    executor: async (model) => {
      if (model.alias === "grok-cli") throw new Error("You've hit your session limit; resets later today");
      return "ok";
    },
  });
  const state = await bridge.start();
  try {
    const base = `http://127.0.0.1:${state.port}`;
    const headers = { Authorization: "Bearer quarantine-token", "Content-Type": "application/json" };
    const failed = await fetch(`${base}/v1/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify({ model: "grok-cli", messages: [{ role: "user", content: "hello" }] }),
    });
    assert.equal(failed.status, 429);
    assert.equal((await failed.json()).code, "provider_limit_reached");
    const models = await fetch(`${base}/v1/models?refresh=1`, { headers }).then((response) => response.json());
    assert.equal(models.models.some((model) => model.alias === "grok-cli"), false);
    assert.equal(models.models.some((model) => model.alias === "codex-cli"), true);
  } finally {
    bridge.stop();
  }
});

test("a second VS Code window reads the authenticated bridge it reuses", async () => {
  const first = createCliBridge({ token: "shared-window-token", port: 0, host: "127.0.0.1", resolver, runner });
  const firstState = await first.start();
  const second = createCliBridge({
    token: "shared-window-token",
    port: firstState.port,
    host: "127.0.0.1",
    resolver: async () => null,
    runner,
  });
  try {
    const secondState = await second.start();
    assert.equal(secondState.reused, true);
    const models = await second.models(true);
    assert.deepEqual(Object.keys(models).sort(), ["claude-cli", "codex-cli", "grok-cli"]);
  } finally {
    second.stop();
    first.stop();
  }
});

test("prompt conversion drops system turns and enforces its bound", () => {
  const prompt = promptFromMessages([{ role: "system", content: "rules" }, { role: "user", content: "x".repeat(120_000) }]);
  assert.ok(prompt.length <= 100_000);
  assert.doesNotMatch(prompt, /SYSTEM:/);
  assert.doesNotMatch(prompt, /rules/);
});

test("bridge rejects non-JSON and oversized bodies without executing a CLI", async () => {
  let executions = 0;
  const bridge = createCliBridge({
    token: "body-test-token",
    port: 0,
    host: "127.0.0.1",
    resolver,
    runner,
    executor: async () => { executions += 1; return "unexpected"; },
  });
  const state = await bridge.start();
  try {
    const url = `http://127.0.0.1:${state.port}/v1/chat/completions`;
    const wrongType = await fetch(url, {
      method: "POST",
      headers: { Authorization: "Bearer body-test-token", "Content-Type": "text/plain" },
      body: "{}",
    });
    assert.equal(wrongType.status, 415);
    assert.equal((await wrongType.json()).code, "unsupported_media_type");
    const oversized = await fetch(url, {
      method: "POST",
      headers: { Authorization: "Bearer body-test-token", "Content-Type": "application/json" },
      body: JSON.stringify({ model: "codex-cli", messages: [{ role: "user", content: "x".repeat(600_000) }] }),
    });
    assert.equal(oversized.status, 413);
    assert.equal((await oversized.json()).code, "request_too_large");
    assert.equal(executions, 0);
  } finally {
    bridge.stop();
  }
});

test("bridge returns stable provider error codes without leaking raw CLI output", async () => {
  const bridge = createCliBridge({
    token: "typed-error-token",
    port: 0,
    discoverCliModels: undefined,
    runner: async () => ({ ok: true, stdout: "logged in", stderr: "" }),
    resolver: async () => "/fake/codex",
    executor: async () => { throw new Error("secret path /Users/private failed: You've hit your usage limit"); },
  });
  const state = await bridge.start();
  try {
    const response = await fetch(`http://127.0.0.1:${state.port}/v1/chat/completions`, {
      method: "POST",
      headers: { Authorization: "Bearer typed-error-token", "Content-Type": "application/json" },
      body: JSON.stringify({ model: "codex-cli", messages: [{ role: "user", content: "test" }] }),
    });
    const body = await response.json();
    assert.equal(response.status, 429);
    assert.equal(body.code, "provider_limit_reached");
    assert.doesNotMatch(body.error, /Users|private/);
  } finally {
    bridge.stop();
  }
});

test("host CLI capture marks truncation and enforces timeout", async () => {
  const output = await spawnWithInput(
    process.execPath,
    ["-e", "process.stdin.resume(); process.stdin.on('end', () => process.stdout.write('x'.repeat(4096)))"],
    "input",
    { stdoutLimit: 512, timeout: 2000 },
  );
  assert.ok(Buffer.byteLength(output) <= 512);
  assert.match(output, /host CLI output truncated/);
  await assert.rejects(
    () => spawnWithInput(process.execPath, ["-e", "setTimeout(() => {}, 5000)"], "", { timeout: 20 }),
    /timed out/,
  );
});

test("CLI children do not inherit bridge tokens or provider API keys", () => {
  const testValues = {
    AETHER_CLI_BRIDGE_TOKEN: "secret-bridge-token",
    OPENAI_API_KEY: "secret-provider-key",
    DATABASE_URL: "postgres://secret@localhost/db",
    AWS_SECRET_ACCESS_KEY: "aws-secret",
    SSH_AUTH_SOCK: "/tmp/private-agent.sock",
    UNEXPECTED_CREDENTIAL: "unknown-secret",
    CODEX_HOME: "/tmp/codex-home",
  };
  const previous = Object.fromEntries(Object.keys(testValues).map((name) => [name, process.env[name]]));
  Object.assign(process.env, testValues);
  try {
    const childEnv = safeCliEnvironment();
    assert.equal(childEnv.AETHER_CLI_BRIDGE_TOKEN, undefined);
    assert.equal(childEnv.OPENAI_API_KEY, undefined);
    assert.equal(childEnv.DATABASE_URL, undefined);
    assert.equal(childEnv.AWS_SECRET_ACCESS_KEY, undefined);
    assert.equal(childEnv.SSH_AUTH_SOCK, undefined);
    assert.equal(childEnv.UNEXPECTED_CREDENTIAL, undefined);
    assert.equal(childEnv.CODEX_HOME, "/tmp/codex-home");
    assert.ok(childEnv.PATH || childEnv.Path);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
  }
});

test("system turns never reach the model as SYSTEM: prompt text", () => {
  const messages = [
    { role: "system", content: "You are AetherStack Auto. Do not mention orchestration." },
    { role: "user", content: "fix the bug" },
  ];
  const { system, conversation } = splitMessages(messages);
  assert.equal(system, "You are AetherStack Auto. Do not mention orchestration.");
  assert.equal(conversation.length, 1);
  const prompt = promptFromMessages(conversation);
  assert.doesNotMatch(prompt, /SYSTEM:/);
  assert.doesNotMatch(prompt, /orchestration/);
  // a lone user turn is passed through verbatim
  assert.equal(prompt, "fix the bug");
});

test("multi-turn conversations keep role headers but still exclude system", () => {
  const { system, conversation } = splitMessages([
    { role: "system", content: "secret instructions" },
    { role: "user", content: "first" },
    { role: "assistant", content: "reply" },
    { role: "user", content: "second" },
  ]);
  assert.equal(system, "secret instructions");
  const prompt = promptFromMessages(conversation);
  assert.doesNotMatch(prompt, /SYSTEM:/);
  assert.doesNotMatch(prompt, /secret instructions/);
  assert.match(prompt, /USER:\nfirst/);
  assert.match(prompt, /ASSISTANT:\nreply/);
});

test("bridge hands the system prompt to the executor out of band", async () => {
  let seen = null;
  const bridge = createCliBridge({
    token: "sys-token",
    port: 0,
    resolver,
    runner,
    executor: async (_model, prompt, options) => { seen = { prompt, system: options.system }; return "done"; },
  });
  const state = await bridge.start();
  try {
    await fetch(`http://127.0.0.1:${state.port}/v1/chat/completions`, {
      method: "POST",
      headers: { Authorization: "Bearer sys-token", "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "claude-cli",
        messages: [
          { role: "system", content: "answer directly" },
          { role: "user", content: "hi" },
        ],
      }),
    }).then((response) => response.json());
    assert.equal(seen.prompt, "hi");
    assert.equal(seen.system, "answer directly");
  } finally {
    bridge.stop();
  }
});

test("bridge forwards workspace-write permission only when explicitly requested", async () => {
  const seen = [];
  const bridge = createCliBridge({
    token: "write-mode-token",
    port: 0,
    resolver,
    runner,
    executor: async (_model, _prompt, options) => { seen.push(options.workspaceWrite); return "done"; },
  });
  const state = await bridge.start();
  try {
    const url = `http://127.0.0.1:${state.port}/v1/chat/completions`;
    const headers = { Authorization: "Bearer write-mode-token", "Content-Type": "application/json" };
    await fetch(url, { method: "POST", headers, body: JSON.stringify({ model: "codex-cli", messages: [{ role: "user", content: "read" }] }) });
    await fetch(url, { method: "POST", headers, body: JSON.stringify({ model: "codex-cli", messages: [{ role: "user", content: "edit" }], workspace_write: true }) });
    assert.deepEqual(seen, [false, true]);
  } finally {
    bridge.stop();
  }
});

test("each host CLI declares how it accepts a system prompt", async () => {
  const models = await discoverCliModels({ resolver, runner });
  assert.equal(models["claude-cli"].systemPromptFlag, "--append-system-prompt");
  assert.equal(models["claude-cli"].systemPromptPrefix, "");
  assert.equal(models["grok-cli"].systemPromptFlag, "--rules");
  // codex has no flag; it takes a config override: -c developer_instructions=<text>
  assert.equal(models["codex-cli"].systemPromptFlag, "-c");
  assert.equal(models["codex-cli"].systemPromptPrefix, "developer_instructions=");
});

test("system prompt argv is built per CLI, flag or config-override", () => {
  const build = (model, system) => {
    const flag = model.systemPromptFlag;
    if (!flag || !system) return [];
    return [flag, `${model.systemPromptPrefix || ""}${system}`];
  };
  assert.deepEqual(
    build({ systemPromptFlag: "--append-system-prompt" }, "be terse"),
    ["--append-system-prompt", "be terse"]
  );
  assert.deepEqual(
    build({ systemPromptFlag: "-c", systemPromptPrefix: "developer_instructions=" }, "be terse"),
    ["-c", "developer_instructions=be terse"]
  );
  assert.deepEqual(build({ systemPromptFlag: "--rules" }, ""), []);
});

test("system prompts are capped so argv stays under the OS limit", () => {
  const { system } = splitMessages([{ role: "system", content: "x".repeat(50_000) }]);
  assert.ok(system.length <= 8_000, `system was ${system.length} chars`);
});

test("Grok bridge execution disables planning and subagents for bounded worker calls", () => {
  const source = runCliModel.toString();
  assert.match(source, /"--no-plan"/);
  assert.match(source, /"--no-subagents"/);
  assert.match(source, /"--max-turns", "8"/);
});

test("bundled CLI discovery requires trusted manifests and in-root regular executables", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "aether-cli-trust-"));
  const platform = process.platform === "win32" ? "windows-x64"
    : process.platform === "darwin" ? "macos-aarch64" : "linux-x64";
  const codexName = process.platform === "win32" ? "codex.exe" : "codex";
  const claudeName = process.platform === "win32" ? "claude.exe" : "claude";
  try {
    const codexRoot = path.join(root, "openai.chatgpt-1.0.0");
    const codex = path.join(codexRoot, "bin", platform, codexName);
    fs.mkdirSync(path.dirname(codex), { recursive: true });
    fs.writeFileSync(path.join(codexRoot, "package.json"), JSON.stringify({ publisher: "openai", name: "chatgpt" }));
    fs.writeFileSync(codex, "binary");
    assert.equal(await findBundledCodex([root]), fs.realpathSync(codex));

    fs.writeFileSync(path.join(codexRoot, "package.json"), JSON.stringify({ publisher: "attacker", name: "chatgpt" }));
    assert.equal(await findBundledCodex([root]), null);

    const claudeRoot = path.join(root, "anthropic.claude-code-1.0.0");
    const claude = path.join(claudeRoot, "resources", "native-binary", claudeName);
    fs.mkdirSync(path.dirname(claude), { recursive: true });
    fs.writeFileSync(path.join(claudeRoot, "package.json"), JSON.stringify({ publisher: "anthropic", name: "claude-code" }));
    fs.writeFileSync(claude, "binary");
    assert.equal(await findBundledClaude([root]), fs.realpathSync(claude));

    const outside = path.join(root, "outside");
    fs.writeFileSync(outside, "binary");
    fs.rmSync(claude);
    try {
      fs.symlinkSync(outside, claude);
      assert.equal(await findBundledClaude([root]), null);
    } catch (error) {
      if (process.platform !== "win32" || error.code !== "EPERM") throw error;
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
