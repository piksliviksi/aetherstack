# AMD compute (Vulkan / ROCm / HIP / DXG)

Use the runtime appropriate to the host. On Windows, host Ollama with experimental Vulkan is the practical path for GPUs outside Ollama's Windows ROCm matrix. On native Linux, use supported ROCm or Vulkan. WSL ROCm/DXG is an experimental fallback, not the default.

The RX 6600 XT reference host was validated on 2026-07-29 with Ollama 0.32.4 host Vulkan: `llama3.1:8b` loaded 100% into GPU memory and generated successfully. WSL ROCm detected all 32 compute units but did not complete a reliable HTTP inference run, so AetherStack leaves that WSL service disabled on this machine.

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
| Windows access | Host Vulkan (validated here); WSL2 ROCDXG is experimental |
| Linux bare metal | `/dev/kfd` + `/dev/dri` + ROCm |

| Observation | Meaning |
|-------------|---------|
| `rocminfo` Agent GPU + `Compute Unit: 32` | HSA sees the engines |
| `ollama ps` → `100% CPU` | LLM kernels not on GPU |

---

## Windows host Vulkan (recommended for this RX 6600 XT)

Set `OLLAMA_VULKAN=1` for the Ollama server, keep AetherStack's `OLLAMA_BASE_URL` pointed at that host endpoint, then verify after a real prompt:

```powershell
$env:OLLAMA_HOST='http://127.0.0.1:11435' # use your configured port
ollama ps
# PROCESSOR must show 100% GPU or an intentional CPU/GPU split
```

Vulkan support is experimental in Ollama. Treat successful model output plus `ollama ps` GPU residency as the runtime gate; device discovery alone is insufficient.

Current support references: [Ollama hardware support](https://docs.ollama.com/gpu) and [AMD ROCm WSL compatibility](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/wsl/wsl_compatibility.html).

## WSL: experimental ROCm path

1. Stock `install.sh` pulls `ollama-linux-amd64-rocm` only when `lspci` reports AMD.  
2. Under WSL + ROCDXG the GPU often does not appear as PCI amdgpu.  
3. Install keeps CUDA / Vulkan / CPU runners → VRAM 0 → CPU inference.

This path is useful for experiments and supported hardware, but RX 6600 XT is outside AMD's current WSL support matrix. Do not automatically replace a working Windows Vulkan runtime with it.

**Manual procedure:**

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

## Runtime paths

```text
Client (VS Code / browser)
  → Docker: WebUI :3000 · LiteLLM :4000 · Hub :8766 · Redis
  → host.docker.internal:11434
  → Windows host Ollama + Vulkan, or native Linux Ollama + ROCm/Vulkan
  → Radeon GPU
```

Docker control plane does not own AMD CUs by default.

---

## Related

- [WSL-AMD-GPU.md](./WSL-AMD-GPU.md)  
- [GPU-NVIDIA.md](./GPU-NVIDIA.md) · [GPU-INTEL.md](./GPU-INTEL.md)  
- Combos `private_local` / `inline_fable` bind work to local Ollama once GPU path is verified  
