"use strict";

/** One-line summary of a node's config — the text equivalent of an Inspector panel. */
function describeNode(node) {
  const d = node.data || {};
  const bits = [];
  if (d.model) bits.push(`model=${d.model}`);
  else if (["master", "worker", "parallel", "analyser", "tester"].includes(node.type)) bits.push("model=auto-resolve");
  if (d.tier) bits.push(`tier=${d.tier}`);
  if (d.max_cost) bits.push(`cost=${d.max_cost}`);
  if (d.parallel && Number(d.parallel) > 1) bits.push(`parallel=${d.parallel}`);
  if (d.script) bits.push("script=yes");
  if (d.workspace_write) bits.push("workspace_write=yes");
  return bits.join(" ");
}

function promptSnippet(node, maxChars = 90) {
  const d = node.data || {};
  const text = d.instructions_md || d.text || "";
  if (!text) return "";
  const oneLine = String(text).replace(/\s+/g, " ").trim();
  return oneLine.length > maxChars ? `${oneLine.slice(0, maxChars)}…` : oneLine;
}

/**
 * Renders a graph as an indented text tree, following edges from every
 * node with no incoming edge (the roots — normally just "goal"). Falls back
 * to appending any node the edge walk never reached, so nothing is silently
 * dropped even for an unusual/custom wiring.
 */
function renderTree(graph, { color = false } = {}) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const childrenOf = new Map();
  const hasIncoming = new Set();
  for (const edge of edges) {
    if ((edge.kind || "data") !== "data") continue;
    if (!byId.has(edge.from) || !byId.has(edge.to)) continue;
    if (!childrenOf.has(edge.from)) childrenOf.set(edge.from, []);
    childrenOf.get(edge.from).push(edge.to);
    hasIncoming.add(edge.to);
  }
  const roots = nodes.filter((n) => !hasIncoming.has(n.id)).map((n) => n.id);

  const lines = [];
  const visited = new Set();
  const bold = (s) => (color ? `\x1b[1m${s}\x1b[0m` : s);
  const dim = (s) => (color ? `\x1b[2m${s}\x1b[0m` : s);

  function walk(id, linePrefix, childPrefix) {
    const node = byId.get(id);
    if (!node) return;
    if (visited.has(id)) {
      lines.push(`${linePrefix}${dim(`(already shown above)`)} → ${node.data?.label || id}`);
      return;
    }
    visited.add(id);
    const label = node.data && node.data.label ? node.data.label : node.type;
    const summary = describeNode(node);
    lines.push(`${linePrefix}${bold(`[${node.type}]`)} ${label}${summary ? dim(` (${summary})`) : ""}`);
    const snippet = promptSnippet(node);
    if (snippet) lines.push(`${childPrefix}    ${dim(`"${snippet}"`)}`);
    const kids = childrenOf.get(id) || [];
    kids.forEach((childId, index) => {
      const isLast = index === kids.length - 1;
      walk(childId, `${childPrefix}${isLast ? "└─ " : "├─ "}`, `${childPrefix}${isLast ? "   " : "│  "}`);
    });
  }

  roots.forEach((id) => walk(id, "", ""));
  for (const node of nodes) {
    if (!visited.has(node.id)) walk(node.id, dim("(unreached) "), "");
  }
  return lines.join("\n");
}

module.exports = { renderTree, describeNode, promptSnippet };
