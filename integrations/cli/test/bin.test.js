const assert = require("node:assert/strict");
const test = require("node:test");

const { parseArgs, main } = require("../bin/aetherstack");
const hubClient = require("../lib/hub-client");
const commands = require("../lib/commands");

test("parseArgs separates flags from positional arguments", () => {
  const { args, flags } = parseArgs(["run", "coding", "fix", "the", "bug", "--json", "--hub", "http://x:1"]);
  assert.deepEqual(args, ["run", "coding", "fix", "the", "bug"]);
  assert.equal(flags.json, true);
  assert.equal(flags.hub, "http://x:1");
});

test("parseArgs recognizes --edit and -h/--help", () => {
  assert.equal(parseArgs(["build", "--edit", "coding"]).flags.edit, "coding");
  assert.equal(parseArgs(["-h"]).flags.help, true);
  assert.equal(parseArgs(["--help"]).flags.help, true);
});

function withMockedHubClient(overrides, fn) {
  const originals = {};
  for (const key of Object.keys(overrides)) {
    originals[key] = hubClient[key];
    hubClient[key] = overrides[key];
  }
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      for (const key of Object.keys(originals)) hubClient[key] = originals[key];
    });
}

test("`aetherstack list` prints every preset the hub reports", async () => {
  const lines = [];
  const origLog = console.log;
  console.log = (line) => lines.push(line);
  try {
    await withMockedHubClient(
      { listServices: async () => [{ id: "coding", label: "Coding", summary: "Write code" }] },
      () => main(["list"])
    );
  } finally {
    console.log = origLog;
  }
  assert.equal(lines.length, 1);
  assert.match(lines[0], /^coding\tCoding\tWrite code$/);
});

test("`aetherstack tree <id>` errors clearly when the preset is unknown", async () => {
  await withMockedHubClient({ getServiceGraph: async () => ({ error: "unknown service: nope" }) }, async () => {
    await assert.rejects(main(["tree", "nope"]), /unknown service/);
  });
});

test("`aetherstack cancel` reports whether the run was actually found", async () => {
  const lines = [];
  const origLog = console.log;
  console.log = (line) => lines.push(line);
  try {
    await withMockedHubClient({ cancelRun: async (id) => ({ ok: true, run_id: id, found: false }) }, () =>
      main(["cancel", "run-xyz"])
    );
  } finally {
    console.log = origLog;
  }
  assert.match(lines[0], /was not an active run/);
});

test("missing required arguments raise a usage error instead of crashing", async () => {
  await assert.rejects(main(["tree"]), /usage: aetherstack tree/);
  await assert.rejects(main(["run"]), /usage: aetherstack run/);
  await assert.rejects(main(["export"]), /usage: aetherstack export/);
  await assert.rejects(main(["import"]), /usage: aetherstack import/);
  await assert.rejects(main(["cancel"]), /usage: aetherstack cancel/);
});

test("an unknown command exits non-zero without throwing", async () => {
  const code = await main(["bogus-command"]);
  assert.equal(code, 1);
});

function withMockedCommands(overrides, fn) {
  const originals = {};
  for (const key of Object.keys(overrides)) {
    originals[key] = commands[key];
    commands[key] = overrides[key];
  }
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      for (const key of Object.keys(originals)) commands[key] = originals[key];
    });
}

test("`aetherstack up` starts the stack found from --cwd and reports where", async () => {
  const lines = [];
  const origLog = console.log;
  console.log = (line) => lines.push(line);
  try {
    await withMockedCommands({ startStack: async () => "/my/checkout" }, () => main(["up", "--cwd", "/my/checkout"]));
  } finally {
    console.log = origLog;
  }
  assert.match(lines[0], /AetherStack is up \(\/my\/checkout\)/);
});

test("`aetherstack down` reports the stack it stopped", async () => {
  const lines = [];
  const origLog = console.log;
  console.log = (line) => lines.push(line);
  try {
    await withMockedCommands({ stopStack: async () => "/my/checkout" }, () => main(["down"]));
  } finally {
    console.log = origLog;
  }
  assert.match(lines[0], /AetherStack stopped \(\/my\/checkout\)/);
});

test("`aetherstack status` exits non-zero when a service is down", async () => {
  const origLog = console.log;
  console.log = () => {};
  let code;
  try {
    code = await withMockedCommands(
      {
        stackStatus: async () => ({
          root: "/my/checkout",
          docker: { installed: true, running: true },
          services: [{ id: "hub", ok: true }, { id: "litellm", ok: false, error: "connection refused" }],
        }),
      },
      () => main(["status"])
    );
  } finally {
    console.log = origLog;
  }
  assert.equal(code, 1);
});

test("`aetherstack status` exits zero when every service is healthy", async () => {
  const origLog = console.log;
  console.log = () => {};
  let code;
  try {
    code = await withMockedCommands(
      {
        stackStatus: async () => ({
          root: "/my/checkout",
          docker: { installed: true, running: true },
          services: [{ id: "hub", ok: true }],
        }),
      },
      () => main(["status"])
    );
  } finally {
    console.log = origLog;
  }
  assert.equal(code, 0);
});
