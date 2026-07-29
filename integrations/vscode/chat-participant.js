"use strict";

const { parseChatInput, commandHelp } = require("./chat-routing");

/**
 * Adapts HubChat's Hub-calling logic to VS Code's Chat Participant API, so
 * AetherStack shows up as a tab in the native Chat panel next to other
 * participants (Codex, Claude Code, Grok, ...). The stream can only render
 * markdown/buttons/progress — no dropdowns or the webview's node graph — so
 * routing/lean-mode selection happens via slash commands instead of <select>s.
 */
function createChatRequestHandler(hubChat) {
  return async function handleChatRequest(request, _context, stream, token) {
    if (!hubChat.services.length) {
      try {
        await hubChat.loadServices(false, null);
      } catch (error) {
        stream.markdown(`AetherStack Hub is unreachable: ${error.message || error}`);
        return;
      }
    }
    const original = request.command ? `/${request.command} ${request.prompt}`.trim() : request.prompt;
    const parsed = parseChatInput(original, "auto", hubChat.services.map((service) => service.id));

    if (parsed.action === "error") {
      stream.markdown(parsed.message);
      return;
    }
    if (parsed.action === "help") {
      stream.markdown(commandHelp(hubChat.services));
      return;
    }
    if (parsed.action === "presets") {
      stream.markdown(hubChat.services.map((service) => `- **/${service.id}** — ${service.label}: ${service.summary}`).join("\n"));
      return;
    }
    if (parsed.action === "select") {
      stream.markdown(`Preset selected: **${parsed.serviceId}**. Send your goal in the next message.`);
      return;
    }

    const prompt = String(parsed.prompt || "").trim();
    if (!prompt) {
      stream.markdown("Enter a goal first.");
      return;
    }
    if (token.isCancellationRequested) return;

    let serviceId = parsed.serviceId;
    let selection;
    if (serviceId === "auto") {
      stream.progress("Analyzing intent…");
      selection = await hubChat.hubRequest("/api/services/classify", { method: "POST", body: { goal: prompt } });
      serviceId = String(selection.service_id || "");
      if (!hubChat.services.some((service) => service.id === serviceId)) {
        stream.markdown("AetherStack could not map this request to an available service preset.");
        return;
      }
      selection.source = "intent-analysis";
    } else if (parsed.command) {
      const service = hubChat.services.find((item) => item.id === serviceId) || {};
      selection = { service_id: serviceId, label: service.label || serviceId, confidence: "fixed", source: "slash-command" };
    }
    if (selection) {
      const confidence = selection.confidence && selection.confidence !== "fixed" ? ` · ${selection.confidence} confidence` : "";
      stream.markdown(`_Active preset: **${selection.label || serviceId}**${confidence}_\n\n`);
    }
    if (token.isCancellationRequested) return;

    stream.progress("The agent team is working…");
    const result = await hubChat.hubRequest(`/api/services/${encodeURIComponent(serviceId)}/run`, {
      method: "POST",
      body: {
        goal: prompt,
        lean_mode: "balanced",
        token_saver: false,
        history: hubChat.history.slice(-8),
      },
    });
    hubChat.history.push({ role: "user", content: prompt }, { role: "assistant", content: result.answer || "" });
    stream.markdown(result.answer || result.output || "Completed without a text answer.");

    const team = (result.agents || []).map((agent) => agent.model).filter(Boolean).join(", ");
    if (team) stream.markdown(`\n\n---\n*Team: ${team}*`);
    stream.button({ command: "aetherstack.openControlCenter", title: "Advanced setup" });
  };
}

module.exports = { createChatRequestHandler };
