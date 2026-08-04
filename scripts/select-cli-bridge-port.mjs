#!/usr/bin/env node
// Single source of truth for host CLI bridge port selection.
// Prints one free loopback port and exits 0, or exits 1 with a message on stderr.
// Used by start.ps1 / start.sh so ladders are not re-copied in shell.

import net from "node:net";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const bridgePath = join(dirname(fileURLToPath(import.meta.url)), "..", "integrations", "vscode", "cli-bridge.js");
const { DEFAULT_PORT, FALLBACK_PORTS } = require(bridgePath);

function configuredPort() {
  const raw = process.env.AETHER_CLI_BRIDGE_PORT;
  if (raw == null || raw === "") return null;
  if (!/^\d+$/.test(String(raw))) return null;
  const port = Number(raw);
  if (port < 1024 || port > 65535) return null;
  return port;
}

function candidates() {
  const preferred = configuredPort();
  const list = [];
  if (preferred != null) list.push(preferred);
  list.push(DEFAULT_PORT, ...FALLBACK_PORTS);
  return [...new Set(list)];
}

function portAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.listen(port, "127.0.0.1", () => {
      server.close(() => resolve(true));
    });
  });
}

async function main() {
  for (const port of candidates()) {
    if (await portAvailable(port)) {
      process.stdout.write(String(port));
      return;
    }
  }
  console.error(
    `no free loopback port for the host CLI bridge (tried ${DEFAULT_PORT}, fallbacks ${FALLBACK_PORTS.join(",")})`,
  );
  process.exit(1);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
