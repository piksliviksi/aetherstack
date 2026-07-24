# Scan a project folder for AI chat artifacts and write .aetherstack overview
param(
  [Parameter(Mandatory = $false)]
  [string]$Path = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $Path).Path
$outDir = Join-Path $root ".aetherstack"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$checks = @(
  @{ id = "continue"; rel = ".continue"; label = "Continue.dev" },
  @{ id = "claude"; rel = ".claude"; label = "Claude / Claude Code" },
  @{ id = "waylog"; rel = ".waylog"; label = "WayLog" },
  @{ id = "aetherstack"; rel = ".aetherstack"; label = "AetherStack" },
  @{ id = "cursor"; rel = ".cursor"; label = "Cursor" }
)

$sources = @()
foreach ($c in $checks) {
  $p = Join-Path $root $c.rel
  if (Test-Path $p) {
    $files = Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 12
    $sources += [pscustomobject]@{
      id        = $c.id
      label     = $c.label
      path      = $p
      fileCount = @($files).Count
      recent    = @($files | ForEach-Object {
          [pscustomobject]@{
            name  = $_.FullName.Substring($root.Length).TrimStart('\', '/')
            mtime = $_.LastWriteTime.ToString("o")
            size  = $_.Length
          }
        })
    }
  }
}

foreach ($name in @("aider.chat.history.md", ".aider.chat.history.md")) {
  $p = Join-Path $root $name
  if (Test-Path $p) {
    $i = Get-Item $p
    $sources += [pscustomobject]@{
      id = "aider"; label = "Aider"; path = $p; fileCount = 1
      recent = @([pscustomobject]@{ name = $name; mtime = $i.LastWriteTime.ToString("o"); size = $i.Length })
    }
  }
}

$overview = [pscustomobject]@{
  generatedAt = (Get-Date).ToString("o")
  workspace   = $root
  sources     = $sources
  aetherstack = @{
    baseUrl       = "http://127.0.0.1:4000/v1"
    chatUiUrl     = "http://127.0.0.1:3000"
    defaultModel  = "local-default"
  }
}

$jsonPath = Join-Path $outDir "project-overview.json"
$overview | ConvertTo-Json -Depth 6 | Set-Content $jsonPath -Encoding utf8

$md = @("# AetherStack project overview", "", "Generated: $($overview.generatedAt)", "Workspace: ``$root``", "", "## Detected AI history sources", "")
if (-not $sources.Count) {
  $md += "_None found._"
} else {
  foreach ($s in $sources) {
    $md += "### $($s.label)"
    $md += "- Path: ``$($s.path)``"
    $md += "- Files sampled: $($s.fileCount)"
    foreach ($r in $s.recent) { $md += "  - ``$($r.name)`` ($($r.mtime))" }
    $md += ""
  }
}
$md += "## Continue"
$md += "1. Start AetherStack (start.bat / ./start.sh)"
$md += "2. VS Code: install integrations/vscode extension"
$md += "3. Command: AetherStack: Wire Continue.dev"
$md += "4. Chat UI: http://127.0.0.1:3000"
$md += ""
$mdPath = Join-Path $outDir "project-overview.md"
$md -join "`n" | Set-Content $mdPath -Encoding utf8

Write-Host "Wrote $mdPath"
Write-Host "Sources: $($sources.Count)"
$sources | ForEach-Object { Write-Host " - $($_.label) ($($_.fileCount) files)" }
