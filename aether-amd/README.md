# Aether AMD compute adapter (userspace)

This is **not** a Windows kernel display/GPU driver and **not** a replacement for AMD Adrenalin or ROCm.

It is a **userspace adapter** that:

1. Detects AMD **compute engines** (CUs) via ROCm/`rocminfo` / DXG  
2. Ensures Ollama loads the **HIP/ROCm** runner (so those CUs run LLM kernels)  
3. Ships **device profiles** (e.g. RX 6600 XT → gfx + dids + HSA overrides)  
4. Exposes a small API used by Aether Hub discover / auto-install  

## Driver stack (who owns what)

```text
┌─────────────────────────────────────────────────────────┐
│  AetherStack (LiteLLM, Hub, combos)                     │  app
├─────────────────────────────────────────────────────────┤
│  Ollama + libggml-hip / ROCm runners                    │  LLM runtime
├─────────────────────────────────────────────────────────┤
│  Aether AMD adapter (this folder)                       │  glue / profiles
├─────────────────────────────────────────────────────────┤
│  ROCm HSA + librocdxg (WSL)  or  amdgpu+kfd (Linux)     │  compute runtime
├─────────────────────────────────────────────────────────┤
│  Windows: AMD Adrenalin (DXCore)  ·  Linux: amdgpu      │  OS/vendor driver
└─────────────────────────────────────────────────────────┘
```

Writing a new **kernel** driver for Radeon would require AMD/Microsoft signing, years of work, and is out of scope.  
If engines are idle, fix **layers 2–3** (Ollama ROCm + adapter profiles), not reinvent Adrenalin.

## Quick use (Debian WSL)

```bash
# Probe CUs + backend
python3 /mnt/d/llm/stack/aether-amd/probe.py

# Apply profile + install ROCm Ollama if missing
sudo bash /mnt/d/llm/stack/aether-amd/ensure-backend.sh

# Or from Windows:
#   wsl -d Debian -- bash -lc 'sudo bash /mnt/d/llm/stack/aether-amd/ensure-backend.sh'
```

## Device profiles

JSON under [`profiles/`](./profiles/) — chip ID, gfx, HSA override, dids line, notes.

| Profile | GPU | Chip ID | CUs (ref) |
|---------|-----|---------|-----------|
| `navi23-rx6600xt` | RX 6600 XT | 0x73FF | 32 |

## Files

| Path | Role |
|------|------|
| `probe.py` | Report engines + whether Ollama can use them |
| `ensure-backend.sh` | Install ROCm Ollama + apply systemd/env + dids |
| `profiles/*.json` | Per-GPU compute profile |
| `dids/` | Snippets for `/opt/rocm/share/rocdxg/dids.conf` |
