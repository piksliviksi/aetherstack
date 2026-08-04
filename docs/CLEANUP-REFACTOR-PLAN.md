# AetherStack cleanup / refactor / verify plan

## Origin

Last Claude Code session (`2489b12d…`, not the earlier `aec32531…` title-only list entry):

| # | User request |
|---|--------------|
| … | start failed, Grok CLI, chat UX, mistral-vibe concepts, commit/push |
| **Last CODE request** | **“clean the code, refactor, test, verify and look structure-wise do we have overlapping features, gaps, etc. make a plan on how to fix everything.”** |

Claude invoked **ponytail-audit**, gathered structure findings, then hit **session limit** mid-pass. **No plan document was written.** Work stopped at the Windows CLI-bridge port ladder + duplicate `Set-DotEnvValue` notes.

This plan completes that interrupted audit and turns it into ordered fix work.

---

## Current tree (what exists)

| Area | Role |
|------|------|
| `aether-hub/` | Control plane API (services, matrix, graph, memory, auth) |
| `integrations/vscode/` | Primary IDE surface: chat, control center, host CLI bridge |
| `integrations/cli/` | Terminal CLI talking to Hub |
| `scripts/` | Start helpers, packaging, verify, GPU/WSL tooling |
| `start.ps1` / `start.sh` | One-click bootstrap (parity incomplete) |
| `docker-compose*.yml` | Runtime |
| `extension/` | **Docker Desktop Extension** (separate product surface; **drifted** configs) |
| `aether-hub/static/` | Hub UIs: `simple.html`, `graph.html`, `gdpr.html` |
| `project-engine/` | Separate project tooling UI |
| `combos/`, `pipelines/` | Policy artifacts |
| `distro/` | Edition packaging (desktop / team / cloud) |
| `tests/` + `aether-hub/test_*.py` + `integrations/*/test/` | Gates |

**Chat / UI surfaces (overlap risk):** VS Code `chat.html`, Hub `simple.html`, Hub `graph.html`, Open WebUI, Docker Extension mini-UI, project-engine UI. Product intent: VS Code chat + Hub simple for normal work; graph = power; Open WebUI optional — keep that hierarchy, don’t merge UIs blindly.

---

## Structural findings (verified)

### P0 — Correctness / ops pain

| ID | Finding | Evidence | Status |
|----|---------|----------|--------|
| P0-1 | CLI bridge port ladder `8767–8777` hits Windows Hyper-V exclusion **8768–8867** (EACCES) | Measured on this host; Claude hit live | **Done** (`705c0cf`, `56956c2`) |
| P0-2 | Two bridges (extension SecretStorage token vs start-script daemon) fight over port/token; Hub can lose host CLIs | Session log: foreign token on 8767 | **Documented + free-port** (`docs/VSCODE.md`, free-port fallback). Full single-process merge deferred. |
| P0-3 | Docker Desktop Extension ships **stale** `extension/litellm_config.yaml` | Root **90** models vs extension **89**; missing **`openai-embed`** | **Done** (`e712f12` + verify-release gate) |
| P0-4 | `extension/docker-compose.yaml` is a thin **fork** of root compose (71 vs 261 lines) | Drift hazard for every release | Open (intentional slim compose; catalog gate covers models) |

### P1 — Duplication / single source of truth

| ID | Finding | Detail |
|----|---------|--------|
| P1-1 | Port ladders triplicated | Ollama probe + bridge fallbacks in `start.ps1`, `start.sh`, `cli-bridge.js` (post-fix still 3 lists) |
| P1-2 | Duplicate `Set-DotEnvValue` | Claude found lines 60+182; **already removed** in working tree |
| P1-3 | Start script feature parity | `start.sh`: managed bridge lifecycle, macOS Ollama, `select_cli_bridge_port`. `start.ps1`: different shape, historically missing free-port selection |
| P1-4 | Env helpers dual | `Set-DotEnvValue` / `set_env_value` — expected dual OS, but behavior should match (UTF-8 no BOM, last-wins, etc.) |
| P1-5 | Host CLI discovery single lib | Good: `cli-bridge-daemon.js` reuses `integrations/vscode/cli-bridge.js`. Keep that; don’t reimplement in `integrations/cli` |

### P2 — Dead / unreferenced / noise

| ID | Finding | Detail |
|----|---------|--------|
| P2-1 | ~9 unreferenced scripts (~53 KB) | e.g. `audit-service-presets.py`, `browser-smoke.mjs`, `e2e-radio-stone-graph-test.py`, `scan-project-ai.{ps1,sh}`, WSL ollama test shells — **0 refs outside `scripts/`** |
| P2-2 | Local leftover `.aetherstack/activity_words.json` | Feature removed; only CHANGELOG memory + untracked runtime copy |
| P2-3 | No root `package.json` | Tests/release live under `integrations/vscode` (`release:check`). Fine if intentional; document entrypoint |
| P2-4 | Giant modules | `server.py` ~119KB, `services.py` ~113KB, `extension.js` ~91KB, `graph.html` ~82KB, `chat.html` ~62KB — hard to review; split only where seams are clear |

### P3 — Gaps (features / gates)

| ID | Gap |
|----|-----|
| P3-1 | No automated tests for `start.ps1` / `start.sh` logic (only string asserts in activation tests) |
| P3-2 | Chat UI (`chat.html`) thin automated coverage (inline JS syntax checks ad hoc) |
| P3-3 | Release path does not verify Docker Extension configs stay in sync with root |
| P3-4 | Product docs claim free-port bridge handoff; code was incomplete until current uncommitted patch |
| P3-5 | Multiple scan paths: `scan-system.ps1/sh`, Hub `discover.py`, matrix — complementary but undocumented ownership |

---

## Design decisions (proposed)

1. **Bridge ownership contract**  
   - Prefer **one** host bridge process.  
   - If extension already owns a port with a valid token → start scripts **do not** mint a conflicting token for compose; leave Hub unconfigured for CLIs until extension reconciles (current intentional path).  
   - If default port busy with **foreign** token → bind free port outside Hyper-V band, export `AETHER_CLI_BRIDGE_URL/PORT/TOKEN` to compose.  
   - **Single source of port candidates:** export from `cli-bridge.js` (`DEFAULT_PORT`, `FALLBACK_PORTS`); start scripts either call a tiny Node helper or share a `scripts/ports.json` generated/checked in CI.

2. **Docker Desktop Extension configs**  
   - Stop hand-editing forks. Prefer generate-from-root or CI diff gate (`extension/litellm_config.yaml` must match root allowlist / full copy policy).  
   - Short term: sync missing `openai-embed` and add `verify-release` check.

3. **Unreferenced scripts**  
   - For each: **wire into docs/`release:check`**, move to `scripts/archive/`, or delete. No silent orphans.

4. **UI surfaces**  
   - No merge of `chat.html` / `simple.html` / `graph.html` in this cleanup.  
   - Document matrix: who is primary, who is optional. Remove only true dead UI (none proven yet except extension dashboard thinness).

5. **Big-file splits**  
   - Defer bulk splits of `services.py` / `extension.js` until after P0/P1.  
   - Prefer extract-when-touching (e.g. bridge env handoff already isolated).

---

## Implementation plan (PR-sized)

### PR 0 — Land current bridge fixes (uncommitted)

**Scope:** Working tree already has:
- `Select-CliBridgePort` / fixed `select_cli_bridge_port` (safe ladder)
- Single `Set-DotEnvValue`
- `cli-bridge.js` free-port fallback + `extension.js` real URL/port env
- Tests in `cli-bridge.test.js` / `activation.test.js`

**Verify:**
```text
cd integrations/vscode && node --test test/*.test.js
# hub tests if env ready:
# pytest aether-hub tests -q
```

**Do not** mix with larger refactors.

---

### PR 1 — Single source of truth for bridge ports + ownership docs

**Files:** `integrations/vscode/cli-bridge.js`, `scripts/cli-bridge-daemon.js`, optional `scripts/select-cli-bridge-port.mjs`, `start.ps1`, `start.sh`, `docs/VSCODE.md` or `AGENT-MEMORY` note, tests.

**Work:**
1. Keep `DEFAULT_PORT` + `FALLBACK_PORTS` only in JS.
2. Add tiny Node CLI: `node scripts/select-cli-bridge-port.mjs` prints free port (used by both start scripts) **or** share `ports.json` read by all three.
3. Document two-bridge / token rules in one short doc section.
4. Assert start scripts do **not** hardcode `8768 8769…8777`.

**Verify:** existing cli-bridge tests + activation string asserts + manual bind on Windows exclusion range.

---

### PR 2 — Docker Extension drift gate

**Files:** `extension/litellm_config.yaml`, maybe `extension/docker-compose.yaml`, `scripts/verify-release.mjs`.

**Work:**
1. Sync missing model(s) (`openai-embed`).
2. Add verify step: model_name sets equal (or extension ⊆ root with explicit allowlist).
3. Decide compose strategy: generate subset vs document intentional slim compose.

**Verify:** `npm run verify:release` from `integrations/vscode`.

---

### PR 3 — Script inventory cleanup

**Work:**
1. Table each unreferenced script → keep+wire / archive / delete.
2. Wire keepers into README or `release:check` / docs.
3. Delete proven orphans with one-line rationale in commit body.
4. Ignore or clean local `.aetherstack/activity_words.json` (not tracked).

**Verify:** `git grep` for each remaining script name; docs links resolve.

---

### PR 4 — Start script parity checklist (behavior, not rewrite)

**Work:** Shared behavior checklist implemented on both OSes:
- [ ] Docker ready / auto-start
- [ ] Master key ensure
- [ ] Host Ollama find + alternate ports
- [ ] Bundled Ollama fallback port select
- [ ] CLI bridge free port + env export to compose
- [ ] System scan publish
- [ ] Wait core services

Add a **parity test** that parses both scripts for required function/command names (extend `activation.test.js` pattern) rather than a full PowerShell runner in CI.

**Verify:** activation + dry-run parse of `start.ps1`; `bash -n start.sh`.

---

### PR 5 — Test & verify matrix (no feature work)

| Gate | Command | When |
|------|---------|------|
| VS Code unit | `cd integrations/vscode && npm test` | Every PR |
| CLI unit | `cd integrations/cli && npm test` (if package has tests) | PR touching CLI |
| Hub/Python | `pytest aether-hub tests -q` | PR touching hub/tests |
| Release | `cd integrations/vscode && npm run release:check` | Pre-release / PR2 |
| One-click (manual/optional) | `node scripts/verify-one-click.mjs` | Windows smoke |
| Start syntax | parse `start.ps1`; `bash -n start.sh` | PR0–4 |

Baseline **measured 2026-08-04**: **Python 242 passed**, **JS 89 tests / 89 pass
/ 0 fail** (`npm test`, exit 0), `start.ps1` parses clean, `bash -n start.sh`
clean. Treat any regression as a blocker.

> The old "run each JS file separately, `hubchat.test.js` hangs" workaround is
> **obsolete** — `npm test` completes normally. Looping per file and skipping
> that file under-reports the suite.

> **These gates have only ever run locally.** Every GitHub Actions run fails in
> 3–12s with *"The job was not started because your account is locked due to a
> billing issue"* — jobs never start, so `ci.yml` has validated nothing on any
> commit. All green results are one machine / one OS / one Node / one Python.
> The cross-platform matrix in `ci.yml` is unverified until billing is cleared.

---

### Later (not in first cleanup wave)

- Split `services.py` / `extension.js` by domain (auth, services run, chat host).
- Unify scan/discover docs (ownership diagram only unless bugs found).
- Open WebUI proxy vs Hub simple: product decision only if users confuse them.

---

## Overlap / gap summary (structure)

```text
                    ┌─────────────────────┐
  User surfaces     │ VS Code chat (primary)│
                    │ Hub simple / graph    │
                    │ Open WebUI (optional) │
                    │ Docker Ext UI (thin)  │
                    │ integrations/cli      │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
  Control plane     │ aether-hub :8766      │
                    │ LiteLLM :4000         │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
  Model backends    │ Cloud keys (multi)    │
                    │ Host Ollama           │
                    │ Host CLI bridge ──────┼── extension OR start daemon
                    │ Bundled Ollama CPU    │   (two owners — P0-2)
                    └─────────────────────┘
```

| Overlap | Action |
|---------|--------|
| Extension litellm vs root | Sync + CI gate |
| Extension compose vs root | Slim intentional + verify or generate |
| Bridge in extension vs start | Ownership contract + free port (PR0–1) |
| Port ladders ×3 | One source (PR1) |
| Many UIs | Document roles; no merge |
| Unreferenced scripts | Inventory PR3 |
| Start.ps1 vs start.sh | Parity checklist PR4 |

| Gap | Action |
|-----|--------|
| Windows reserved ports | Done in PR0; harden in PR1 |
| Release doesn’t catch extension drift | PR2 |
| Start scripts untested | PR4 lightweight asserts |
| Plan never written from last session | **This document** |

---

## Execution order

1. **PR0** land + test + push bridge fixes (unblocks Windows).  
2. **PR1** port SSoT + bridge ownership docs.  
3. **PR2** extension config drift.  
4. **PR3** script cleanup.  
5. **PR4** start parity asserts.  
6. Full `release:check` when cutting a version.

---

## Out of scope for “fix everything” wave

- New chat features / mistral-vibe-style redesign (already partially shipped in `e43988a`).  
- Rewriting Hub in another language.  
- Merging all UIs into one SPA.  
- “Elias Thorn” (unrelated stray message after chat commit).

---

## Success criteria

- [x] No hard-coded CLI bridge ports in the Hyper-V exclusion band. — `activation.test.js` asserts neither ladder reappears.
- [x] Extension model catalog matches root (or CI fails). — root 90 / extension 90, diff 0; `verify-release.mjs` gates it.
- [x] Zero unreferenced scripts without explicit archive/docs home. — `scripts/README.md` lists all 9 as manual/lab tools with a sunset rule.
- [x] Documented single primary chat surface + optional surfaces. — "Current tree" + overlap diagram in this document.
- [x] `npm test` (vscode) + `pytest` green; start scripts parse clean. — measured 2026-08-04, see PR5.
- [x] `release:check` green before next tagged release. — run locally 2026-08-04, **exit 0** (VSIX `aetherstack-0.3.23.vsix`, runtime `aetherstack-runtime-0.3.23.tar.gz`, 148 tracked files, privacy/licence checks passed). **CI cannot confirm this** while the Actions billing lock stands, so re-run it locally before every tag.

### PR3 / PR4 status (verified 2026-08-04)

- **PR3 — done via documentation, not deletion.** The plan offered
  wire/archive/delete; `scripts/README.md` takes a fourth route: every orphan is
  listed with intent plus "zero maintainers and zero docs links for a release
  cycle → delete". No silent orphans remain, which was the actual goal.
- **PR4 — done.** `activation.test.js` implements the parity checklist as
  marker patterns over both start scripts. One asymmetry fixed on 2026-08-04:
  the shell list asserted no core-service readiness wait even though `start.sh`
  performs one, so deleting that wait would not have failed the checklist.
