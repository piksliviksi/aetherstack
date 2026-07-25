# AMD compute engines (ROCm / HIP / DXG)

AetherStack local inference on Radeon must use the GPU’s **compute units (CUs)** via **ROCm/HSA**, not the display stack and not a CUDA-only Ollama build.

## Do we write a custom driver?

| Layer | Who provides it | Aether role |
|-------|-----------------|-------------|
| Kernel / display / DXCore | **AMD Adrenalin** (Windows), **amdgpu** (Linux) | Never replace |
| ROCDXG / HSA in WSL | **librocdxg** + ROCm | Install/configure |
| LLM HIP kernels | **Ollama ROCm package** (`libggml` HIP) | Force-install on WSL |
| Device profiles, dids, env, probes | **`aether-amd/` userspace adapter** | Yes — this is our “driver glue” |

We **do not** ship a signed kernel GPU driver. That would be a multi-year AMD/Microsoft project.  
We **do** ship a **userspace compute adapter** so the stack always targets the CUs correctly:

```bash
python3 aether-amd/probe.py
sudo bash aether-amd/ensure-backend.sh
```

## What “compute engines” means here

On discrete AMD GPUs (e.g. **RX 6600 XT**):

| Concept | Example (RX 6600 XT) |
|---------|----------------------|
| Marketing name | AMD Radeon RX 6600 XT |
| ISA / gfx | gfx1032 (Navi 23); often overridden to **gfx1030** for HIP |
| **Compute Units** | **32** |
| Wavefront | 32 |
| Access on Win11 | WSL2 **`/dev/dxg`** + **librocdxg** + ROCm HSA |
| Access on Linux bare metal | `/dev/kfd` + `/dev/dri` + ROCm |

`rocminfo` **Agent 2** with `Device Type: GPU` and `Compute Unit: 32` means the stack can see the engines.  
**`ollama ps` showing `100% CPU`** means those engines are **not** being used for LLM kernels yet.

## Why Ollama often stays on CPU in WSL

1. Stock `install.sh` downloads **`ollama-linux-amd64-rocm` only if `lspci` finds AMD**.  
2. Under WSL + ROCDXG, the GPU often **does not appear as PCI amdgpu** — only via `rocminfo` / DXG.  
3. Result: install keeps **cuda_v12 / cuda_v13 / vulkan / cpu** runners → **VRAM = 0**, inference on CPU.

**Fix:** Aether AMD adapter + ROCm Ollama package:

```bash
# In Debian WSL — preferred
sudo bash /mnt/d/llm/stack/aether-amd/ensure-backend.sh
python3 /mnt/d/llm/stack/aether-amd/probe.py

# Or low-level:
sudo bash /mnt/d/llm/stack/scripts/install-ollama-rocm-wsl.sh
bash /mnt/d/llm/stack/scripts/amd-compute-status.sh
```

From Windows (elevated auto-install path):

```powershell
.\scripts\auto-install.ps1 -Yes -IncludeElevated
```

## Required environment (systemd)

```bash
HSA_ENABLE_DXG_DETECTION=1
HSA_OVERRIDE_GFX_VERSION=10.3.0    # RDNA2 consumer cards
LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib
HIP_VISIBLE_DEVICES=0
ROCR_VISIBLE_DEVICES=0
OLLAMA_HOST=0.0.0.0:11434
```

Device allow-list for RX 6600 XT:

```text
# /opt/rocm/share/rocdxg/dids.conf
0x73FF,10,3,2
```

Scripts: `scripts/wire-ollama-wsl.sh`, `scripts/wsl-rocm-env.sh`, `scripts/install-ollama-rocm-wsl.sh`.

## Verify engines are used

```bash
source /etc/profile.d/aether-rocm.sh
rocminfo | grep -E "Marketing Name:|Compute Unit:|Device Type:"
# Expect GPU agent + Compute Unit: 32 (6600 XT)

ollama run tinyllama "hi"
ollama ps
# PROCESSOR must include GPU — not "100% CPU"

# Windows: Task Manager → GPU → Compute graphs should move
```

Hub discover will recommend the ROCm install when host scan sets `ollama_missing_rocm_libs`.

## AetherStack layout (who uses CUs)

```
Windows browser / VS Code
        │
        ▼
 Docker: Open WebUI :3000 · LiteLLM :4000 · Hub :8766 · Redis
        │  (no AMD CUs inside containers by default)
        ▼
 host.docker.internal:11434
        │
        ▼
 WSL Ollama  +  ROCm HIP runners  +  DXG
        │
        ▼
 RX 6600 XT compute units (HSA)
```

## Related

- [WSL-AMD-GPU.md](./WSL-AMD-GPU.md) — enablement history / limitations  
- [GPU-NVIDIA.md](./GPU-NVIDIA.md) / [GPU-INTEL.md](./GPU-INTEL.md) — other vendors  
- Combos `private_local` / `inline_fable` — route work to local Ollama once GPU works  
