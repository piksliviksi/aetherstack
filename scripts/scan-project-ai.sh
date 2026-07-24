#!/usr/bin/env bash
# Scan a project for AI chat folders and write .aetherstack overview
set -euo pipefail
ROOT="$(cd "${1:-.}"; pwd)"
OUT="$ROOT/.aetherstack"
mkdir -p "$OUT"

{
  echo "# AetherStack project overview"
  echo ""
  echo "Generated: $(date -Iseconds 2>/dev/null || date)"
  echo "Workspace: \`$ROOT\`"
  echo ""
  echo "## Detected AI history sources"
  echo ""
} > "$OUT/project-overview.md"

found=0
for pair in "continue:.continue:Continue.dev" "claude:.claude:Claude Code" "waylog:.waylog:WayLog" "aetherstack:.aetherstack:AetherStack" "cursor:.cursor:Cursor"; do
  id="${pair%%:*}"
  rest="${pair#*:}"
  rel="${rest%%:*}"
  label="${rest#*:}"
  p="$ROOT/$rel"
  if [[ -e "$p" ]]; then
    found=$((found+1))
    {
      echo "### $label"
      echo "- Path: \`$p\`"
      echo "- Sample files:"
      find "$p" -type f 2>/dev/null | head -12 | while read -r f; do
        echo "  - \`${f#$ROOT/}\`"
      done
      echo ""
    } >> "$OUT/project-overview.md"
    echo "Found: $label"
  fi
done

for name in aider.chat.history.md .aider.chat.history.md; do
  if [[ -f "$ROOT/$name" ]]; then
    found=$((found+1))
    echo "### Aider" >> "$OUT/project-overview.md"
    echo "- \`$name\`" >> "$OUT/project-overview.md"
    echo "" >> "$OUT/project-overview.md"
    echo "Found: Aider"
  fi
done

if [[ "$found" -eq 0 ]]; then
  echo "_None found._" >> "$OUT/project-overview.md"
fi

{
  echo "## Continue with AetherStack"
  echo "1. ./start.sh  (or start.bat on Windows)"
  echo "2. Install VS Code extension: integrations/vscode"
  echo "3. Command: AetherStack: Wire Continue.dev"
  echo "4. Open http://127.0.0.1:3000"
} >> "$OUT/project-overview.md"

echo "Wrote $OUT/project-overview.md ($found sources)"
