"use strict";

const MEMORY_CONTEXT_OPTIONS = new Set([256, 512, 1024, 2048]);
const SEQUENCE_MODES = new Set(["sequential_exhaustion", "per_request"]);
const LEAN_MODES = new Set(["off", "balanced", "strict"]);

function buildServiceRunBody(options = {}) {
  const memoryContextKb = Number(options.memoryContextKb);
  return {
    goal: String(options.goal || "").trim(),
    lean_mode: LEAN_MODES.has(options.leanMode) ? options.leanMode : "balanced",
    token_saver: Boolean(options.tokenSaver),
    history: (Array.isArray(options.history) ? options.history : []).slice(-8),
    attachments: Array.isArray(options.attachments) ? options.attachments : [],
    session_id: String(options.sessionId || "vscode-chat"),
    memory_context_kb: MEMORY_CONTEXT_OPTIONS.has(memoryContextKb) ? memoryContextKb : 512,
    sequence_mode: SEQUENCE_MODES.has(options.sequenceMode)
      ? options.sequenceMode
      : "sequential_exhaustion",
  };
}

module.exports = { buildServiceRunBody };
