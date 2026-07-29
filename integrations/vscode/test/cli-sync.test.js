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
    stackRoot: "D:\\workspace\\aetherstack",
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
    stackRoot: "D:\\workspace\\aetherstack",
    cliBridge: { models: async () => ({ "codex-cli": {}, "claude-cli": {}, "grok-cli": {} }) },
    request,
    runCompose: async (_root, args) => { composeCalls.push(args); applied = true; },
    waitMs: 1000,
  });
  assert.equal(result.changed, true);
  assert.deepEqual(composeCalls, [["up", "-d", "--no-deps", "--force-recreate", "aether-hub"]]);
  assert.deepEqual(result.aliases, ["claude-cli", "codex-cli", "grok-cli"]);
});

test("bridge reconciliation applies a refreshed CLI login without restarting Hub", async () => {
  let refreshed = false;
  let forcedDiscovery = false;
  let composeCalls = 0;
  const result = await reconcileHostCliBridge({
    stackRoot: "D:\\workspace\\aetherstack",
    cliBridge: {
      models: async (force) => {
        forcedDiscovery = force;
        return { "codex-cli": {}, "claude-cli": {} };
      },
    },
    request: async (url) => {
      if (url.endsWith("/api/services/refresh")) {
        refreshed = true;
        return { status: 200, body: {} };
      }
      return { status: 200, body: refreshed ? matrix(["codex-cli", "claude-cli"]) : matrix(["codex-cli"]) };
    },
    runCompose: async () => { composeCalls += 1; },
  });
  assert.equal(forcedDiscovery, true);
  assert.equal(result.changed, true);
  assert.equal(result.recreated, false);
  assert.equal(composeCalls, 0);
});

test("bridge reconciliation removes logged-out CLI aliases without restarting Hub", async () => {
  let refreshed = false;
  let composeCalls = 0;
  const result = await reconcileHostCliBridge({
    stackRoot: "D:\\workspace\\aetherstack",
    cliBridge: { models: async () => ({}) },
    request: async (url) => {
      if (url.endsWith("/api/services/refresh")) {
        refreshed = true;
        return { status: 200, body: {} };
      }
      return { status: 200, body: refreshed ? matrix([]) : matrix(["codex-cli"]) };
    },
    runCompose: async () => { composeCalls += 1; },
  });
  assert.equal(result.changed, true);
  assert.deepEqual(result.aliases, []);
  assert.equal(result.recreated, false);
  assert.equal(composeCalls, 0);
});
