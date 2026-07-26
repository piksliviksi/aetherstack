const assert = require("node:assert/strict");
const test = require("node:test");

const { availableHostCliAliases, reconcileHostCliBridge } = require("../cli-sync");

const matrix = (aliases) => ({
  models: Object.fromEntries(aliases.map((alias) => [alias, { available: true, executor: "host_cli" }])),
});

test("host CLI alias inspection ignores unavailable and non-bridge models", () => {
  assert.deepEqual(availableHostCliAliases({ models: {
    "codex-cli": { available: true, executor: "host_cli" },
    "claude-cli": { available: false, executor: "host_cli" },
    "local-default": { available: true, executor: "litellm" },
  } }), ["codex-cli"]);
});

test("bridge reconciliation does nothing when the Hub matrix is current", async () => {
  let composeCalls = 0;
  const result = await reconcileHostCliBridge({
    stackRoot: "D:\\llm\\stack",
    cliBridge: { models: async () => ({ "codex-cli": {}, "claude-cli": {} }) },
    request: async () => ({ status: 200, body: matrix(["codex-cli", "claude-cli"]) }),
    runCompose: async () => { composeCalls += 1; },
  });
  assert.equal(result.changed, false);
  assert.equal(composeCalls, 0);
});

test("bridge reconciliation recreates only Hub when authenticated CLIs are missing", async () => {
  let applied = false;
  const composeCalls = [];
  const request = async (url, options = {}) => {
    if (url.endsWith("/api/health")) return { status: 200, body: { ok: true } };
    if (url.endsWith("/api/services/refresh")) {
      assert.equal(options.method, "POST");
      return { status: 200, body: { services: [] } };
    }
    return { status: 200, body: applied ? matrix(["codex-cli", "claude-cli", "grok-cli"]) : matrix([]) };
  };
  const result = await reconcileHostCliBridge({
    stackRoot: "D:\\llm\\stack",
    cliBridge: { models: async () => ({ "codex-cli": {}, "claude-cli": {}, "grok-cli": {} }) },
    request,
    runCompose: async (_root, args) => { composeCalls.push(args); applied = true; },
    waitMs: 1000,
  });
  assert.equal(result.changed, true);
  assert.deepEqual(composeCalls, [["up", "-d", "--no-deps", "--force-recreate", "aether-hub"]]);
  assert.deepEqual(result.aliases, ["claude-cli", "codex-cli", "grok-cli"]);
});
