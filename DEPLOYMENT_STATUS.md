# nca-gpu-lean Status (V10)

## Current State
- **Repo:** `nca-gpu-lean-ultra` (Cloned from `nca-gpu-lean` V10 state)
- **Image:** `ghcr.io/thomaswebstich/nca-gpu-lean-ultra:v10` OR `...lean:v10`
- **Base Image:** `nvidia/cuda:11.8.0-runtime-ubuntu22.04`
- **Drivers:** NVIDIA Drivers are successfully mounted (`nvidia-smi` works).
- **Rendering:** Uses **SwiftShader (CPU)** fallback. Xvfb/GLX constraints prevent direct GPU usage for Headless Chromium currently.
- **Encoding:** Uses **libx264 (CPU)**. NVENC access exits with code 218 (likely permission/path issue).
- **Performance:** ~3.5 FPS at 720p.

## How to Run (Safe Mode)
Use the "Safe Mode" n8n script which forces:
- Software Rendering (Standard Chromium)
- CPU Encoding (libx264)
- 720p Resolution
- 2s Duration (to avoid 100s Cloudflare timeout)

## Future Optimizations
1. **Enable EGL/GPU:** Requires modifying Dockerfile to include `libnvidia-egl-wayland1` and ensuring `EGL_ICD` json points to NVIDIA.
2. **Async Execution:** To support long renders (>100s), `app.py` must be upgraded to support async/background jobs.
