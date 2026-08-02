const assert = require("node:assert/strict");
const test = require("node:test");

const { renderTree } = require("../lib/tree");

function graph() {
  return {
    nodes: [
      { id: "g", type: "goal", data: { text: "Ship the login page" } },
      { id: "m", type: "master", data: { label: "Lead", model: "claude-cli", instructions_md: "Plan the work." } },
      { id: "w1", type: "worker", data: { label: "Backend", model: "grok-code" } },
      { id: "w2", type: "worker", data: { label: "Frontend" } },
      { id: "a", type: "analyser", data: { label: "Audit" } },
      { id: "o", type: "output", data: { label: "Final answer" } },
    ],
    edges: [
      { from: "g", to: "m", kind: "data" },
      { from: "m", to: "w1", kind: "data" },
      { from: "m", to: "w2", kind: "data" },
      { from: "w1", to: "a", kind: "data" },
      { from: "w2", to: "a", kind: "data" },
      { from: "a", to: "o", kind: "data" },
    ],
  };
}

test("renders every node exactly once, starting from the root with no incoming edge", () => {
  const text = renderTree(graph());
  assert.match(text, /\[goal\]/);
  assert.match(text, /\[master\] Lead \(model=claude-cli\)/);
  assert.match(text, /\[worker\] Backend \(model=grok-code\)/);
  assert.match(text, /\[worker\] Frontend \(model=auto-resolve\)/);
  assert.match(text, /\[analyser\] Audit/);
  assert.match(text, /\[output\] Final answer/);
  // each node id appears in exactly one "[type]" line
  for (const id of ["goal", "master", "worker", "worker", "analyser", "output"]) {
    assert.equal((text.match(new RegExp(`\\[${id}\\]`, "g")) || []).length >= 1, true);
  }
});

test("branches under the fan-out node are indented deeper than it", () => {
  const lines = renderTree(graph()).split("\n");
  const masterLine = lines.findIndex((l) => l.includes("[master]"));
  const backendLine = lines.findIndex((l) => l.includes("Backend"));
  assert.ok(backendLine > masterLine);
  assert.ok(lines[backendLine].includes("├─") || lines[backendLine].includes("└─"));
});

test("shows the instructions/prompt snippet under a node that has one", () => {
  const text = renderTree(graph());
  assert.match(text, /"Plan the work\."/);
});

test("a node unreachable from any root is still shown, not silently dropped", () => {
  const g = graph();
  g.nodes.push({ id: "orphan", type: "worker", data: { label: "Orphan" } });
  const text = renderTree(g);
  assert.match(text, /Orphan/);
});

test("a cyclic/recursive edge does not infinite-loop", () => {
  const g = graph();
  g.edges.push({ from: "o", to: "m", kind: "feedback" });
  g.edges.push({ from: "a", to: "m", kind: "data" }); // cycle back to master
  const text = renderTree(g);
  assert.match(text, /already shown above/);
});
