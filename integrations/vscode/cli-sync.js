"use strict";

const HUB_MATRIX_URL = "http://127.0.0.1:8766/api/matrix";
const HUB_REFRESH_URL = "http://127.0.0.1:8766/api/services/refresh";

function availableHostCliAliases(matrix) {
  return Object.entries((matrix && matrix.models) || {})
    .filter(([, model]) => model && model.available === true && model.executor === "host_cli")
    .map(([alias]) => alias)
    .sort();
}

async function reconcileHostCliBridge({ stackRoot, cliBridge, request, runCompose, waitMs = 30_000 }) {
  if (!stackRoot) return { changed: false, reason: "stack root unavailable", aliases: [] };
  const discovered = await cliBridge.models();
  const aliases = Object.keys(discovered || {}).sort();
  if (!aliases.length) return { changed: false, reason: "no authenticated host CLIs", aliases };

  let matrixResponse;
  try { matrixResponse = await request(HUB_MATRIX_URL, { timeoutMs: 3000 }); }
  catch { return { changed: false, reason: "Hub is offline; bridge will be applied on start", aliases }; }
  if (matrixResponse.status !== 200) {
    return { changed: false, reason: "Hub is offline; bridge will be applied on start", aliases };
  }
  const current = availableHostCliAliases(matrixResponse.body);
  if (aliases.every((alias) => current.includes(alias))) {
    return { changed: false, reason: "Hub bridge already current", aliases };
  }

  await runCompose(
    stackRoot,
    ["up", "-d", "--no-deps", "--force-recreate", "aether-hub"],
    { timeoutMs: 2 * 60_000 }
  );
  const deadline = Date.now() + waitMs;
  let refreshed;
  while (Date.now() < deadline) {
    try {
      const health = await request("http://127.0.0.1:8766/api/health", { timeoutMs: 2000 });
      if (health.status === 200 && health.body && health.body.ok) {
        refreshed = await request(HUB_REFRESH_URL, { method: "POST", body: {}, timeoutMs: 30_000 });
        break;
      }
    } catch {
      // The Hub closes connections briefly while its container is replaced.
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (!refreshed || refreshed.status !== 200) {
    throw new Error("Hub did not become ready after applying the host CLI bridge");
  }
  // /api/services does not expose full model metadata; verify through /api/matrix.
  const verified = await request(HUB_MATRIX_URL, { timeoutMs: 5000 });
  const verifiedAliases = availableHostCliAliases(verified.body);
  if (!aliases.every((alias) => verifiedAliases.includes(alias))) {
    throw new Error("Hub restarted but did not accept the authenticated host CLI bridge");
  }
  return { changed: true, reason: "Hub bridge environment refreshed", aliases, applied: verifiedAliases };
}

module.exports = { availableHostCliAliases, reconcileHostCliBridge };
