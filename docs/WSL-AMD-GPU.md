# WSL + AMD Radeon RX 6600 XT (this machine)

## Status (2026-07-25)

| Check | Result |
|-------|--------|
| `/dev/dxg` | Present |
| `rocminfo` Agent 2 | **AMD Radeon RX 6600 XT / gfx1032** |
| Mesa `vulkaninfo` | Still **llvmpipe only** (expected on AMD WSL) |
| Official AMD WSL GPU list | RX 7000/9000 series + some Ryzen APUs |
| RX 6600 XT enablement | Via **librocdxg** + custom `dids.conf` entry |

## What was installed (Debian 13 WSL)

1. **librocdxg** `rocdxg-roct_1.2.1` from [ROCm/librocdxg](https://github.com/ROCm/librocdxg/releases)
2. **ROCm 7.2.4** HSA runtime from `repo.radeon.com` (`hsa-rocr`, `rocm-core`, AMD `rocminfo`)
3. Device ID allow-list:

```text
# /opt/rocm/share/rocdxg/dids.conf
0x73FF,10,3,2    # RX 6600 XT (Navi 23 / gfx1032)
```

4. Environment ( `/etc/profile.d/aether-rocm.sh` ):

```bash
export HSA_ENABLE_DXG_DETECTION=1
export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/opt/rocm/bin${PATH:+:$PATH}"
```

## Verify

```bash
source /etc/profile.d/aether-rocm.sh
rocminfo | grep -A5 "Agent 2"
# Expect: Marketing Name: AMD Radeon RX 6600 XT
```

## Important limitations

1. **Not Vulkan** — GPU compute is via **ROCm/HSA → DXCore**, not Mesa Vulkan. `vulkaninfo` may still show only llvmpipe.
2. **Warning: “Windows driver is old”** — Adrenalin on this PC is ~**25.10.x**; AMD docs recommend **Adrenalin 26.2.2** for production ROCDXG. Upgrade when possible.
3. **Unofficial for RX 6000** — AMD’s matrix focuses on 7000/9000. The `dids.conf` line is community-style enablement; some workloads may still fail.
4. **Debian + Ubuntu ROCm packages** — mixed repos; pin AMD `rocminfo` if Debian’s package shadows `/opt/rocm/bin`.
5. **Ollama** — needs ROCm-capable build/env; host Ollama on Windows may be separate from WSL Ollama.

## Next steps for full LLM GPU use

```bash
# After GPU shows in rocminfo:
ollama serve   # with env from profile.d
ollama run tinyllama "hi"
# Watch Windows Task Manager → GPU → Compute for activity
```

Optional: upgrade Adrenalin to **26.2.2+**, then retest.

## Dual-boot alternative

For full Mesa Vulkan + native `amdgpu` (no DXG): install Debian bare metal with Mesa/ROCm — more reliable than WSL for RDNA2 inference.
