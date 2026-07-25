# AMD compute (ROCm / HIP / DXG)

Local Radeon inference uses GPU **compute units (CUs)** through **ROCm/HSA**. Display drivers alone do not run LLM kernels. CUDA-only Ollama builds do not use AMD CUs.

## Scope of this repository

| Layer | Provider | In this repo |
|-------|----------|--------------|
| Kernel / display / DXCore | AMD Adrenalin (Windows), amdgpu (Linux) | Not shipped |
| ROCDXG / HSA in WSL | librocdxg + ROCm | Install/configure scripts |
| LLM HIP kernels | Ollama ROCm package (`libggml` HIP) | Force-install path for WSL |
| Device profiles, dids, env, probes | `aether-amd/` userspace adapter | Shipped |

**Not included:** signed kernel GPU driver.  
**Included:** userspace adapter — profiles, dids, probe, ensure-backend.

```bash
python3 aether-amd/probe.py
sudo bash aether-amd/ensure-backend.sh
```

---

## Compute units (example)

| Field | RX 6600 XT |
|-------|------------|
| Marketing name | AMD Radeon RX 6600 XT |
| ISA / gfx | gfx1032 (Navi 23); HIP override often **gfx1030** |
| Compute units | **32** |
| Wavefront | 32 |
| Windows access | WSL2 `/dev/dxg` + librocdxg + ROCm HSA |
| Linux bare metal | `/dev/kfd` + `/dev/dri` + ROCm |

| Observation | Meaning |
|-------------|---------|
| `rocminfo` Agent GPU + `Compute Unit: 32` | HSA sees the engines |
| `ollama ps` → `100% CPU` | LLM kernels not on GPU |

---

## WSL: CPU fallback cause

1. Stock `install.sh` pulls `ollama-linux-amd64-rocm` only when `lspci` reports AMD.  
2. Under WSL + ROCDXG the GPU often does not appear as PCI amdgpu.  
3. Install keeps CUDA / Vulkan / CPU runners → VRAM 0 → CPU inference.

**Corrective procedure:**

```bash
# Debian WSL
sudo bash /mnt/d/llm/stack/aether-amd/ensure-backend.sh
python3 /mnt/d/llm/stack/aether-amd/probe.py

# Lower-level
sudo bash /mnt/d/llm/stack/scripts/install-ollama-rocm-wsl.sh
bash /mnt/d/llm/stack/scripts/amd-compute-status.sh
```

Windows (elevated host path):

```powershell
.\scripts\auto-install.ps1 -Yes -IncludeElevated
```

---

## Required environment (systemd / Ollama)

```bash
HSA_ENABLE_DXG_DETECTION=1
HSA_OVERRIDE_GFX_VERSION=10.3.0    # RDNA2 consumer cards
LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib
HIP_VISIBLE_DEVICES=0
ROCR_VISIBLE_DEVICES=0
OLLAMA_HOST=0.0.0.0:11434
```

Device allow-list example (RX 6600 XT):

```text
# /opt/rocm/share/rocdxg/dids.conf
0x73FF,10,3,2
```

Scripts: `scripts/wire-ollama-wsl.sh`, `scripts/wsl-rocm-env.sh`, `scripts/install-ollama-rocm-wsl.sh`.

---

## Verification

```bash
source /etc/profile.d/aether-rocm.sh
rocminfo | grep -E "Marketing Name:|Compute Unit:|Device Type:"
# Expect GPU agent + Compute Unit count for the card

ollama run tinyllama "hi"
ollama ps
# PROCESSOR includes GPU — not 100% CPU
```

Windows: Task Manager → GPU → compute graphs active during run.

Hub discover surfaces `ollama_missing_rocm_libs` when host scan reports the gap.

---

## Runtime path

```text
Client (VS Code / browser)
  → Docker: WebUI :3000 · LiteLLM :4000 · Hub :8766 · Redis
  → host.docker.internal:11434
  → WSL/host Ollama + ROCm HIP runners
  → Radeon CUs (HSA)
```

Docker control plane does not own AMD CUs by default.

---

## Related

- [WSL-AMD-GPU.md](./WSL-AMD-GPU.md)  
- [GPU-NVIDIA.md](./GPU-NVIDIA.md) · [GPU-INTEL.md](./GPU-INTEL.md)  
- Combos `private_local` / `inline_fable` bind work to local Ollama once GPU path is verified  
