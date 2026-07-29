# WSL + AMD Radeon RX 6600 XT example

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
2. **Adrenalin version** — Host driver ~**25.10.x** on the reference machine; AMD documents **Adrenalin 26.2.2+** for production ROCDXG.
3. **RX 6000 matrix** — AMD’s official list emphasizes 7000/9000. The `dids.conf` line is enablement outside that list; some workloads fail.
4. **Debian + Ubuntu ROCm packages** — mixed repos; pin AMD `rocminfo` if Debian’s package shadows `/opt/rocm/bin`.
5. **Ollama** — needs ROCm-capable build/env; host Ollama on Windows may be separate from WSL Ollama.
6. **Reference inference result (2026-07-29)** — ROCm discovered the RX 6600 XT and Ollama reported GPU offload, but the HTTP inference ended prematurely and the service restarted. This path is therefore not the AetherStack default on this card.

## Use the AMD compute engines (required for real GPU LLM)

Seeing the card in `rocminfo` is **not** enough. Ollama must load the **ROCm/HIP** runner so kernels run on the GPU’s **compute units** (e.g. 32 CUs on RX 6600 XT).

```bash
# Force ROCm package (stock install skips it on WSL — no lspci amdgpu)
sudo bash /mnt/d/llm/stack/scripts/install-ollama-rocm-wsl.sh
bash /mnt/d/llm/stack/scripts/amd-compute-status.sh

ollama run tinyllama "hi"
ollama ps   # must NOT be 100% CPU
# Windows Task Manager → GPU → Compute_* activity
```

Full write-up: [AMD-COMPUTE.md](./AMD-COMPUTE.md).

Adrenalin **26.2.2+**: retest ROCDXG after upgrade.

## VS Code on the same machine

VS Code does not attach to the AMD GPU for LLM inference on Windows 11. Clients use LiteLLM (`http://127.0.0.1:4000/v1`). On the reference RX 6600 XT, the working server is Windows host Ollama with Vulkan; WSL ROCm remains an opt-in experiment. See [VSCODE.md](./VSCODE.md).

## Bare metal

Full Mesa Vulkan + native `amdgpu` (no DXG): Debian (or other Linux) bare metal with Mesa/ROCm.
