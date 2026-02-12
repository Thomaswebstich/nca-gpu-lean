# nca-gpu-lean Deployment Status

## Latest Release: LEAN-V11
- **Repo:** `nca-gpu-lean` / `nca-gpu-lean-ultra`
- **Docker Image:** `ghcr.io/thomaswebstich/nca-gpu-lean:v11`
- **Base Image:** `nvidia/opengl:1.2-glvnd-runtime-ubuntu22.04` (Designed for Headless EGL)

## GPU vs. Host Environment
This image is **GPU-Ready**, meaning it contains all necessary client-side libraries (`libglvnd`, `vulkan`, `ffmpeg-nvenc`) to utilize an NVIDIA GPU.

However, the hosting provider (e.g., RunPod) MUST mount the host driver libraries (`libEGL_nvidia.so`, `libGLX_nvidia.so`) into the container at runtime.

### Current Status on RunPod (Standard Templates)
- **Problem:** RunPod standard templates mount Compute Drivers (CUDA) but often skip Graphics Drivers (EGL/GLX).
- **Symptom:** `nvidia-smi` works, but `eglinfo` shows only Mesa (Software).
- **Result:** Direct GPU rendering degrades to Software Rendering.

### Solution: `smart_render.py`
We have included a "Smart Render" script that automatically detects the environment capabilities at runtime.

1.  **Checks for Drivers:** Runs `ldconfig -p | grep libEGL_nvidia`.
2.  **If Drivers Found (e.g. Salad, Local):** 
    - Enables `EGL` backend.
    - Renders at 1080p (Hardware Accelerated).
    - Encodes with `h264_nvenc` (Hardware Accelerated).
3.  **If Drivers Missing (e.g. RunPod):**
    - Falls back to `SwiftShader` (Software).
    - Renders at 720p (CPU Optimized).
    - Encodes with `libx264` (CPU Optimized).

This allows you to deploy the **same image** anywhere. It will perform maximally on properly configured hosts (Salad/Vast.ai) and reliably on constrained hosts (RunPod).

## Usage
Copy the content of `smart_render.py` into your n8n workflows. Verify you provide the S3 Environment Variables.
