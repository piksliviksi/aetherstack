# Building a Debian-Based Distro with AetherStack Built In

**Status:** design guide + E0 scaffold in [distro/](../distro/)  
**Audience:** platform engineers, image maintainers, offline/lab appliance builders, enterprise ops  
**AetherStack reference:** v0.3.x (control plane via Docker Compose; host Ollama for local GPU)

This document describes how to build a **Debian-family live or installable distribution** that ships with the **AetherStack toolkit pre-installed and ready to start**. It covers architecture choices, image pipelines, package layout, first-boot behaviour, GPU variants, and the practical benefits of an appliance-style image versus a manual install.

**Enterprise editions:** Desktop (single operator) and **Team Server** (multi-user, OIDC) share this pipeline. Cloud is deploy-config, not an ISO — see [ENTERPRISE-PLATFORM.md](./ENTERPRISE-PLATFORM.md) and [MULTI-USER.md](./MULTI-USER.md).

---

## 0. Editions (Desktop vs Team Server)

| Edition | Config | Network | Auth | Compose |
|---------|--------|---------|------|---------|
| **Desktop** | [distro/editions/desktop.yaml](../distro/editions/desktop.yaml) | Loopback | Single operator | `docker-compose.yml` |
| **Team Server** | [distro/editions/team-server.yaml](../distro/editions/team-server.yaml) | TLS reverse proxy on 443; app ports loopback | OIDC + local users (air-gap) | + `docker-compose.team.yml` |
| **Cloud** | [distro/editions/cloud-control-plane.yaml](../distro/editions/cloud-control-plane.yaml) | Edge only | OIDC/SAML multi-tenant | + team + `docker-compose.enterprise.yml` |

**Rule:** Team Server images must set `AETHER_REQUIRE_AUTH=1`. Do not publish Hub/LiteLLM on LAN without E1 JWT enforcement.

Scaffold commands:

```bash
./distro/scripts/render-edition-env.sh desktop
./distro/scripts/render-edition-env.sh team-server
./distro/live-build/build-iso.sh --edition team-server
./distro/scripts/validate-compose.sh
```

---

## 1. Goal

Deliver an OS image where a developer or lab machine boots to a known-good state:

| Outcome | Target |
|---------|--------|
| Control plane | Docker Compose stack (Hub, LiteLLM, Redis, Postgres, Open WebUI + loopback proxy) starts cleanly |
| Local inference | Host **Ollama** installed, socket on `127.0.0.1:11434`, default coding model pre-pulled or staged |
| Operator surface | VS Code (or code-server) + AetherStack extension optional; Simple Hub at `:8766`; chat façade at `:3000` / `:4000` |
| Network posture | Services bound to **loopback by default**; no accidental internet exposure of the gateway |
| Update path | Documented, checksummed runtime/VSIX updates; Compose image pins preserved |

AetherStack’s design already matches an appliance model: **Docker = control plane**, **host Ollama = GPU path**. A custom distro formalizes that split so every machine shares the same layout.

---

## 2. What “AetherStack toolkit” means in the image

Bake in (or stage) these layers:

### 2.1 Runtime control plane (required)

From the upstream repo (`docker-compose.yml` and related assets):

| Component | Role | Typical host bind |
|-----------|------|-------------------|
| **aether-hub** | Orchestration, Auto mode, services, memory, OpenAI-compatible façade, node graph | `127.0.0.1:8766` |
| **litellm** | Multi-provider gateway, spend/budget | `127.0.0.1:4000` |
| **postgres** | LiteLLM spend DB (internal) | not published |
| **redis** | Cache / coordination | `127.0.0.1:6379` |
| **open-webui** | Optional rich chat UI (internal) | not published |
| **open-webui-proxy** | Loopback passwordless local session | `127.0.0.1:3000` |
| **ollama** (optional profile) | Only if host GPU path is unavailable | prefer **host** Ollama |

Supporting tree on disk (example):

```text
/opt/aetherstack/                 # pinned release checkout or unpacked runtime tarball
  docker-compose.yml
  docker-compose.nvidia.yml
  docker-compose.amd.yml
  litellm_config.yaml
  .env.example → /etc/aetherstack/env (managed)
  aether-hub/
  open-webui-proxy/
  open-webui-config/
  pipelines/  combos/  scripts/
  start.sh  stop.sh
```

### 2.2 Host inference (required for local GPU)

| Piece | Notes |
|-------|--------|
| **Ollama** (native `.deb` or vendor install script packaged offline) | Prefer host over container for CUDA / ROCm / Vulkan |
| Default model | e.g. `qwen2.5-coder:7b` as `local-default` backend floor for coding |
| Embeddings | e.g. `nomic-embed-text` for RAG / Open WebUI embedding path |
| GPU stacks (image flavors) | NVIDIA: driver + CUDA userland; AMD: ROCm; Intel: see project GPU docs |

### 2.3 Operator tools (recommended)

| Piece | Notes |
|-------|--------|
| Docker Engine + Compose plugin | Engine of the control plane |
| `aetherstack` CLI wrappers | thin systemd units + `/usr/local/bin/aetherstack {start,stop,status,update}` |
| VS Code / code-server + VSIX | Marketplace or pre-seeded `aetherstack-*.vsix` from `dist/` |
| Project Engine (optional) | `project-engine/` for multi-project awareness |
| Desktop entry | `.desktop` launcher → start stack + open Hub |

### 2.4 What *not* to bake naively

| Avoid | Why |
|-------|-----|
| Live cloud API keys in the image | Secrets belong in first-boot or user-provisioned `/etc/aetherstack/env` |
| Unpinned `:latest` images | Breaks reproducibility; pin digests as Compose already tends to |
| Publishing ports on `0.0.0.0` by default | Contradicts local-appliance security model |
| Giant multi-GPU drivers in one ISO | Prefer **flavor ISOs** (cpu / nvidia / amd) to keep images bootable and smaller |

---

## 3. Reference architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│  Debian-based AetherStack OS (live or installed)                │
│                                                                 │
│  User space                                                     │
│    VS Code / browser ──► Hub :8766 / Proxy :3000 / Gateway :4000│
│                                                                 │
│  systemd                                                        │
│    aetherstack.target                                           │
│      ├─ docker.service                                          │
│      ├─ ollama.service          (host inference)                │
│      └─ aetherstack-compose.service                             │
│           docker compose -f /opt/aetherstack/docker-compose.yml │
│                                                                 │
│  Containers (control plane)          Host                       │
│    hub · litellm · redis · pg        Ollama :11434              │
│    open-webui · proxy                GPU driver / ROCm / CUDA   │
│         │                                   ▲                   │
│         └──── host.docker.internal ─────────┘                   │
│                                                                 │
│  Data volumes                                                   │
│    /var/lib/aetherstack/docker-volumes/                         │
│    /var/lib/ollama/  or  ~ollama/.ollama                        │
│    /var/lib/aetherstack/config/env                              │
└─────────────────────────────────────────────────────────────────┘
```

**Invariant:** inference stays on the host where GPU access is simplest; orchestration stays in Compose where it is portable and versioned.

---

## 4. Distro build approaches (technical)

Pick one primary pipeline; all can produce the same on-disk layout.

### 4.1 Approach A — Debian live-build (recommended baseline)

**Tools:** `live-build` (`lb config`, `lb build`) on a Debian/Ubuntu builder host.

**Why:** Official Debian path for hybrid ISO (live + installer), hooks for packages and overlays, reproducible config trees.

**Sketch:**

```bash
# On a clean builder (Debian bookworm/trixie or Ubuntu build chroot)
sudo apt-get install -y live-build debootstrap squashfs-tools xorriso

mkdir -p ~/aether-os && cd ~/aether-os
lb config \
  --distribution bookworm \
  --architectures amd64 \
  --binary-images iso-hybrid \
  --bootappend-live "boot=live components hostname=aether quiet splash" \
  --mirror-bootstrap http://deb.debian.org/debian/ \
  --archive-areas "main contrib non-free non-free-firmware"

# Package lists
cat > config/package-lists/aether.list.chroot <<'EOF'
docker.io
docker-compose
curl
ca-certificates
git
python3
python3-venv
nodejs
npm
jq
vim
sudo
network-manager
EOF
# Prefer Docker CE from docker.com for production; pin versions in a local apt repo.

# Overlay: copy toolkit into the image
mkdir -p config/includes.chroot/opt/aetherstack
# rsync release tree (no .git, no user .env secrets)
rsync -a --exclude '.git' --exclude '.env' /path/to/aetherstack/ \
  config/includes.chroot/opt/aetherstack/

# Hooks: post-install configuration inside chroot
cat > config/hooks/live/9999-aetherstack.hook.chroot <<'EOF'
#!/bin/bash
set -euo pipefail
# Install Ollama (offline .deb preferred)
# dpkg -i /root/debs/ollama_*.deb || true

# System user / groups
getent group docker >/dev/null || groupadd --system docker
usermod -aG docker aether 2>/dev/null || true

# systemd units (installed under /etc/systemd/system)
systemctl enable docker.service
systemctl enable ollama.service || true
systemctl enable aetherstack-compose.service

# Pre-seed compose env template
install -d -m 0755 /etc/aetherstack
if [ ! -f /etc/aetherstack/env ]; then
  cp /opt/aetherstack/.env.example /etc/aetherstack/env
  # generate local-only secrets at first boot, not build time, if multi-tenant
fi
ln -sfn /etc/aetherstack/env /opt/aetherstack/.env

# Pre-load Docker images from a cache tarball if present
if [ -f /root/cache/aether-images.tar ]; then
  docker load -i /root/cache/aether-images.tar || true
fi
EOF
chmod +x config/hooks/live/9999-aetherstack.hook.chroot

sudo lb build
# → live-image-amd64.hybrid.iso
```

**Artifacts:** `*.iso` for USB; optional `*.img` via additional tooling for cloud/raw disk.

### 4.2 Approach B — Ubuntu live-build / Cubic / `ubuntu-image`

Same idea as A, but base = **Ubuntu 22.04/24.04** for broader desktop/driver friendliness (matches current [TUTORIAL-UBUNTU](./TUTORIAL-UBUNTU.md) guidance).

| Tool | Use when |
|------|----------|
| **Cubic** | GUI-friendly customization of Ubuntu desktop ISOs |
| **ubuntu-image** | Snappy/gadget-style or appliance images |
| **live-build** with Ubuntu mirrors | CI-friendly scripted builds |

### 4.3 Approach C — mmdebstrap + systemd-nspawn / disk image

**Tools:** `mmdebstrap`, `genimage` / `virt-make-fs`, optional `packer`.

**Why:** Faster CI than full live-build; good for **cloud qcow2/raw** and headless appliances.

```text
mmdebstrap bookworm rootfs/ ...
  → copy /opt/aetherstack + units
  → pack into ext4 + grub EFI
  → qcow2 for Proxmox/KVM or USB dd image
```

### 4.4 Approach D — OSTree / Immutable (advanced)

**Tools:** `ostree`, `bootc`, or Ubuntu Core-like patterns.

**Why:** Atomic updates, green/blue rollback for lab fleets. AetherStack config and Docker volumes stay on a writable data partition; `/opt/aetherstack` and OS root are immutable and versioned.

### 4.5 Approach E — Debian package + metapackage (complement, not full OS)

Even with a full ISO, ship a metapackage for upgrades on stock Debian/Ubuntu:

```text
aetherstack-toolkit (metapackage)
  Depends: docker-ce | docker.io, ...
  Recommends: ollama, code, ...
  Installs: /opt/aetherstack, systemd units, man pages
```

Build with `dpkg-deb` / `sbuild`. The ISO then simply `apt install aetherstack-toolkit` from a local component repo.

---

## 5. Image content pipeline (CI-friendly)

```text
┌──────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ git tag      │───►│ package-runtime  │───►│ /opt tree +     │
│ VERSION      │    │ + verify scripts │    │ checksums       │
└──────────────┘    └──────────────────┘    └────────┬────────┘
                                                     │
┌──────────────┐    ┌──────────────────┐             ▼
│ compose pins │───►│ docker pull +    │───► docker save → cache tarball
│ digests      │    │ smoke tests      │
└──────────────┘    └──────────────────┘
                                                     │
┌──────────────┐    ┌──────────────────┐             ▼
│ model list   │───►│ ollama pull      │───► models blob cache (optional)
│ (7b + embed) │    │ offline store    │
└──────────────┘    └──────────────────┘
                                                     │
                                                     ▼
                                            live-build / mmdebstrap
                                                     │
                                                     ▼
                                            signed ISO / qcow2 + SBOM
```

**Suggested CI stages:**

1. **Unit/integration** — existing repo tests (`pytest`, runtime smoke).
2. **Compose bake** — `docker compose pull` + `docker compose config` + `scripts/runtime-smoke.py` in a VM.
3. **Image build** — live-build or mmdebstrap with fixed package snapshot (`aptly` or snapshot.debian.org).
4. **Boot smoke** — QEMU: boot ISO → wait for `aetherstack-compose` healthy → curl `:8766` / `:4000/health`.
5. **Sign & publish** — GPG/cosign on ISO + SHA256SUMS; attach SBOM (Syft/Grype).

Reuse upstream packaging where possible: `scripts/package-runtime.mjs`, `scripts/verify-runtime.mjs`, `dist/aetherstack-runtime-*.tar.gz`.

---

## 6. systemd integration (technical detail)

### 6.1 `aetherstack-compose.service`

```ini
[Unit]
Description=AetherStack Docker Compose control plane
After=docker.service network-online.target ollama.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/aetherstack
EnvironmentFile=-/etc/aetherstack/env
# start.sh generates keys and brings the stack up; wrap for non-interactive boot
ExecStart=/opt/aetherstack/start.sh
ExecStop=/opt/aetherstack/stop.sh
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

**First-boot unit** (oneshot) should:

1. If `LITELLM_MASTER_KEY` empty → generate and write to `/etc/aetherstack/env` (mode `0600`).
2. Run discover/bootstrap dry-run; optionally pull models if network allowed.
3. Touch `/var/lib/aetherstack/first-boot-done`.

Mirror Hub’s first-run ideas (`/api/first-run`, `docs/AUTO-INSTALL.md`) but **host-level** so the machine is useful before any browser session.

### 6.2 Ollama

- Enable `ollama.service` (vendor unit or custom).
- Bind loopback if you only need Docker’s `host.docker.internal` path; or keep default localhost.
- Seed models from an offline blob directory on first boot when online pull is disabled.

### 6.3 Desktop (optional GNOME/KDE spin)

`/usr/share/applications/aetherstack.desktop`:

```ini
[Desktop Entry]
Name=AetherStack
Comment=Multi-model control plane
Exec=/usr/local/bin/aetherstack-open
Icon=aetherstack
Terminal=false
Type=Application
Categories=Development;Network;
```

`aetherstack-open` starts the stack if needed, then opens `http://127.0.0.1:8766`.

---

## 7. Configuration and secrets model

| Path | Purpose | Image policy |
|------|---------|--------------|
| `/etc/aetherstack/env` | Compose/env secrets and feature flags | Template only in ISO; real keys at first boot or cloud-init |
| `/etc/aetherstack/litellm.d/` | Optional drop-in fragments (multi-key) | Empty dirs OK |
| `/var/lib/aetherstack/` | State, backups, update staging | Writable |
| Docker volumes | Hub memory, Open WebUI DB, Redis, Postgres | Persist on data partition |
| `~/.ollama` or `/usr/share/ollama` | Models | Preseed optional large blobs on data partition |

**Cloud-init / unattended example:**

```yaml
#cloud-config
write_files:
  - path: /etc/aetherstack/env.d/10-keys.env
    permissions: '0600'
    content: |
      ANTHROPIC_API_KEY=...
      OPENAI_API_KEY=...
runcmd:
  - systemctl start aetherstack-compose.service
```

Never ship production cloud keys inside the public ISO.

---

## 8. GPU and hardware flavors

Build **separate images** or a common base + driver DKMS layer:

| Flavor | Host additions | Compose overlay |
|--------|----------------|-----------------|
| **cpu** | Ollama CPU-only; smaller models optional | default compose |
| **nvidia** | Proprietary driver, NVIDIA Container Toolkit only if using GPU containers | `docker-compose.nvidia.yml` when using ollama container profile |
| **amd** | ROCm userland; `HSA_OVERRIDE_GFX_VERSION` documented for RDNA2 | `docker-compose.amd.yml` for optional container path |
| **intel** | Host Ollama / OpenVINO path per `docs/GPU-INTEL.md` | host inference |

**Policy (aligned with upstream):** prefer **host Ollama + GPU** over putting the LLM runtime inside Docker. The distro should make that the default path and treat GPU-in-Docker as advanced.

Hardware sizing note: local 7B-class models want **≥16 GB RAM** for comfortable use with the Compose stack; 8 GB hosts should document “control plane only” or tiny models.

---

## 9. Security posture for an appliance ISO

| Control | Implementation |
|---------|----------------|
| Loopback binds | Keep `AETHER_BIND_HOST=127.0.0.1` defaults from Compose |
| Firewall | `nftables`/`ufw`: allow SSH (if needed); do not expose 3000/4000/8766 on LAN by default |
| Open WebUI | Proxy-only on loopback; auth headers model preserved |
| Updates | Signed runtime tarballs; do not auto-overwrite dirty checkouts from the browser |
| Supply chain | Pin image digests; local apt mirror; SBOM; reproducible package snapshot |
| Private mode | Document vault behaviour for air-gapped labs (`docs/PRIVATE-MODE.md`) |
| Multi-user | Separate OS users ≠ multi-tenant Hub; see `docs/MULTI-USER.md` before marketing as shared server |

---

## 10. Offline / air-gapped build and run

1. On a networked builder: `docker compose pull` → `docker save` all images → `aether-images.tar`.
2. `ollama pull` required models → copy blobs into image data partition or first-boot cache.
3. Vendor `.deb` packages for Docker, Ollama, kernel headers, GPU drivers into `config/packages.chroot/`.
4. Ship apt repo snapshot on the ISO (`file:///media/apt`) for repair installs.
5. Disable first-boot network model pulls when `AETHER_OFFLINE=1`.

Result: a lab machine can install from USB, start the stack, and run **local-only combos** with no outbound API dependency.

---

## 11. End-user experience (what “built in” should feel like)

| Moment | Behaviour |
|--------|-----------|
| Boot | Graphical or console login; optional auto-login for kiosk lab images |
| ~30–90s after login | `docker`, `ollama`, compose healthy (or clear failure in `journalctl -u aetherstack-compose`) |
| Browser | Hub Simple UI and/or Open WebUI proxy work without manual `git clone` |
| First cloud use | User pastes keys into a setup wizard or edits `/etc/aetherstack/env` once |
| Daily work | Same operating model as upstream: Auto failover chain → local Ollama; pipelines/graphs for multi-stage work |
| Stop | `aetherstack stop` or logout script; volumes retained |

---

## 12. Benefits

### 12.1 Versus manual install on stock Ubuntu/Debian

| Benefit | Why it matters |
|---------|----------------|
| **Zero ritual onboarding** | No Docker GPG dance, no clone, no “which ports”, no forgotten `usermod -G docker` |
| **Identical machines** | Labs, classrooms, and fleets share one golden image; support is “boot this ISO” |
| **Faster time-to-first-token** | Images and optional models pre-staged; first boot skips multi-GB pulls |
| **Fewer foot-guns** | Loopback defaults, systemd ordering (Ollama before Hub), pinned digests |
| **Offline capable** | Workshops and secure sites run without registry access |
| **Cleaner GPU story** | Flavor images encode the correct host Ollama + driver path once |

### 12.2 Versus “just Docker on a random laptop”

| Benefit | Why it matters |
|---------|----------------|
| **Host GPU integration** | Distro can ship kernel/firmware/driver pieces Compose cannot |
| **Lifecycle** | OS updates + toolkit metapackage + compose pins versioned together |
| **Appliance semantics** | Single service target, single config dir, single backup story |
| **Policy-friendly** | IT can sign/allowlist one ISO; disable cloud keys centrally via cloud-init |

### 12.3 Product / project benefits for AetherStack itself

| Benefit | Why it matters |
|---------|----------------|
| **Demonstrates the operating model** | Pass-through Auto + shared memory + local fallback becomes the default OS experience |
| **Showcases the toolkit surface** | Hub, gateway, graphs, combos, private mode, backup — all present without a doc scavenger hunt |
| **Differentiates from “another chat UI”** | Ships as a **control-plane workstation**, not a single-model wrapper |
| **Reduces support load** | Most “install is broken” tickets disappear when install is the image |
| **Enables OEM / lab SKUs** | CPU lab, NVIDIA workstation, AMD ROCm workstation as named downloads |

### 12.4 Operational benefits

- **Rollback:** immutable or dual-partition OS + Docker volume backups (`docs/BACKUP.md`).
- **Observability:** one place for `journalctl` + `docker compose logs`.
- **Capacity planning:** document RAM/GPU floors per flavor so Ollama + Compose do not thrash (critical on 8 GB hosts).
- **Security review:** smaller attack surface when ports and auth defaults are fixed in the image, not left to each developer.

---

## 13. Minimal viable image (MVP scope)

Ship v0.1 of the distro with only:

1. Debian or Ubuntu base (server or minimal desktop).  
2. Docker Engine + Compose.  
3. `/opt/aetherstack` from a verified runtime tarball.  
4. Host Ollama + one coding model + embed model (or documented first-boot pull).  
5. systemd units for compose + ollama.  
6. First-boot key generation for `LITELLM_MASTER_KEY`.  
7. QEMU smoke test in CI.  
8. SHA256 + short README on the download page.

Defer to later releases: full desktop polish, VS Code preinstall, OSTree, multi-flavor GPU ISOs, graphical first-run wizard.

---

## 14. Suggested repository layout for the distro project

Can live in-tree (`distro/`) or as `aetherstack-os`:

```text
aetherstack-os/
  README.md
  VERSION
  live-build/
    auto/config
    config/package-lists/
    config/hooks/
    config/includes.chroot/opt/aetherstack/  # or fetch at build
  packages/
    aetherstack-toolkit/debian/
  systemd/
    aetherstack-compose.service
    aetherstack-firstboot.service
  cloud-init/
    lab-user-data.yaml
  scripts/
    bake-docker-cache.sh
    bake-ollama-models.sh
    qemu-smoke.sh
    build-iso.sh
  docs/
    RELEASE.md
    FLAVORS.md
```

Upstream AetherStack remains the source of compose and Hub; the distro repo **vendors a release tag**, it does not fork business logic long-term.

---

## 15. Validation checklist

| Check | Pass criteria |
|-------|----------------|
| Boot ISO in QEMU | multi-user reached without emergency shell |
| `systemctl is-active aetherstack-compose` | active |
| `curl -sf http://127.0.0.1:8766/` | Hub responds |
| `curl -sf http://127.0.0.1:4000/health/liveliness` (or project health URL) | gateway up |
| `curl -sf http://127.0.0.1:11434/api/tags` | Ollama lists seeded models |
| Auto path | local model answers without cloud keys |
| Restart | reboot → stack healthy without manual steps |
| Offline boot | no registry access required if caches baked |
| Ports | `ss -lntp` shows 3000/4000/8766 on 127.0.0.1 only |

---

## 16. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| ISO size (models + images) | Flavor splits; optional “slim” ISO + model pack USB |
| Driver breakage on new GPUs | Separate GPU flavors; host Ollama docs; don’t pin ancient kernels blindly |
| Secret leakage in public builds | CI scan for keys; generate secrets only at first boot |
| Drift from upstream | Build from git tags; metapackage version = `VERSION` |
| RAM exhaustion (Compose + 7B) | Document minimums; ship `cpu-tiny` profile with smaller model |
| Users expect multi-tenant SaaS | Document single-operator appliance defaults |

---

## 17. Related upstream docs

| Doc | Relevance |
|-----|-----------|
| [TUTORIAL-UBUNTU.md](./TUTORIAL-UBUNTU.md) | Native package/runtime install sequence to encode in hooks |
| [OPERATING-MODEL.md](./OPERATING-MODEL.md) | Behaviour the image should preserve (pass-through Auto, memory) |
| [AUTO-INSTALL.md](./AUTO-INSTALL.md) | Optional in-OS bootstrap of missing pieces |
| [GPU-NVIDIA.md](./GPU-NVIDIA.md) / [AMD-COMPUTE.md](./AMD-COMPUTE.md) / [GPU-INTEL.md](./GPU-INTEL.md) | Flavor design |
| [SECURITY-NOTES.md](./SECURITY-NOTES.md) | Hardening defaults |
| [BACKUP.md](./BACKUP.md) | Appliance backup story |
| [QUICKSTART.md](./QUICKSTART.md) | End-user URLs and expectations |

---

## 18. Summary

A Debian-based **AetherStack OS** is not a fork of the model stack—it is a **reproducible host** that freezes the project’s intended architecture:

1. **Host Ollama** for local GPU inference.  
2. **Docker Compose** for Hub, LiteLLM, Redis, Postgres, and the local WebUI path.  
3. **systemd + `/etc/aetherstack`** for appliance lifecycle.  
4. **Pinned, signed artifacts** for offline and fleet use.

**Technically**, build it with live-build or mmdebstrap, layer a metapackage, pre-cache container images (and optionally models), and verify with QEMU smoke tests.

**Practically**, the benefit is a machine that boots into a working multi-model control plane: one gateway, shared memory, cloud→local failover, and private local paths—without each user reinventing the install.

---

*This is a design guide for implementers. It does not replace the install tutorials for stock Ubuntu/macOS/Windows.*
