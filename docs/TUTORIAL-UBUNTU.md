# AetherStack on Ubuntu (native)

Works on **Ubuntu 22.04 / 24.04** (and most Debian-family desktops with Docker).

## Quick start

```bash
# 1) Docker Engine + Compose plugin
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# log out and back in (or newgrp docker)

# 2) Ollama on the host (GPU-friendly)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b

# 3) AetherStack
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
cp .env.example .env
nano .env   # optional API keys

chmod +x start.sh stop.sh
./start.sh
```

Then open **http://localhost:3000**.

Stop:

```bash
./stop.sh
```

---

## Desktop “click to start”

1. File manager → AetherStack folder  
2. Right-click `start.sh` → **Properties** → allow **Execute**  
3. Double-click → **Run in Terminal**  

Or create a desktop launcher (`~/.local/share/applications/aetherstack.desktop`):

```ini
[Desktop Entry]
Name=AetherStack
Comment=Start AetherStack LLM control plane
Exec=bash -c 'cd %s && ./start.sh; read -p "Press Enter..."'
# Replace path:
# Exec=bash -c 'cd /home/YOU/aetherstack && ./start.sh; read -p "Press Enter..."'
Terminal=true
Type=Application
Categories=Network;Development;
```

---

## AMD GPU on Ubuntu (native)

Best path for Radeon: **host Ollama + ROCm**, not GPU-in-Docker (unless you know ROCm devices).

```bash
# After ROCm works (rocminfo shows your GPU):
ollama serve
# In another terminal:
./start.sh
```

Optional ROCm Ollama **container** (needs `/dev/kfd` + `/dev/dri`):

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml --profile with-ollama-container up -d
```

For many RDNA2 cards set in `.env`:

```env
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

---

## NVIDIA GPU on Ubuntu

Host Ollama usually auto-detects CUDA.  
Or enable the NVIDIA Container Toolkit and use GPU containers as documented by Ollama/NVIDIA.

---

## URLs

| Service | URL |
|---------|-----|
| Chat | http://localhost:3000 |
| LiteLLM | http://localhost:4000/v1 |
| Ollama | http://localhost:11434 |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `permission denied` on docker | `newgrp docker` or re-login after `usermod -aG docker` |
| `host.docker.internal` issues | Compose already sets `extra_hosts: host-gateway` |
| Firewall | Allow localhost ports 3000/4000 for your user session |
| SELinux/AppArmor rare blocks | Check `docker compose logs` |

---

## Update

```bash
cd aetherstack
git pull
docker compose pull
./start.sh
```
