const assert = require("node:assert/strict");
const test = require("node:test");

const { createCliBridge, discoverCliModels, promptFromMessages, splitMessages, safeCliEnvironment } = require("../cli-bridge");

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

test("bridge quarantines a provider after a terminal account failure", async () => {
  const bridge = createCliBridge({
    token: "quarantine-token",
    port: 0,
    host: "127.0.0.1",
    resolver,
    runner,
    executor: async (model) => {
      if (model.alias === "grok-cli") throw new Error("API error (status 402 Payment Required): usage balance exhausted");
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
    assert.equal(failed.status, 500);
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
    const oversized = await fetch(url, {
      method: "POST",
      headers: { Authorization: "Bearer body-test-token", "Content-Type": "application/json" },
      body: JSON.stringify({ model: "codex-cli", messages: [{ role: "user", content: "x".repeat(600_000) }] }),
    });
    assert.equal(oversized.status, 413);
    assert.equal(executions, 0);
  } finally {
    bridge.stop();
  }
});

test("CLI children do not inherit bridge tokens or provider API keys", () => {
  const oldBridge = process.env.AETHER_CLI_BRIDGE_TOKEN;
  const oldOpenAi = process.env.OPENAI_API_KEY;
  process.env.AETHER_CLI_BRIDGE_TOKEN = "secret-bridge-token";
  process.env.OPENAI_API_KEY = "secret-provider-key";
  try {
    const childEnv = safeCliEnvironment();
    assert.equal(childEnv.AETHER_CLI_BRIDGE_TOKEN, undefined);
    assert.equal(childEnv.OPENAI_API_KEY, undefined);
    assert.ok(childEnv.PATH || childEnv.Path);
  } finally {
    if (oldBridge === undefined) delete process.env.AETHER_CLI_BRIDGE_TOKEN; else process.env.AETHER_CLI_BRIDGE_TOKEN = oldBridge;
    if (oldOpenAi === undefined) delete process.env.OPENAI_API_KEY; else process.env.OPENAI_API_KEY = oldOpenAi;
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
