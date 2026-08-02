"use strict";

// Reuses the VS Code extension's docker-compose lifecycle helpers directly —
// stack-control.js has no dependency on the `vscode` API, so it works
// standalone here too. This is what lets someone install and run AetherStack
// from just this CLI, without installing VS Code at all.
const {
  checkDocker,
  checkServices,
  findStackRoot,
  isStackRoot,
  startCompose,
  stopCompose,
  restartCompose,
} = require("../../vscode/stack-control");

function resolveStackRoot(cwd = process.cwd()) {
  const root = findStackRoot({ cwd, workspacePaths: [cwd] });
  if (!root) {
    throw new Error(
      "Could not find an AetherStack checkout (looked for docker-compose.yml, aether-hub/, litellm_config.yaml " +
        "starting from the current directory and its parents). Run this from inside your AetherStack checkout, " +
        "or pass --cwd <path>."
    );
  }
  return root;
}

module.exports = {
  checkDocker,
  checkServices,
  findStackRoot,
  isStackRoot,
  resolveStackRoot,
  startCompose,
  stopCompose,
  restartCompose,
};
