const assert = require("node:assert/strict");
const test = require("node:test");

const { createCliBridge, discoverCliModels, promptFromMessages, safeCliEnvironment } = require("../cli-bridge");

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
    executor: async (model, prompt) => `${model.alias}: ${prompt.includes("USER:\nhello") ? "ok" : "bad"}`,
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

test("prompt conversion preserves roles and enforces its bound", () => {
  const prompt = promptFromMessages([{ role: "system", content: "rules" }, { role: "user", content: "x".repeat(120_000) }]);
  assert.ok(prompt.length <= 100_000);
  assert.match(prompt, /USER:/);
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
