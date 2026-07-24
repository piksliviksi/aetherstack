#!/bin/bash
export PATH="/opt/rocm/bin:/usr/bin:/bin"
export HSA_ENABLE_DXG_DETECTION=1
export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib"

echo "=== tools ==="
which rocminfo
ls -la /opt/rocm/bin/rocminfo 2>/dev/null || true
echo "HSA_ENABLE_DXG_DETECTION=$HSA_ENABLE_DXG_DETECTION"
ls -la /dev/dxg
cat /opt/rocm/share/rocdxg/dids.conf 2>/dev/null || echo "no dids"

echo "=== strace opens ==="
strace -e openat /opt/rocm/bin/rocminfo 2>&1 | grep -iE 'dxg|rocdxg|dids|kfd|amdgpu|dxcore|librocdxg' | head -50

echo "=== rocminfo full ==="
/opt/rocm/bin/rocminfo 2>&1 | head -120
echo "exit=$?"
