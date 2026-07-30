# NVIDIA CUDA support (AetherStack)

Use a local NVIDIA GPU for inference while AetherStack provides the chat UI and multi-model gateway.

| Path | How |
|------|-----|
| Host Ollama + CUDA | Preferred for most setups |
| Ollama container + NVIDIA runtime | `docker-compose.nvidia.yml` |
| vLLM / TensorRT-LLM | Advanced; not in the default stack |

---

## Path A — Host Ollama

1. Install [NVIDIA drivers](https://www.nvidia.com/drivers).  
2. Install [Ollama](https://ollama.com).  
3. Start AetherStack (`start.bat` / `./start.sh`).  
4. Check GPU:

```bash
ollama run llama3.1:8b "hi"
# Windows: Task Manager → GPU → CUDA
# Linux: nvidia-smi
```

Compose services talk to Ollama at `http://host.docker.internal:11434`.

---

## Path B — Ollama GPU container

**Linux** — install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html), then:

```bash
docker compose -f docker-compose.yml -f docker-compose.nvidia.yml \
  --profile with-ollama-container up -d
```

**Windows 11 + Docker Desktop**

1. Enable WSL2 backend.  
2. Install an NVIDIA driver that supports WSL.  
3. Docker Desktop → Settings → Resources → enable GPU.  
4. Same compose command as above.

---

## Verify

```bash
docker compose exec ollama nvidia-smi   # if using container profile
curl http://127.0.0.1:11434/api/tags
```
