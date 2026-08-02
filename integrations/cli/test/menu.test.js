const assert = require("node:assert/strict");
const test = require("node:test");

const { formatEvent } = require("../lib/menu");

test("formatEvent renders a status event's phase and label", () => {
  assert.equal(formatEvent({ type: "status", phase: "lead", label: "Lead…" }), "… lead — Lead…");
});

test("formatEvent falls back to a generic label when nothing else is set", () => {
  assert.equal(formatEvent({ type: "status" }), "… working");
});

test("formatEvent returns null for non-status events (caller decides how to show them)", () => {
  assert.equal(formatEvent({ type: "delta", text: "x" }), null);
  assert.equal(formatEvent({ type: "done" }), null);
});
