"use strict";

const { parseChatInput, commandHelp } = require("./chat-routing");

function responseText(response) {
  return (Array.isArray(response) ? response : [response])
    .map((part) => {
      if (typeof part === "string") return part;
      if (part && typeof part.value === "string") return part.value;
      if (part && typeof part.value?.value === "string") return part.value.value;
      return "";
    })
    .filter(Boolean)
    .join("\n")
    .slice(0, 200_000);
}

function historyFromContext(context) {
  return (Array.isArray(context && context.history) ? context.history : []).slice(-16).flatMap((turn) => {
    if (turn && typeof turn.prompt === "string") {
      return [{ role: "user", content: turn.prompt.slice(0, 200_000) }];
    }
    const content = responseText(turn && turn.response);
    return content ? [{ role: "assistant", content }] : [];
  }).slice(-8);
}

function selectedServiceFromContext(context, availableServiceIds) {
  const history = Array.isArray(context && context.history) ? context.history : [];
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const turn = history[index] || {};
    const prompt = String(turn.prompt || "").trim();
    const command = String(turn.command || "").trim();
    const original = command ? `/${command} ${prompt}`.trim() : prompt;
    if (!original.startsWith("/")) continue;
    const parsed = parseChatInput(original, "auto", availableServiceIds);
    if (parsed.action === "select" || parsed.action === "run") return parsed.serviceId;
  }
  return "auto";
}

/**
 * Adapts HubChat's Hub-calling logic to VS Code's Chat Participant API, so
 * AetherStack shows up as a tab in the native Chat panel next to other
 * participants (Codex, Claude Code, Grok, ...). The stream can only render
 * markdown/buttons/progress — no dropdowns or the webview's node graph — so
 * routing/lean-mode selection happens via slash commands instead of <select>s.
 */
function createChatRequestHandler(hubChat) {
  return async function handleChatRequest(request, context, stream, token) {
    if (!hubChat.services.length) {
      try {
        await hubChat.loadServices(false, null);
      } catch (error) {
        stream.markdown(`AetherStack Hub is unreachable: ${error.message || error}`);
        return;
      }
    }
    const original = request.command ? `/${request.command} ${request.prompt}`.trim() : request.prompt;
    const serviceIds = hubChat.services.map((service) => service.id);
    const selectedService = selectedServiceFromContext(context, serviceIds);
    const parsed = parseChatInput(original, selectedService, serviceIds);

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
    const controller = new AbortController();
    const cancellation = typeof token.onCancellationRequested === "function"
      ? token.onCancellationRequested(() => controller.abort())
      : null;

    try {
      let serviceId = parsed.serviceId;
      let selection;
      if (serviceId === "auto") {
        stream.progress("Auto · host CLI + memory…");
        selection = {
          service_id: "auto",
          label: "Auto",
          confidence: "direct",
          source: "auto-direct-models",
        };
      } else if (parsed.command) {
        const service = hubChat.services.find((item) => item.id === serviceId) || {};
        selection = { service_id: serviceId, label: service.label || serviceId, confidence: "fixed", source: "slash-command" };
      }
      if (selection) {
        if (selection.service_id === "auto") {
          stream.markdown("_Auto · host CLIs as detected + unified memory · fail over on limits → local Ollama_\n\n");
        } else {
          const confidence = selection.confidence && selection.confidence !== "fixed" ? ` · ${selection.confidence} confidence` : "";
          stream.markdown(`_Active preset: **${selection.label || serviceId}**${confidence}_\n\n`);
        }
      }
      if (token.isCancellationRequested) return;

      if (serviceId !== "auto") stream.progress("I'm on it…");
      const result = await hubChat.hubRequest(`/api/services/${encodeURIComponent(serviceId)}/run`, {
        method: "POST",
        signal: controller.signal,
        body: {
          goal: prompt,
          lean_mode: "balanced",
          token_saver: false,
          history: historyFromContext(context),
          session_id: "vscode-participant",
        },
      });
      stream.markdown(result.answer || result.output || "Completed without a text answer.");

      if (result.auto_mode && result.model) {
        const failed = (result.failover_attempts || []).map((a) => a.model).filter(Boolean);
        const note = failed.length
          ? `*Model: **${result.model}** (after ${failed.join(" → ")} limits)*`
          : `*Model: **${result.model}***`;
        stream.markdown(`\n\n---\n${note}`);
      } else {
        const team = (result.agents || []).map((agent) => agent.model).filter(Boolean).join(", ");
        if (team) stream.markdown(`\n\n---\n*Team: ${team}*`);
      }
      stream.button({ command: "aetherstack.openControlCenter", title: "Advanced setup" });
    } catch (error) {
      if (error && (error.name === "AbortError" || error.code === "ABORT_ERR")) {
        stream.markdown("AetherStack request cancelled.");
        return;
      }
      throw error;
    } finally {
      cancellation?.dispose?.();
    }
  };
}

module.exports = { createChatRequestHandler, historyFromContext, selectedServiceFromContext };
