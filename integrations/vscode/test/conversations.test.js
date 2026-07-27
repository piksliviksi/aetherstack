"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { capConversations, titleFromTranscript } = require("../conversations");

test("capConversations keeps the 50 most recently updated", () => {
  const items = Array.from({ length: 55 }, (_, i) => ({ id: String(i), updatedAt: i }));
  const capped = capConversations(items);
  assert.equal(capped.length, 50);
  assert.equal(capped[0].id, "54");
  assert.equal(capped.at(-1).id, "5");
});

test("titleFromTranscript derives a title from the first user message", () => {
  const transcript = [{ role: "user", value: "Fix the login race condition please" }];
  assert.equal(titleFromTranscript(transcript), "Fix the login race condition please");
});

test("titleFromTranscript truncates long first messages", () => {
  const transcript = [{ role: "user", value: "x".repeat(80) }];
  assert.equal(titleFromTranscript(transcript).length, 51); // 50 chars + ellipsis
  assert.ok(titleFromTranscript(transcript).endsWith("…"));
});

test("titleFromTranscript falls back when there is no user message yet", () => {
  assert.equal(titleFromTranscript([]), "New conversation");
});
