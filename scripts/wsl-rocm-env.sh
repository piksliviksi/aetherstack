# AetherStack / ROCm on WSL — source from /etc/profile.d or ~/.bashrc
export HSA_ENABLE_DXG_DETECTION=1
export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/opt/rocm/bin${PATH:+:$PATH}"
# RDNA2 consumer cards often need this for some ROCm apps:
# export HSA_OVERRIDE_GFX_VERSION=10.3.0
