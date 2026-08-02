const assert = require("node:assert/strict");
const test = require("node:test");

const { parseChatInput, commandHelp } = require("../chat-routing");

const serviceIds = [
  "research", "planning", "service-design", "ui-design", "frontend", "backend",
  "coding", "testing", "bugfixing", "whitehat-pentesting", "polishing", "technical-writing",
];

test("natural chat stays on auto (direct models + memory) by default", () => {
  assert.deepEqual(parseChatInput("Fix the broken login", "auto", serviceIds), {
    action: "run",
    serviceId: "auto",
    prompt: "Fix the broken login",
  });
});

test("slash commands select or run dynamic service presets", () => {
  assert.deepEqual(parseChatInput("/research", "auto", serviceIds), {
    action: "select",
    serviceId: "research",
  });
  assert.deepEqual(parseChatInput("/plan map the release", "auto", serviceIds), {
    action: "run",
    serviceId: "planning",
    prompt: "map the release",
    command: true,
  });
  assert.deepEqual(parseChatInput("/preset bugfix reproduce it", "auto", serviceIds), {
    action: "run",
    serviceId: "bugfixing",
    prompt: "reproduce it",
    command: true,
  });
});

test("/clear archives and clears, optionally forcing past open tasks", () => {
  assert.deepEqual(parseChatInput("/clear", "auto", serviceIds), { action: "clear", force: false });
  assert.deepEqual(parseChatInput("/clear force", "auto", serviceIds), { action: "clear", force: true });
});

test("unknown slash commands fail closed with discoverable help", () => {
  const result = parseChatInput("/telepathy do it", "auto", serviceIds);
  assert.equal(result.action, "error");
  assert.match(result.message, /\/help/);
  assert.match(commandHelp(serviceIds.map((id) => ({ id }))), /\/auto/);
});
