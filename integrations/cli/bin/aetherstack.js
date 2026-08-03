#!/usr/bin/env node
"use strict";

const hubClient = require("../lib/hub-client");
const commands = require("../lib/commands");
const { createMenu } = require("../lib/menu");

const USAGE = `AetherStack CLI — the text equivalent of the Hub. No VS Code required:
this alone can start, use, and stop a full AetherStack checkout.

Usage:
  aetherstack                          Interactive menu (list/run/build/export/import presets)
  aetherstack up                       Start the local stack (Docker Compose) — like start.sh
  aetherstack down                     Stop the local stack — like stop.sh
  aetherstack status                   Docker + service health for this checkout
  aetherstack list                     List available presets
  aetherstack tree <preset>            Show a preset's node tree as text
  aetherstack run <preset> [goal]      Run a preset (reads goal from stdin if omitted)
  aetherstack run auto [goal]          Run Auto
  aetherstack build [--edit <preset>]  Open $EDITOR on a preset script, save the result
  aetherstack export <preset> [file]   Export a preset as a YAML preset script (stdout if no file)
  aetherstack import <file>            Import a YAML preset script and save it as a new preset
  aetherstack cancel <run_id>          Cancel a run by id

  aetherstack gdpr status                    Show GDPR mode settings + subprocessor list
  aetherstack gdpr enable                    Turn on GDPR-compliant mode
  aetherstack gdpr disable                   Turn off GDPR-compliant mode
  aetherstack gdpr retention <days>          Set retention days for archives/vectors
  aetherstack gdpr consent <session_id>      Record consent to route that session to cloud models
  aetherstack gdpr revoke <session_id>       Revoke consent for that session
  aetherstack gdpr export <session_id>       Export everything stored for a session (Article 15/20)
  aetherstack gdpr erase <session_id>        Permanently erase a session's data (Article 17)

Options:
  --hub <url>     Hub base URL (default: $AETHERSTACK_HUB_URL or http://127.0.0.1:8766)
  --cwd <path>    AetherStack checkout to operate on for up/down/status (default: current directory)
  --json          For "run": print the final result as JSON instead of plain text
  -h, --help      Show this help
`;

function readStdin() {
  return new Promise((resolve) => {
    if (process.stdin.isTTY) {
      resolve("");
      return;
    }
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
  });
}

function parseArgs(argv) {
  const args = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--hub") flags.hub = argv[++i];
    else if (arg === "--edit") flags.edit = argv[++i];
    else if (arg === "--cwd") flags.cwd = argv[++i];
    else if (arg === "--json") flags.json = true;
    else if (arg === "-h" || arg === "--help") flags.help = true;
    else args.push(arg);
  }
  return { args, flags };
}

async function main(argv) {
  const { args, flags } = parseArgs(argv);
  if (flags.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  const baseUrl = flags.hub || hubClient.DEFAULT_BASE_URL;
  const client = {
    listServices: (o) => hubClient.listServices({ baseUrl, ...o }),
    getServiceGraph: (id, o) => hubClient.getServiceGraph(id, { baseUrl, ...o }),
    saveServiceGraph: (id, g, o) => hubClient.saveServiceGraph(id, g, { baseUrl, ...o }),
    saveGraph: (g, o) => hubClient.saveGraph(g, { baseUrl, ...o }),
    runServiceStream: (id, e, cb, o) => hubClient.runServiceStream(id, e, cb, { baseUrl, ...o }),
    runGraphStream: (g, e, cb, o) => hubClient.runGraphStream(g, e, cb, { baseUrl, ...o }),
    cancelRun: (id, o) => hubClient.cancelRun(id, { baseUrl, ...o }),
    fromPresetScript: (t, o) => hubClient.fromPresetScript(t, { baseUrl, ...o }),
    toPresetScript: (g, o) => hubClient.toPresetScript(g, { baseUrl, ...o }),
    getGdprSettings: (o) => hubClient.getGdprSettings({ baseUrl, ...o }),
    setGdprSettings: (p, o) => hubClient.setGdprSettings(p, { baseUrl, ...o }),
    gdprConsent: (id, o) => hubClient.gdprConsent(id, { baseUrl, ...o }),
    gdprRevokeConsent: (id, o) => hubClient.gdprRevokeConsent(id, { baseUrl, ...o }),
    gdprExport: (id, o) => hubClient.gdprExport(id, { baseUrl, ...o }),
    gdprErase: (id, o) => hubClient.gdprErase(id, { baseUrl, ...o }),
  };

  const [command, ...rest] = args;

  if (!command) {
    console.log(`AetherStack CLI — talking to ${baseUrl}`);
    await createMenu(client, { baseUrl }).run();
    return 0;
  }

  if (command === "up") {
    const root = await commands.startStack(flags.cwd, { onOutput: (chunk) => process.stdout.write(chunk) });
    console.log(`\nAetherStack is up (${root}).`);
    return 0;
  }

  if (command === "down") {
    const root = await commands.stopStack(flags.cwd);
    console.log(`AetherStack stopped (${root}).`);
    return 0;
  }

  if (command === "status") {
    const { root, docker, services } = await commands.stackStatus(flags.cwd);
    console.log(`Checkout: ${root}`);
    console.log(`Docker: ${docker.installed ? (docker.running ? "running" : "installed, not running") : "not installed"}`);
    for (const s of services) console.log(`${s.ok ? "OK  " : "FAIL"}  ${s.name || s.id}\t${s.url || ""}${s.ok ? "" : `\t${s.error || ""}`}`);
    return services.every((s) => s.ok) ? 0 : 1;
  }

  if (command === "list") {
    const presets = await commands.listPresets(client);
    for (const p of presets) console.log(`${p.id}\t${p.label || ""}\t${p.summary || ""}`);
    return 0;
  }

  if (command === "tree") {
    const id = rest[0];
    if (!id) throw new Error("usage: aetherstack tree <preset>");
    const { text } = await commands.showTree(client, id);
    console.log(text);
    return 0;
  }

  if (command === "run") {
    const id = rest[0];
    if (!id) throw new Error("usage: aetherstack run <preset|auto> [goal]");
    let goal = rest.slice(1).join(" ").trim();
    if (!goal) goal = (await readStdin()).trim();
    if (!goal) throw new Error("no goal given (pass it as an argument or pipe it on stdin)");
    let streamed = false;
    const result = await commands.runPreset(client, id, goal, {
      onEvent: (event) => {
        if (event.type === "status") {
          process.stderr.write(`… ${[event.phase, event.label].filter(Boolean).join(" — ")}\n`);
        } else if (event.type === "delta" && event.text && !flags.json) {
          streamed = true;
          process.stdout.write(event.text);
        }
      },
    });
    if (result.cancelled) {
      console.error("[cancelled]");
      return 1;
    }
    if (!result.result) {
      // The stream ended without a "done" event (e.g. the hub crashed mid-run) —
      // this is a failure, not a quiet success with nothing to show.
      console.error("Error: run ended without a result");
      return 1;
    }
    if (flags.json) {
      console.log(JSON.stringify(result.result, null, 2));
    } else if (!streamed) {
      // Host-CLI models don't stream deltas (services.py disables on_delta for
      // them) — nothing was printed as it happened, so print the answer now.
      console.log(result.result.answer || "(no answer)");
    } else {
      console.log("");
    }
    return 0;
  }

  if (command === "build") {
    const saved = await commands.buildOrEditPreset(client, { presetId: flags.edit });
    console.log(`Saved "${saved.id}".`);
    return 0;
  }

  if (command === "export") {
    const id = rest[0];
    if (!id) throw new Error("usage: aetherstack export <preset> [file]");
    const file = rest[1];
    const text = await commands.exportPreset(client, id, file);
    if (!file) console.log(text);
    else console.error(`Wrote ${file}`);
    return 0;
  }

  if (command === "import") {
    const file = rest[0];
    if (!file) throw new Error("usage: aetherstack import <file>");
    const saved = await commands.importPreset(client, file);
    console.log(`Imported and saved as "${saved.id}".`);
    return 0;
  }

  if (command === "cancel") {
    const runId = rest[0];
    if (!runId) throw new Error("usage: aetherstack cancel <run_id>");
    const result = await commands.cancelRun(client, runId);
    console.log(result.found ? `Cancel requested for ${runId}.` : `${runId} was not an active run.`);
    return 0;
  }

  if (command === "gdpr") {
    const sub = rest[0];
    if (sub === "status") {
      const settings = await commands.gdprStatus(client);
      console.log(`enabled: ${settings.enabled}`);
      console.log(`retention_days: ${settings.retention_days}`);
      console.log(`require_cloud_consent: ${settings.require_cloud_consent}`);
      console.log("subprocessors:");
      for (const p of settings.subprocessors.cloud_providers) console.log(`  ${p.provider}\t${p.models}\t${p.purpose}`);
      console.log(settings.subprocessors.local_note);
      return 0;
    }
    if (sub === "enable" || sub === "disable") {
      await commands.gdprSetSettings(client, { enabled: sub === "enable" });
      console.log(`GDPR mode ${sub === "enable" ? "enabled" : "disabled"}.`);
      return 0;
    }
    if (sub === "retention") {
      const days = Number(rest[1]);
      if (!days) throw new Error("usage: aetherstack gdpr retention <days>");
      await commands.gdprSetSettings(client, { retention_days: days });
      console.log(`Retention set to ${days} days.`);
      return 0;
    }
    if (sub === "consent" || sub === "revoke") {
      const sid = rest[1];
      if (!sid) throw new Error(`usage: aetherstack gdpr ${sub} <session_id>`);
      const result = await commands.gdprConsent(client, sid, { revoke: sub === "revoke" });
      console.log(`${sid}: consented=${result.consented}`);
      return 0;
    }
    if (sub === "export") {
      const sid = rest[1];
      if (!sid) throw new Error("usage: aetherstack gdpr export <session_id>");
      console.log(JSON.stringify(await commands.gdprExportData(client, sid), null, 2));
      return 0;
    }
    if (sub === "erase") {
      const sid = rest[1];
      if (!sid) throw new Error("usage: aetherstack gdpr erase <session_id>");
      const result = await commands.gdprEraseData(client, sid);
      console.log(JSON.stringify(result, null, 2));
      return 0;
    }
    throw new Error(`usage: aetherstack gdpr <status|enable|disable|retention|consent|revoke|export|erase>`);
  }

  process.stderr.write(`Unknown command: ${command}\n\n${USAGE}`);
  return 1;
}

if (require.main === module) {
  main(process.argv.slice(2))
    .then((code) => process.exit(code || 0))
    .catch((err) => {
      console.error(`Error: ${err.message}`);
      process.exit(1);
    });
}

module.exports = { main, parseArgs, USAGE };
