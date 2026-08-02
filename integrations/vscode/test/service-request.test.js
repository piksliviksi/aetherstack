const assert = require("node:assert/strict");
const test = require("node:test");

const { buildServiceRunBody } = require("../service-request");

test("shared service request builder bounds and normalizes both chat surfaces", () => {
  const history = Array.from({ length: 12 }, (_, index) => ({ role: "user", content: String(index) }));
  const body = buildServiceRunBody({
    goal: "  inspect this  ",
    leanMode: "strict",
    tokenSaver: true,
    history,
    attachments: [{ type: "image" }],
    sessionId: "thread-one",
    memoryContextKb: 2048,
    sequenceMode: "per_request",
  });
  assert.equal(body.goal, "inspect this");
  assert.equal(body.history.length, 8);
  assert.equal(body.history[0].content, "4");
  assert.equal(body.lean_mode, "strict");
  assert.equal(body.token_saver, true);
  assert.equal(body.memory_context_kb, 2048);
  assert.equal(body.sequence_mode, "per_request");
  assert.equal(body.session_id, "thread-one");
});

test("shared service request builder uses product defaults for invalid settings", () => {
  const body = buildServiceRunBody({ memoryContextKb: 999, sequenceMode: "unknown", leanMode: "fast" });
  assert.equal(body.memory_context_kb, 512);
  assert.equal(body.sequence_mode, "sequential_exhaustion");
  assert.equal(body.lean_mode, "balanced");
});
