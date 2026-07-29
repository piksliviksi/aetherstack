const assert = require("node:assert/strict");
const test = require("node:test");

const { createChatRequestHandler } = require("../chat-participant");

function fakeStream() {
  const markdown = [];
  const progress = [];
  const buttons = [];
  return {
    markdown: (value) => markdown.push(value),
    progress: (value) => progress.push(value),
    button: (value) => buttons.push(value),
    get: () => ({ markdown, progress, buttons }),
  };
}

function fakeHubChat({ services = [{ id: "coding", label: "Coding", summary: "Implement things" }], run } = {}) {
  return {
    services,
    history: [],
    loadServices: async () => {},
    hubRequest: run || (async () => ({ answer: "done" })),
  };
}

const token = { isCancellationRequested: false };

test("routes a natural-language prompt through auto classification", async () => {
  const calls = [];
  const hubChat = fakeHubChat({
    run: async (pathname, options) => {
      calls.push(pathname);
      if (pathname === "/api/services/classify") return { service_id: "coding", label: "Coding", confidence: "high" };
      return { answer: "Implemented the fix.", agents: [{ model: "gpt-4.1" }] };
    },
  });
  const handler = createChatRequestHandler(hubChat);
  const stream = fakeStream();
  await handler({ prompt: "fix the bug", command: undefined }, {}, stream, token);

  assert.deepEqual(calls, ["/api/services/classify", "/api/services/coding/run"]);
  const { markdown } = stream.get();
  assert.ok(markdown.some((m) => m.includes("Coding")), "should announce the resolved preset");
  assert.ok(markdown.some((m) => m.includes("Implemented the fix.")), "should stream the answer");
  assert.ok(markdown.some((m) => m.includes("gpt-4.1")), "should surface the resolved team");
});

test("slash command runs the named preset without classification", async () => {
  const calls = [];
  const hubChat = fakeHubChat({
    run: async (pathname) => {
      calls.push(pathname);
      return { answer: "Reviewed." };
    },
  });
  const handler = createChatRequestHandler(hubChat);
  const stream = fakeStream();
  await handler({ prompt: "review the diff", command: "code" }, {}, stream, token);

  assert.deepEqual(calls, ["/api/services/coding/run"]);
});

test("unknown slash command fails closed with a message, not a crash", async () => {
  const hubChat = fakeHubChat();
  const handler = createChatRequestHandler(hubChat);
  const stream = fakeStream();
  await handler({ prompt: "do it", command: "telepathy" }, {}, stream, token);

  const { markdown } = stream.get();
  assert.ok(markdown.some((m) => /help/i.test(m)));
});

test("/help lists commands without calling the Hub", async () => {
  const hubChat = fakeHubChat({
    run: async () => { throw new Error("should not be called"); },
  });
  const handler = createChatRequestHandler(hubChat);
  const stream = fakeStream();
  await handler({ prompt: "", command: "help" }, {}, stream, token);

  const { markdown } = stream.get();
  assert.ok(markdown.some((m) => m.includes("AetherStack commands")));
});
