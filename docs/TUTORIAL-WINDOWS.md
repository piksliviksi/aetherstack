# AetherStack on Windows 11

## One-click start

1. Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) and start it once so it finishes setup.
2. Install [Ollama for Windows](https://ollama.com/download) for local models / GPU.
3. Clone or download this repo.
4. Double-click **`start.bat`**.

That script will:

- Create `.env` from `.env.example` if missing  
- Start Docker Desktop if needed  
- Run `docker compose up -d`  
- Open **http://localhost:3000** in your browser  

Double-click **`stop.bat`** to stop the stack.

> If Windows blocks the script: right-click `start.ps1` → Properties → Unblock, or run:
> `powershell -ExecutionPolicy Bypass -File .\start.ps1`

---

## First-time setup

```powershell
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
copy .env.example .env
notepad .env
```

Add any keys you need:

| Variable | Provider |
|----------|----------|
| `XAI_API_KEY` | Grok (xAI) |
| `OPENAI_API_KEY` | GPT / Codex |
| `ANTHROPIC_API_KEY` | Claude |
| `GOOGLE_API_KEY` | Gemini |
| `MISTRAL_API_KEY` | Mistral / Codestral / Pixtral |

Then:

```powershell
.\start.bat
```

Optional local model:

```powershell
ollama pull llama3.1:8b
```

---

## URLs

| Service | URL |
|---------|-----|
| Chat (Open WebUI) | http://localhost:3000 |
| API gateway (LiteLLM) | http://localhost:4000/v1 |
| Ollama (host) | http://localhost:11434 |

LiteLLM API key for clients: the generated value of `LITELLM_MASTER_KEY` in `.env`.

---

## AMD GPU (Radeon) on Windows

Docker on Windows does **not** expose AMD GPUs well. Prefer:

1. **Host Ollama for Windows with Vulkan** (`OLLAMA_VULKAN=1`) for cards outside the Windows ROCm matrix. This is the validated RX 6600 XT path, though Ollama marks Vulkan experimental.
2. Native Linux ROCm/Vulkan for supported hardware.
3. **Ollama inside WSL** with ROCm/DXG only as an opt-in experiment — see [WSL-AMD-GPU.md](./WSL-AMD-GPU.md).

AetherStack containers still run in Docker; only **inference** stays on the host/WSL Ollama.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `docker` not found | Install Docker Desktop; log out/in |
| Docker never ready | Open Docker Desktop manually; wait for “Engine running” |
| Port 3000/4000 in use | Stop other apps or change ports in `docker-compose.yml` |
| Open WebUI can’t see Ollama | Ensure Ollama is running at the `OLLAMA_BASE_URL` port from `.env` |
| Script blocked | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

---

## Update

```powershell
cd aetherstack
git pull
docker compose pull
.\start.bat
```
