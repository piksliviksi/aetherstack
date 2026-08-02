# AetherStack Debian distro packaging (scaffold)

**Status:** E0 preparation — structure and docs only; ISO build is not production-ready yet.

This tree prepares **Debian-family images** and metapackages for:

| Edition | Config | Compose |
|---------|--------|---------|
| **Desktop** | [editions/desktop.yaml](./editions/desktop.yaml) | Default `docker-compose.yml` (loopback appliance) |
| **Team Server** | [editions/team-server.yaml](./editions/team-server.yaml) | + `docker-compose.team.yml` |
| **Cloud control plane** | [editions/cloud-control-plane.yaml](./editions/cloud-control-plane.yaml) | + team + `docker-compose.enterprise.yml` (deploy ref, not an ISO) |

Product architecture: [docs/ENTERPRISE-PLATFORM.md](../docs/ENTERPRISE-PLATFORM.md)  
ISO technical design: [docs/DEBIAN-DISTRO-BUILD.md](../docs/DEBIAN-DISTRO-BUILD.md)  
Multi-user phases: [docs/MULTI-USER.md](../docs/MULTI-USER.md)  
Roadmap: [docs/ENTERPRISE-ROADMAP.md](../docs/ENTERPRISE-ROADMAP.md)

---

## Layout

```text
distro/
  editions/           # declarative edition flags → env rendering
  live-build/         # Debian live-build hooks and package lists
  packages/           # .deb metapackage skeletons
  systemd/            # unit files installed on the image
  cloud-init/         # Team Server first-boot examples
  scripts/            # bake cache, smoke, render env
  sbom/               # placeholder for release SBOMs
```

---

## Quick commands (developer machine)

```bash
# Render env template from an edition (requires python3 + pyyaml if used)
./distro/scripts/render-edition-env.sh desktop

# Validate team compose merges (from repo root; needs docker compose)
./distro/scripts/validate-compose.sh

# QEMU smoke — stub until images exist
./distro/scripts/qemu-smoke.sh --help
```

Build ISO (requires Debian/Ubuntu builder with `live-build`):

```bash
./distro/live-build/build-iso.sh --edition desktop
# ./distro/live-build/build-iso.sh --edition team-server
```

---

## Safety

- **Desktop** remains the default product path; do not enable LAN binds without auth.
- **Team Server** edition sets `AETHER_REQUIRE_AUTH=1` in templates; Hub enforcement lands in E1.
- Never bake production API keys into images.

---

## Version

Packaging track: see [VERSION](./VERSION) (may lag product `VERSION` during prep).
