# live-build (Debian ISO)

Scaffold for hybrid ISOs. Full procedure: [docs/DEBIAN-DISTRO-BUILD.md](../../docs/DEBIAN-DISTRO-BUILD.md).

## Prerequisites (builder host)

- Debian or Ubuntu with `live-build`, `debootstrap`, `squashfs-tools`, `xorriso`
- Docker (to bake image cache tarballs)
- Optional: Ollama model blob cache for offline Desktop images

## Build

```bash
./build-iso.sh --edition desktop
./build-iso.sh --edition team-server
```

The script currently validates the environment and prints the intended `lb config` steps. Wire real `lb build` once package lists and `/opt/aetherstack` overlay are complete.

## Package lists

| File | Contents |
|------|----------|
| `config/package-lists/aether-common.list.chroot` | Docker deps, curl, python, jq |
| `config/package-lists/aether-desktop.list.chroot` | Desktop conveniences |
| `config/package-lists/aether-team.list.chroot` | Server/proxy oriented packages |
