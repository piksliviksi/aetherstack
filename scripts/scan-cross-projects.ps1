# Scan one or more project roots for LLM-native folders and index into Aether Hub cross-memory.
param(
  [string[]]$Paths = @(),
  [string]$HubUrl = "http://127.0.0.1:8766",
  [switch]$EnableMultiProject,
  [switch]$FromParent,  # scan immediate child dirs of -Paths[0]
  [int]$MaxFiles = 60
)
$ErrorActionPreference = "Continue"

if ($EnableMultiProject) {
  try {
    Invoke-RestMethod -Method POST -Uri "$HubUrl/api/xref" -ContentType "application/json" `
      -Body (@{ multi_project = $true; auto_pull = $true } | ConvertTo-Json) -TimeoutSec 10 | Out-Null
    Write-Host "Multi-project mode ON" -ForegroundColor Green
  } catch { Write-Host "Hub xref enable failed: $_" -ForegroundColor Yellow }
}

$roots = @()
if ($Paths.Count -eq 0) {
  $Paths = @((Get-Location).Path)
}
foreach ($p in $Paths) {
  if (-not (Test-Path $p)) { Write-Host "Skip missing $p"; continue }
  $rp = (Resolve-Path $p).Path
  if ($FromParent) {
    Get-ChildItem $rp -Directory -ErrorAction SilentlyContinue | ForEach-Object { $roots += $_.FullName }
  } else {
    $roots += $rp
  }
}

Write-Host "Scanning $($roots.Count) project(s) for LLM-native history..." -ForegroundColor Cyan

# Prefer hub-side scan if we send paths the hub can read (Linux/WSL mounts).
# On Windows Docker, host paths usually aren't visible — upload chunks via Python if available.
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
  $env:AETHER_HUB = $HubUrl
  $rootsJson = ($roots | ConvertTo-Json -Compress)
  $code = @'
import json, os, sys, urllib.request
sys.path.insert(0, os.path.join(os.environ.get("AETHER_STACK", r"D:\llm\stack"), "aether-hub"))
# fallback path next to script
script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
roots = json.loads(os.environ["AETHER_ROOTS"])
hub = os.environ.get("AETHER_HUB", "http://127.0.0.1:8766")
# load scanner from repo
candidates = [
    os.path.join(r"D:\llm\stack", "aether-hub"),
    os.path.join(os.getcwd(), "aether-hub"),
    os.path.join(os.path.dirname(os.getcwd()), "aether-hub"),
]
for c in candidates:
    if os.path.isfile(os.path.join(c, "cross_memory.py")):
        sys.path.insert(0, c)
        break
from cross_memory import scan_project_tree

def post(path, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(hub + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

for root in roots:
    print("scan", root)
    sc = scan_project_tree(root, max_files=int(os.environ.get("AETHER_MAX_FILES", "60")))
    if sc.get("error"):
        print(" error", sc["error"])
        continue
    # strip embeddings work to hub
    payload = {
        "project_id": sc.get("project_id"),
        "path": sc.get("path"),
        "name": sc.get("name"),
        "sources": sc.get("sources"),
        "chunks": sc.get("chunks"),
        "scanned_at": sc.get("scanned_at"),
    }
    try:
        res = post("/api/xref/index", payload)
        print(" indexed", res.get("indexed"), "kinds", res.get("kinds"))
    except Exception as e:
        print(" hub index failed", e)
'@
  $env:AETHER_ROOTS = $rootsJson
  $env:AETHER_MAX_FILES = "$MaxFiles"
  $env:AETHER_STACK = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
  $tmp = Join-Path $env:TEMP "aether-xref-scan.py"
  # fix __file__ path - write script with stack path injected
  $stack = $env:AETHER_STACK
  $code2 = @"
import json, os, sys, urllib.request
sys.path.insert(0, r"$stack\aether-hub")
from cross_memory import scan_project_tree
roots = json.loads(os.environ["AETHER_ROOTS"])
hub = os.environ.get("AETHER_HUB", "http://127.0.0.1:8766")

def post(path, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(hub + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())

for root in roots:
    print("scan", root)
    sc = scan_project_tree(root, max_files=int(os.environ.get("AETHER_MAX_FILES", "60")))
    if sc.get("error"):
        print(" error", sc["error"]); continue
    payload = {k: sc.get(k) for k in ("project_id","path","name","sources","chunks","scanned_at")}
    try:
        res = post("/api/xref/index", payload)
        print(" indexed", res.get("indexed"), "kinds", res.get("kinds"))
    except Exception as e:
        print(" hub index failed", e)
"@
  Set-Content -Path $tmp -Value $code2 -Encoding utf8
  python $tmp
} else {
  Write-Host "Python required for cross-project scan." -ForegroundColor Red
  exit 1
}

Write-Host ""
Write-Host "Search: POST $HubUrl/api/xref/search  {`"query`":`"auth middleware`"}" -ForegroundColor DarkCyan
Write-Host "Pull:   POST $HubUrl/api/xref/pull    {`"query`":`"tested oauth`"}" -ForegroundColor DarkCyan
