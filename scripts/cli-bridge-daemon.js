#!/usr/bin/env node
"use strict";

// Detects authenticated host CLI subscriptions (Codex CLI, Claude CLI, Grok CLI)
// and exposes them to the aether-hub container over the same host-CLI bridge
// protocol the VSCode extension uses (integrations/vscode/cli-bridge.js).
//
// Without this, host CLI subscriptions were only ever picked up when the
// VSCode extension itself was open and running: `./start.sh` run standalone
// from a terminal never started a bridge server, so LiteLLM/the Hub had no way
// to reach Codex/Claude/Grok even if the user was logged into all three. This
// daemon lets the one-click start.sh path pick them up on its own.

const path = require("path");
const {
  createCliBridge,
} = require(path.join(__dirname, "..", "integrations", "vscode", "cli-bridge.js"));

const token = process.env.AETHER_CLI_BRIDGE_TOKEN;
const port = Number(process.env.AETHER_CLI_BRIDGE_PORT || 8767);
const cwd = process.env.AETHER_STACK_ROOT || process.cwd();

if (!token) {
  console.error("[cli-bridge] AETHER_CLI_BRIDGE_TOKEN is required");
  process.exit(1);
}

const bridge = createCliBridge({ token, port, cwd, host: "0.0.0.0" });

async function main() {
  const { port: boundPort, reused } = await bridge.start();
  if (reused) {
    // A different token owns that server (e.g. the VSCode extension's own
    // SecretStorage-backed bridge) — our freshly generated token would never
    // match it, so the caller must not forward AETHER_CLI_BRIDGE_TOKEN to
    // compose here. Whatever already owns the bridge is responsible for
    // reconciling its own token with the Hub on its own start/refresh cycle.
    console.log(`[cli-bridge] status=reused Another bridge is already listening on ${boundPort}; leaving it in place.`);
    process.exit(0);
    return;
  }
  console.log(`[cli-bridge] status=started Listening on 0.0.0.0:${boundPort}`);
  const models = await bridge.models(true);
  const labels = Object.values(models).map((model) => model.label);
  if (labels.length) {
    console.log(`[cli-bridge] Authenticated host CLI subscriptions detected: ${labels.join(", ")}`);
  } else {
    console.log("[cli-bridge] No authenticated host CLI subscriptions found (Codex CLI, Claude CLI, Grok CLI).");
  }
}

main().catch((error) => {
  console.error(`[cli-bridge] failed to start: ${error.message}`);
  process.exit(1);
});

const shutdown = () => {
  bridge.stop();
  process.exit(0);
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
