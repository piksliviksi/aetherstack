"use strict";

const HUB_MATRIX_URL = "http://127.0.0.1:8766/api/matrix";
const HUB_REFRESH_URL = "http://127.0.0.1:8766/api/services/refresh";

function availableHostCliAliases(matrix) {
  return Object.entries((matrix && matrix.models) || {})
    .filter(([, model]) => model && model.available === true && model.executor === "host_cli")
    .map(([alias]) => alias)
    .sort();
}

function sameAliases(left, right) {
  return left.length === right.length && left.every((alias, index) => alias === right[index]);
}

async function reconcileHostCliBridge({ stackRoot, cliBridge, request, runCompose, waitMs = 30_000 }) {
  if (!stackRoot) return { changed: false, reason: "stack root unavailable", aliases: [] };
  const discovered = await cliBridge.models(true);
  const aliases = Object.keys(discovered || {}).sort();

  let matrixResponse;
  try { matrixResponse = await request(HUB_MATRIX_URL, { timeoutMs: 3000 }); }
  catch { return { changed: false, reason: "Hub is offline; bridge will be applied on start", aliases }; }
  if (matrixResponse.status !== 200) {
    return { changed: false, reason: "Hub is offline; bridge will be applied on start", aliases };
  }
  const current = availableHostCliAliases(matrixResponse.body);
  if (sameAliases(aliases, current)) {
    return { changed: false, reason: "Hub bridge already current", aliases };
  }

  // Login/install changes do not normally require a container recreation: the
  // running Hub can re-probe the same protected bridge. Try that first so a
  // normal Refresh can add and remove CLI aliases without disrupting Chat.
  try {
    const refreshed = await request(HUB_REFRESH_URL, { method: "POST", body: {}, timeoutMs: 30_000 });
    if (refreshed.status === 200) {
      const verified = await request(HUB_MATRIX_URL, { timeoutMs: 5000 });
      const verifiedAliases = availableHostCliAliases(verified.body);
      if (sameAliases(aliases, verifiedAliases)) {
        return { changed: true, reason: "Hub re-probed authenticated host CLIs", aliases, applied: verifiedAliases, recreated: false };
      }
    }
  } catch {
    // A stale/missing bridge token requires recreating only the Hub below.
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
  if (!sameAliases(aliases, verifiedAliases)) {
    throw new Error("Hub restarted but did not accept the authenticated host CLI bridge");
  }
  return { changed: true, reason: "Hub bridge environment refreshed", aliases, applied: verifiedAliases, recreated: true };
}

module.exports = { availableHostCliAliases, reconcileHostCliBridge, sameAliases };
