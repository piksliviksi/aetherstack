"use strict";

const PRESET_ALIASES = Object.freeze({
  research: "research",
  plan: "planning",
  planning: "planning",
  "service-design": "service-design",
  service: "service-design",
  ui: "ui-design",
  "ui-design": "ui-design",
  frontend: "frontend",
  backend: "backend",
  code: "coding",
  coding: "coding",
  test: "testing",
  testing: "testing",
  bug: "bugfixing",
  bugfix: "bugfixing",
  bugfixing: "bugfixing",
  pentest: "whitehat-pentesting",
  security: "whitehat-pentesting",
  "whitehat-pentesting": "whitehat-pentesting",
  polish: "polishing",
  polishing: "polishing",
  docs: "technical-writing",
  write: "technical-writing",
  "technical-writing": "technical-writing",
});

function parseChatInput(input, selectedService = "auto", availableServiceIds = []) {
  const original = String(input || "").trim();
  const selected = String(selectedService || "auto");
  const available = new Set(["auto", ...availableServiceIds.map(String)]);
  if (!original.startsWith("/")) {
    return { action: "run", serviceId: available.has(selected) ? selected : "auto", prompt: original };
  }

  const [rawCommand, ...restParts] = original.slice(1).split(/\s+/);
  const command = String(rawCommand || "").toLowerCase();
  if (command === "help") return { action: "help" };
  if (command === "presets" || command === "services") return { action: "presets" };

  let serviceId;
  let promptParts = restParts;
  if (command === "preset") {
    const requested = String(restParts[0] || "").toLowerCase();
    if (!requested) return { action: "presets" };
    serviceId = requested === "auto" ? "auto" : PRESET_ALIASES[requested] || requested;
    promptParts = restParts.slice(1);
  } else if (command === "auto") {
    serviceId = "auto";
  } else {
    serviceId = PRESET_ALIASES[command];
  }

  if (!serviceId || !available.has(serviceId)) {
    return { action: "error", message: `Unknown AetherStack command or preset: /${command}. Use /help.` };
  }
  const prompt = promptParts.join(" ").trim();
  return prompt
    ? { action: "run", serviceId, prompt, command: true }
    : { action: "select", serviceId };
}

function commandHelp(services = []) {
  const dynamic = services.map((service) => `/${service.id}`).join(", ");
  return [
    "AetherStack commands",
    "• /auto <goal> — analyze the goal and choose the preset",
    "• /preset <name> <goal> — use a named preset",
    "• /presets — list the presets available on this system",
    "• /help — show this help",
    dynamic ? `Shortcuts: ${dynamic}` : "",
  ].filter(Boolean).join("\n");
}

module.exports = { PRESET_ALIASES, parseChatInput, commandHelp };
