#!/bin/bash
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export DEBIAN_FRONTEND=noninteractive

echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/7.2.4 noble main" \
  | sudo tee /etc/apt/sources.list.d/rocm.list

sudo apt-get update

# Remove debian rocminfo / older hsa if present
sudo apt-get remove -y rocminfo libhsa-runtime64-1 2>/dev/null || true

# Install ROCm 7.2.x HSA stack (pulls versioned packages)
sudo apt-get install -y hsa-rocr rocm-core rocminfo 2>&1 | tail -40

# Ensure librocdxg still present under /opt/rocm
if [ ! -e /opt/rocm/lib/librocdxg.so ]; then
  if [ -f /opt/rocm-librocdxg-pkg/lib/librocdxg.so.1.2.1 ]; then
    sudo mkdir -p /opt/rocm/lib /opt/rocm/share/rocdxg
    sudo cp -a /opt/rocm-librocdxg-pkg/lib/librocdxg.so* /opt/rocm/lib/
    sudo cp -a /opt/rocm-librocdxg-pkg/share/rocdxg/* /opt/rocm/share/rocdxg/ 2>/dev/null || true
  else
    # reinstall deb if needed
    cd /tmp
    curl -fsSL -L -o rocdxg.deb \
      "https://github.com/ROCm/librocdxg/releases/download/v1.2.1/rocdxg-roct_1.2.1_amd64.deb"
    sudo dpkg -i rocdxg.deb || true
  fi
fi

printf '%s\n' '0x73FF,10,3,2' | sudo tee /opt/rocm/share/rocdxg/dids.conf
sudo ldconfig || true

ls -la /opt/rocm /opt/rocm/lib/librocdxg* /opt/rocm/lib/libhsa-runtime64* 2>&1 | head -30
echo "ROCm package versions:"
dpkg -l | grep -iE 'hsa-rocr|rocm-core|rocdxg|rocminfo' || true
