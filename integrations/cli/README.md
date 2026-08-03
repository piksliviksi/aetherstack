# AetherStack CLI

A terminal client for AetherStack Hub — the text equivalent of the web Hub and
node-graph canvas. No VS Code required: this alone can start, use, and stop a
full AetherStack checkout, over plain HTTP/SSE for the Hub API (the same one
`graph.html`/`chat.html`/the VS Code extension use) and Docker Compose
directly for the stack lifecycle. No dependencies, no build step.

## Install

Requires Node 18+, Docker Desktop/Engine, and a clone of this repository
(`git clone` it — that's the entire prerequisite; VS Code is not needed for
any of this).

```bash
cd integrations/cli
npm link          # installs the `aetherstack` command globally from this checkout
```

Or run it directly without installing:

```bash
node integrations/cli/bin/aetherstack.js
```

Then start the stack and use it, entirely from the terminal:

```bash
aetherstack up        # first run pulls images/models — same as ./start.sh
aetherstack status     # confirm Docker + every service is healthy
aetherstack run coding "explain what this repo does"
aetherstack down       # stop everything when you're done
```

`up`/`down`/`status` auto-detect the checkout from the current directory
(walking up for `docker-compose.yml`); pass `--cwd <path>` to target a
different one. The Hub itself defaults to `http://127.0.0.1:8766` — point
elsewhere with `--hub <url>` / `AETHERSTACK_HUB_URL` for `list`/`tree`/`run`/
etc. once it's up.

## Interactive menu

Run with no arguments for a numbered text menu covering everything the web
Hub does: list presets, view a preset's node tree as text, run a preset or
Auto (with live streaming status/output, Ctrl+C to cancel), build a new
preset or edit an existing one in `$EDITOR`, and export/import presets as
YAML.

```
$ aetherstack

AetherStack — text Hub
======================
1) List presets
2) Show a preset's node tree
3) Run a preset
4) Run Auto
5) Build a new preset (opens $EDITOR)
6) Edit an existing preset (opens $EDITOR)
7) Export a preset to a YAML file
8) Import a preset from a YAML file
9) Cancel the active run
s) Start the local stack (Docker Compose)
d) Stop the local stack
t) Stack status (Docker + service health)
0) Exit
```

## Scripting / non-interactive use

Every menu action also has a direct subcommand, so the CLI is scriptable in
shell pipelines and CI without touching the menu:

```bash
aetherstack up
aetherstack status
aetherstack list
aetherstack tree coding
aetherstack run coding "fix the flaky test in test_graph_exec.py"
echo "fix the flaky test" | aetherstack run coding      # goal can come from stdin
aetherstack run coding "..." --json | jq .answer

aetherstack export coding > coding.aether-preset.yaml
aetherstack import coding.aether-preset.yaml             # saves as a new preset
aetherstack build                                        # new preset, opens $EDITOR
aetherstack build --edit coding                           # edit an existing preset's tree
aetherstack cancel <run_id>
```

`aetherstack tree <preset>` prints the same node tree the canvas shows
graphically, but as indented text — each node's type, label, model/tier/cost,
and a one-line prompt snippet, following the actual fan-out/fan-in wiring
(master → every worker/parallel branch, concurrently → audit → tester →
output).

## GDPR-compliant mode

```bash
aetherstack gdpr status              # settings + the cloud-provider subprocessor list
aetherstack gdpr enable              # forces safer defaults (see below)
aetherstack gdpr retention 14        # days before archives/vectors expire
aetherstack gdpr consent <session>   # allow that session to route to cloud models
aetherstack gdpr revoke <session>
aetherstack gdpr export <session>    # Article 15/20: everything stored for that session
aetherstack gdpr erase <session>     # Article 17: real deletion, not archive-then-clear
```

When enabled: `/clear` erases instead of archiving, archives/vectors get an
expiring retention window instead of living forever, and Auto excludes
cloud/subscription models from a session until `gdpr consent` is recorded for
it — a prompt cannot silently leave the machine. This flips the Hub's
defaults for an operator; it does not by itself make a deployment legally
compliant. Same settings, same effect, as the Hub's `/gdpr` page.

## Preset scripts (YAML)

`export`/`import`/`build` all use the same
[whole-preset YAML format](../../docs/) the canvas's Import/Export preset
script buttons use (`aether-hub/preset_script.py`) — a preset is:

```yaml
title: Backend + Frontend build
goal: Ship the login page
master:
  model: claude-sonnet-4
  prompt: Plan the work and delegate to workers.
workers:
  - label: Backend
    model: grok-code
    prompt: Implement the backend change.
parallel:
  - label: Survey
    branches: 3
    prompt: Independently investigate the approach.
audit:
  prompt: Check the work for correctness and regressions.
tester:
  prompt: Run and verify the tests.
```

`aetherstack build` opens exactly this format in `$EDITOR`/`$VISUAL` (falls
back to `vi`); saving and exiting imports and saves it.

## Testing

```bash
cd integrations/cli
npm test
```
