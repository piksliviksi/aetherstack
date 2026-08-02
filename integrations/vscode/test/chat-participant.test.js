const assert = require("node:assert/strict");
const test = require("node:test");

const { createChatRequestHandler, historyFromContext, selectedServiceFromContext } = require("../chat-participant");
const { buildServiceRunBody } = require("../service-request");

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
    buildRunBody: (options) => buildServiceRunBody({
      ...options,
      memoryContextKb: 1024,
      sequenceMode: "per_request",
    }),
    hubRequest: run || (async () => ({ answer: "done" })),
  };
}

const token = { isCancellationRequested: false };

test("a bare prompt goes straight to Auto, with no classify round-trip", async () => {
  const calls = [];
  const hubChat = fakeHubChat({
    run: async (pathname, options) => {
      calls.push(pathname);
      return { answer: "Implemented the fix.", agents: [{ model: "gpt-4.1" }] };
    },
  });
  const handler = createChatRequestHandler(hubChat);
  const stream = fakeStream();
  await handler({ prompt: "fix the bug", command: undefined }, {}, stream, token);

  // Auto is a direct pass-through: no preset classification step.
  assert.deepEqual(calls, ["/api/services/auto/run"]);
  const { markdown } = stream.get();
  assert.ok(markdown.some((m) => m.includes("Auto")), "should announce Auto");
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

test("native Chat visibly marks degraded preset answers", async () => {
  const hubChat = fakeHubChat({
    run: async () => ({ answer: "Partial answer.", degraded: true, degraded_reasons: ["secret raw error"] }),
  });
  const stream = fakeStream();
  await createChatRequestHandler(hubChat)(
    { prompt: "review", command: "code" },
    {},
    stream,
    token,
  );
  const text = stream.get().markdown.join("\n");
  assert.match(text, /reduced independent verification/i);
  assert.doesNotMatch(text, /secret raw error/i);
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

test("native Chat context is thread-local and remembers an explicit preset", async () => {
  const calls = [];
  const hubChat = fakeHubChat({
    services: [
      { id: "coding", label: "Coding", summary: "Implement things" },
      { id: "research", label: "Research", summary: "Find evidence" },
    ],
    run: async (pathname, options) => {
      calls.push({ pathname, body: options.body });
      return { answer: "done" };
    },
  });
  const handler = createChatRequestHandler(hubChat);

  const codingContext = {
    history: [
      { command: "code", prompt: "" },
      { prompt: "first task" },
      { response: [{ value: { value: "first answer" } }] },
    ],
  };
  await handler({ prompt: "continue it", command: undefined }, codingContext, fakeStream(), token);
  assert.equal(calls[0].pathname, "/api/services/coding/run");
  assert.deepEqual(calls[0].body.history.slice(-2), [
    { role: "user", content: "first task" },
    { role: "assistant", content: "first answer" },
  ]);

  // A fresh thread carries no preset, so it falls back to Auto rather than
  // inheriting the other thread's "coding" selection.
  await handler({ prompt: "investigate this", command: undefined }, { history: [] }, fakeStream(), token);
  assert.equal(calls[1].pathname, "/api/services/auto/run");
  assert.deepEqual(calls[1].body.history, []);
  assert.equal(calls[1].body.memory_context_kb, 1024);
  assert.equal(calls[1].body.sequence_mode, "per_request");
  assert.equal(selectedServiceFromContext(codingContext, ["coding", "research"]), "coding");
  assert.deepEqual(historyFromContext({ history: [] }), []);
});

test("native Chat cancellation aborts the in-flight Hub request", async () => {
  let cancel;
  let observedSignal;
  const cancellationToken = {
    isCancellationRequested: false,
    onCancellationRequested: (callback) => {
      cancel = callback;
      return { dispose() {} };
    },
  };
  const hubChat = fakeHubChat({
    run: async (_pathname, options) => {
      observedSignal = options.signal;
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("cancelled");
          error.name = "AbortError";
          reject(error);
        }, { once: true });
      });
    },
  });
  const stream = fakeStream();
  const running = createChatRequestHandler(hubChat)(
    { prompt: "do something long", command: "code" },
    { history: [] },
    stream,
    cancellationToken,
  );
  await new Promise((resolve) => setImmediate(resolve));
  cancel();
  await running;
  assert.equal(observedSignal.aborted, true);
  assert.ok(stream.get().markdown.some((value) => /cancelled/i.test(value)));
});
