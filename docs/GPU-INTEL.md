# Intel GPU support (AetherStack)

**Partially feasible**, but **not as smooth as NVIDIA CUDA** and different from **AMD ROCm**.

| Stack | Status | Notes |
|-------|--------|--------|
| **Intel Arc (discrete) / Xe** | Experimental | Drivers + OpenVINO / SYCL / Level Zero |
| **Intel integrated (UHD/Iris/Xe-iGPU)** | Mixed | Often works for small models; VRAM shared with system RAM |
| **Ollama + Intel** | Limited / evolving | Check current Ollama release notes; Vulkan/IPEX paths vary by OS |
| **OpenVINO** | Mature for Intel | Best for production Intel inference; separate from default Ollama path |
| **IPEX-LLM / bigdl-llm** | Community | Good for some Arc/CPU hybrids |
| **Docker + Intel GPU** | Possible on Linux | Needs `/dev/dri` + `intel-gpu-tools` / oneAPI container device plugins |

AetherStack’s **control plane** (Open WebUI, LiteLLM, Redis) is GPU-agnostic. Only the **local inference engine** cares about Intel.

---

## Recommended approaches

### 1. Host Ollama (try first)

```bash
# Linux: up-to-date mesa + intel-media-driver
# Then:
ollama pull llama3.2:3b
ollama run llama3.2:3b "test"
```

If Ollama uses GPU on your Intel stack, keep AetherStack pointing at host `:11434` — **no compose changes required**.

### 2. OpenVINO Model Server (advanced)

Run OpenVINO as an OpenAI-compatible or custom backend, then add a LiteLLM entry in `litellm_config.yaml`. Heavier setup; best when you need official Intel optimizations.

### 3. llama.cpp / IPEX builds

Use a Vulkan or SYCL build of llama.cpp as a server, then point LiteLLM/Ollama-compatible clients at it.

---

## Docker sketch (Linux only, experimental)

```yaml
# Not enabled by default — example only
services:
  ollama-intel:
    image: ollama/ollama:latest   # or a community Intel-optimized image
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - video
      - render
    ports:
      - "11434:11434"
```

Success depends on kernel, driver (`i915` / `xe`), and whether the image includes Intel compute libraries.

---

## Feasibility verdict

| Goal | Feasible? |
|------|-----------|
| Use AetherStack UI/gateway with Intel machine | **Yes** (always) |
| Local models on Intel GPU with zero pain | **Maybe** — try host Ollama first |
| Same first-class support as NVIDIA in AetherStack | **Not yet** — document + optional profiles only |
| Ship a guaranteed Intel Docker Extension path | **No** without per-SKU testing |

**Bottom line:** Intel is **feasible as best-effort host inference**. We do **not** claim first-class CUDA-equivalent Docker GPU support for Intel in this repo. Contributions with tested Arc/iGPU compose overlays are welcome.
