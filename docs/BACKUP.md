# Backup (local PC + cloud buckets)

Export AetherStack **memory, research, session context** — per **project** or **global** — **manually** or on a **schedule**.  
Write to a **local folder** on the PC and/or a pre-configured **AWS S3** / **Azure Blob** bucket.

Status: **shipped** for local hub (lab).

---

## Scopes

| Scope | Contents |
|-------|----------|
| `global` | Common vector namespaces, sessions, xref registry, privacy state |
| `project` | Filtered by `project_id` / `project_path` / `session_id`; includes `.aetherstack/` research files under that path |

| Flag | Default | Effect |
|------|---------|--------|
| `include_private` | false | Private vaults excluded unless true |
| `include_embeddings` | false | Smaller archives; vectors without embedding arrays |

---

## Destinations

| Destination | Config |
|-------------|--------|
| **Local folder** | `local.path` (default `.aetherstack/backups`) |
| **AWS S3** | `aws.bucket` + credentials (`boto3` or AWS CLI) |
| **Azure Blob** | `azure.container` + connection string env |

Multiple destinations can run in one backup (local + S3, etc.).

---

## Manual

### Hub API

```bash
# Global → local zip
curl -s -X POST http://127.0.0.1:8766/api/backup \
  -H "Content-Type: application/json" \
  -d '{"scope":"global","destinations":["local"]}'

# One project → local + S3
curl -s -X POST http://127.0.0.1:8766/api/backup \
  -H "Content-Type: application/json" \
  -d '{"scope":"project","project_path":"D:/code/myapp","destinations":["local","aws"]}'

# List backups + config
curl -s http://127.0.0.1:8766/api/backup | jq .
```

### Host scripts

```powershell
# Windows
.\scripts\backup-aether.ps1 -Scope global
.\scripts\backup-aether.ps1 -Scope project -ProjectPath D:\code\myapp -Destinations local,aws
.\scripts\backup-aether.ps1 -ConfigureAuto -AutoIntervalSec 86400 -LocalDir D:\Backups\aether
```

```bash
# Linux / macOS
./scripts/backup-aether.sh global local
PROJECT_PATH=/path/to/app ./scripts/backup-aether.sh project local
```

---

## Automatic

1. Write `.aetherstack/backup.yaml` from `backup.yaml.example`, or:

```bash
curl -s -X POST http://127.0.0.1:8766/api/backup/config \
  -H "Content-Type: application/json" \
  -d '{"auto":{"enabled":true,"interval_sec":86400,"scope":"global"},"local":{"enabled":true,"path":".aetherstack/backups"}}'
```

2. Hub background sync runs `run_auto_if_due` on each matrix interval when auto is enabled.

Env shortcuts:

| Env | Effect |
|-----|--------|
| `AETHER_BACKUP_DIR` | Local destination path |
| `AETHER_BACKUP_S3_BUCKET` | Enable S3 + bucket name |
| `AETHER_BACKUP_S3_PREFIX` | S3 key prefix |
| `AETHER_BACKUP_AZURE_CONTAINER` | Enable Azure container |
| `AETHER_BACKUP_AUTO=1` | Enable auto in config load |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure upload auth |
| AWS standard env / profile | S3 upload auth |

---

## Archive layout

```text
aether-backup-YYYYMMDDTHHMMSSZ-<id>.zip
  manifest.json      # scope, meta, privacy, xref registry
  vectors.json       # namespace → vectors (optional embeddings)
  sessions.json      # session_id → messages
  project_files/     # .aetherstack notes when project_path set
```

Schema: `aetherstack.backup.v1`.

---

## Privacy

| Rule | Fact |
|------|------|
| Private vaults | Omitted unless `include_private: true` |
| Cloud upload | Only to **your** pre-configured bucket; credentials stay client-side |
| Retention | `local.keep_last` prunes old local zips |

---

## Related

- [PRIVATE-MODE.md](./PRIVATE-MODE.md)  
- [AGENT-MEMORY.md](./AGENT-MEMORY.md)  
- [FUTURE.md](./FUTURE.md) enterprise backup  
- Example config: [backup.yaml.example](./backup.yaml.example) → copy to `.aetherstack/backup.yaml`
