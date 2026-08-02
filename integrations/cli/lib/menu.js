"use strict";

const readline = require("readline");

const commands = require("./commands");
const { renderTree } = require("./tree");

const MENU_TEXT = `
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
`;

function formatEvent(event) {
  if (event.type === "status") {
    const bits = [event.phase, event.label].filter(Boolean);
    return `… ${bits.join(" — ") || "working"}`;
  }
  return null;
}

async function pickPreset(client, ask, label = "Preset id") {
  const presets = await commands.listPresets(client);
  presets.forEach((p) => console.log(`  ${p.id.padEnd(20)} ${p.label || ""}`));
  return ask(`${label}: `);
}

function createMenu(client, { input = process.stdin, output = process.stdout, baseUrl } = {}) {
  const rl = readline.createInterface({ input, output });
  const ask = (question) => new Promise((resolve) => rl.question(question, resolve));
  let activeRunId = null;

  const onSigint = () => {
    if (activeRunId) {
      output.write("\nCancelling active run…\n");
      commands.cancelRun(client, activeRunId).catch(() => {});
    }
  };
  process.on("SIGINT", onSigint);

  async function doRun(presetId, goalHint) {
    const goal = goalHint || (await ask("Goal: "));
    if (!goal.trim()) {
      console.log("No goal entered.");
      return;
    }
    console.log(`Running "${presetId}"… (Ctrl+C to cancel)`);
    try {
      const result = await commands.runPreset(client, presetId, goal, {
        onEvent: (event) => {
          activeRunId = event.run_id || activeRunId;
          if (event.type === "delta" && event.text) output.write(event.text);
          else {
            const line = formatEvent(event);
            if (line) console.log(line);
          }
        },
      });
      activeRunId = null;
      if (result.cancelled) {
        console.log("\n[cancelled]");
        return;
      }
      console.log(`\n\n--- Answer (model: ${result.result?.model || "?"}) ---`);
      console.log(result.result?.answer || "(no answer)");
    } catch (err) {
      activeRunId = null;
      console.log(`\nRun failed: ${err.message}`);
    }
  }

  async function loop() {
    for (;;) {
      console.log(MENU_TEXT);
      const choice = (await ask("> ")).trim();
      try {
        if (choice === "1") {
          const presets = await commands.listPresets(client);
          presets.forEach((p) => console.log(`${p.id.padEnd(20)} ${p.label || ""}${p.summary ? ` — ${p.summary}` : ""}`));
        } else if (choice === "2") {
          const id = await pickPreset(client, ask);
          if (!id.trim()) continue;
          const { text } = await commands.showTree(client, id.trim());
          console.log(text);
        } else if (choice === "3") {
          const id = await pickPreset(client, ask);
          if (!id.trim()) continue;
          await doRun(id.trim());
        } else if (choice === "4") {
          await doRun("auto");
        } else if (choice === "5") {
          console.log(`Opening $EDITOR (${process.env.EDITOR || process.env.VISUAL || "vi"})…`);
          const saved = await commands.buildOrEditPreset(client);
          console.log(`Saved as "${saved.id}".`);
        } else if (choice === "6") {
          const id = await pickPreset(client, ask, "Preset id to edit");
          if (!id.trim()) continue;
          const saved = await commands.buildOrEditPreset(client, { presetId: id.trim() });
          console.log(`Saved "${saved.id}".`);
        } else if (choice === "7") {
          const id = await pickPreset(client, ask, "Preset id to export");
          if (!id.trim()) continue;
          const file = await ask("Output file (blank = print to screen): ");
          const text = await commands.exportPreset(client, id.trim(), file.trim() || undefined);
          if (!file.trim()) console.log(text);
          else console.log(`Wrote ${file.trim()}`);
        } else if (choice === "8") {
          const file = await ask("Preset script file: ");
          if (!file.trim()) continue;
          const saved = await commands.importPreset(client, file.trim());
          console.log(`Imported and saved as "${saved.id}".`);
        } else if (choice === "9") {
          if (!activeRunId) {
            console.log("No active run to cancel.");
          } else {
            await commands.cancelRun(client, activeRunId);
            console.log(`Cancel requested for ${activeRunId}.`);
          }
        } else if (choice.toLowerCase() === "s") {
          const root = await commands.startStack(undefined, { onOutput: (chunk) => output.write(chunk) });
          console.log(`\nAetherStack is up (${root}).`);
        } else if (choice.toLowerCase() === "d") {
          const root = await commands.stopStack();
          console.log(`AetherStack stopped (${root}).`);
        } else if (choice.toLowerCase() === "t") {
          const { root, docker, services } = await commands.stackStatus();
          console.log(`Checkout: ${root}`);
          console.log(`Docker: ${docker.installed ? (docker.running ? "running" : "installed, not running") : "not installed"}`);
          services.forEach((s) => console.log(`${s.ok ? "OK  " : "FAIL"}  ${s.name || s.id}\t${s.url || ""}${s.ok ? "" : `\t${s.error || ""}`}`));
        } else if (choice === "0" || choice.toLowerCase() === "q") {
          break;
        } else {
          console.log("Unknown choice.");
        }
      } catch (err) {
        console.log(`Error: ${err.message}`);
      }
    }
  }

  return {
    run: () => loop().finally(() => {
      process.removeListener("SIGINT", onSigint);
      rl.close();
    }),
  };
}

module.exports = { createMenu, MENU_TEXT, formatEvent };
