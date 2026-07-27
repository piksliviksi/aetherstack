"use strict";

const MAX_CONVERSATIONS = 50;
const TITLE_MAX = 50;

function capConversations(items) {
  return [...items].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CONVERSATIONS);
}

function titleFromTranscript(transcript) {
  const first = (transcript || []).find((item) => item.role === "user");
  if (!first || !first.value) return "New conversation";
  const value = String(first.value).trim();
  return value.length > TITLE_MAX ? `${value.slice(0, TITLE_MAX)}…` : value;
}

module.exports = { MAX_CONVERSATIONS, capConversations, titleFromTranscript };
