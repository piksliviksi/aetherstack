#!/usr/bin/env node
"use strict";

const hubClient = require("../lib/hub-client");
const commands = require("../lib/commands");
const { createMenu } = require("../lib/menu");

const USAGE = `AetherStack CLI — the text equivalent of the Hub.

Usage:
  aetherstack                          Interactive menu (list/run/build/export/import presets)
  aetherstack list                     List available presets
  aetherstack tree <preset>            Show a preset's node tree as text
  aetherstack run <preset> [goal]      Run a preset (reads goal from stdin if omitted)
  aetherstack run auto [goal]          Run Auto
  aetherstack build [--edit <preset>]  Open $EDITOR on a preset script, save the result
  aetherstack export <preset> [file]   Export a preset as a YAML preset script (stdout if no file)
  aetherstack import <file>            Import a YAML preset script and save it as a new preset
  aetherstack cancel <run_id>          Cancel a run by id

Options:
  --hub <url>     Hub base URL (default: $AETHERSTACK_HUB_URL or http://127.0.0.1:8766)
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
  };

  const [command, ...rest] = args;

  if (!command) {
    console.log(`AetherStack CLI — talking to ${baseUrl}`);
    await createMenu(client, { baseUrl }).run();
    return 0;
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
    const result = await commands.runPreset(client, id, goal, {
      onEvent: (event) => {
        if (event.type === "status") {
          process.stderr.write(`… ${[event.phase, event.label].filter(Boolean).join(" — ")}\n`);
        } else if (event.type === "delta" && event.text && !flags.json) {
          process.stdout.write(event.text);
        }
      },
    });
    if (result.cancelled) {
      console.error("[cancelled]");
      return 1;
    }
    if (flags.json) {
      console.log(JSON.stringify(result.result, null, 2));
    } else if (!result.result?.answer) {
      // Nothing streamed as delta (host-CLI models don't stream) — print now.
      console.log(result.result?.answer || "(no answer)");
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
