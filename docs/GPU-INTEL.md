# Intel GPU support (AetherStack)

Run AetherStack’s control plane (Open WebUI, LiteLLM, Redis) on any machine; use an Intel GPU for **local inference** via host tools.

| Setup | Approach |
|-------|----------|
| **Intel Arc / Xe discrete** | Drivers + Ollama, OpenVINO, SYCL / Level Zero, or IPEX-LLM |
| **Intel integrated (UHD / Iris / Xe-iGPU)** | Shared system memory; prefer smaller models |
| **Ollama** | Host install; check current Ollama docs for your GPU |
| **OpenVINO** | Strong path for optimized Intel inference |
| **IPEX-LLM / bigdl-llm** | Community stacks for Arc / hybrid |
| **Docker + Intel GPU (Linux)** | Pass `/dev/dri`; use a suitable image and drivers (`i915` / `xe`) |

---

## Host Ollama

```bash
# Linux: up-to-date mesa + intel-media-driver as needed
ollama pull llama3.2:3b
ollama run llama3.2:3b "test"
```

Keep AetherStack pointed at host Ollama on `:11434` — no compose change required when Ollama runs on the host.

---

## OpenVINO Model Server

Run OpenVINO as a backend, then add a LiteLLM entry in `litellm_config.yaml` if you expose an OpenAI-compatible endpoint.

---

## llama.cpp / IPEX

Use a Vulkan or SYCL build of llama.cpp as a server, then point LiteLLM or OpenAI-compatible clients at it.

---

## Docker example (Linux)

```yaml
# Optional profile — enable when your host exposes Intel render nodes
services:
  ollama-intel:
    image: ollama/ollama:latest
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - video
      - render
    ports:
      - "11434:11434"
```

Requires correct kernel drivers and an image that can use Intel compute.
