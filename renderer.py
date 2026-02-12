import os, subprocess, shutil, sys
from playwright.async_api import async_playwright
import boto3
from datetime import datetime

# Default Demo HTML (Torus Knot)
DEMO_HTML = """<!DOCTYPE html>
<html lang="en">
    <head>
        <title>Three.js UltraHDR</title>
        <style>body { margin: 0; overflow: hidden; background: black; }</style>
        <script type="importmap">
            { "imports": { "three": "https://unpkg.com/three@0.169.0/build/three.module.js", "three/addons/": "https://unpkg.com/three@0.169.0/examples/jsm/" } }
        </script>
    </head>
    <body>
        <script type="module">
            import * as THREE from 'three';
            import { UltraHDRLoader } from 'three/addons/loaders/UltraHDRLoader.js';

            window.__isLoaded = false;
            try { init(); } catch (e) { console.error(e); }

            function init() {
                const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
                renderer.setSize(window.innerWidth, window.innerHeight);
                renderer.toneMapping = THREE.ACESFilmicToneMapping;
                renderer.toneMappingExposure = 1.0;
                document.body.appendChild(renderer.domElement);

                const scene = new THREE.Scene();
                const camera = new THREE.PerspectiveCamera(50, window.innerWidth/window.innerHeight, 1, 500);
                camera.position.set(0, 0, -6);
                camera.lookAt(0,0,0);

                const mesh = new THREE.Mesh(new THREE.TorusKnotGeometry(1, 0.4, 128, 128), new THREE.MeshStandardMaterial({ roughness: 0, metalness: 1 }));
                scene.add(mesh);

                new UltraHDRLoader().load('https://threejs.org/examples/textures/equirectangular/spruit_sunrise_2k.hdr.jpg', (tex) => {
                    tex.mapping = THREE.EquirectangularReflectionMapping;
                    scene.background = tex;
                    scene.environment = tex;
                    window.__isLoaded = true;
                    console.log("HDR Loaded");
                });

                window.__advanceFrame = () => {
                    mesh.rotation.y += 0.05;
                    renderer.render(scene, camera);
                };
            }
        </script>
    </body>
</html>"""

async def check_gpu_availability():
    """Detects if NVIDIA Drivers (Rendering) and NVENC (Encoding) are active."""
    status = {"render": False, "encode": False, "mode": "CPU"}
    
    print("--- GPU DIAGNOSTIC ---", flush=True)
    
    # 1. Update LD Cache (Required for detecting runtime-mounted drivers)
    try:
        subprocess.run("ldconfig", shell=True)
    except: pass

    # 2. Check Renderer (EGL)
    try:
        res = subprocess.run("ldconfig -p | grep libEGL_nvidia", shell=True, stdout=subprocess.PIPE)
        if res.returncode == 0:
            status["render"] = True
            status["mode"] = "GPU"
            print("✅ GPU RENDERER DETECTED (libEGL_nvidia found)", flush=True)
        else:
            print("⚠️ GPU RENDERER MISSING (libEGL_nvidia not found). using Software Fallback.", flush=True)
    except Exception as e:
        print(f"Diagnostic Error: {e}", flush=True)

    # 3. Check Encoder (NVENC)
    try:
        res = subprocess.run("ffmpeg -encoders 2>/dev/null | grep h264_nvenc", shell=True, stdout=subprocess.PIPE)
        if res.returncode == 0:
            status["encode"] = True
            print("✅ GPU ENCODER DETECTED (h264_nvenc found)", flush=True)
        else:
            print("⚠️ GPU ENCODER MISSING. Using libx264.", flush=True)
    except: pass
    
    return status

async def render_video(
    s3_endpoint, s3_bucket, aws_key, aws_secret,
    html_content=None,
    frames_dir_prefix="/tmp/frames",
    fps=30, duration=2, 
    width=None, height=None
):
    """
    Main entry point for n8n Scripts.
    Automatically handles GPU/CPU detection.
    """
    
    # Detect Environment Mode
    status = await check_gpu_availability()
    use_gpu = status["render"]
    
    # Resolve Resolution
    if width is None: width = 1920 if use_gpu else 1280
    if height is None: height = 1080 if use_gpu else 720
    
    print(f"--- STARTING RENDER ({status['mode']} MODE: {width}x{height}) ---", flush=True)

    # Clean display locks
    subprocess.run("pkill Xvfb", shell=True) 
    subprocess.run("rm /tmp/.X99-lock", shell=True)

    # Start Xvfb
    xvfb = subprocess.Popen(['Xvfb', ':99', '-screen', '0', f'{width}x{height}x24'])
    os.environ["DISPLAY"] = ":99"

    # Setup GPU Env
    if use_gpu:
        os.environ["NVIDIA_VISIBLE_DEVICES"] = "all"
        os.environ["NVIDIA_DRIVER_CAPABILITIES"] = "all"

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    frames_dir = f'{frames_dir_prefix}_{timestamp}'
    os.makedirs(frames_dir, exist_ok=True)
    output_path = f"/tmp/render_{timestamp}.mp4"

    try:
        args = [
            '--no-sandbox', 
            '--disable-setuid-sandbox',
            f'--window-size={width},{height}'
        ]
        
        if use_gpu:
            args.extend([
                '--ignore-gpu-blocklist',
                '--enable-gpu-rasterization',
                '--enable-zero-copy',
                '--enable-webgl',
                '--use-gl=egl',
                '--enable-features=Vulkan'
            ])
            
        async with async_playwright() as p:
            print("🚀 Launching Browser...", flush=True)
            browser = await p.chromium.launch(headless=False, args=args)
            page = await browser.new_page(viewport={'width': width, 'height': height})
            
            # Use provided HTML or Demo
            content_to_load = html_content if html_content else DEMO_HTML
            await page.set_content(content_to_load)
            
            print("⏳ Loading Assets...", flush=True)
            try:
                await page.wait_for_function("window.__isLoaded === true", timeout=30000)
            except:
                print("Warning: HDR Load Timeout (or custom HTML lacking __isLoaded), proceeding...", flush=True)
                
            print(f"📸 Capturing {fps * duration} Frames...", flush=True)
            for i in range(fps * duration):
                await page.evaluate('window.__advanceFrame()')
                await page.screenshot(path=f"{frames_dir}/f{i:04d}.png")
            
            await browser.close()
            
    finally:
        xvfb.terminate()
        
    # --- ENCODING ---
    cmd = ['ffmpeg', '-y', '-framerate', str(fps), '-i', f'{frames_dir}/f%04d.png']
    
    if status["encode"]:
        print("Encoding with NVENC (Hardware)...", flush=True)
        cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-b:v', '5M'])
    else:
        print("Encoding with libx264 (Software)...", flush=True)
        cmd.extend(['-c:v', 'libx264', '-preset', 'ultrafast'])
        
    cmd.extend(['-pix_fmt', 'yuv420p', output_path])
    
    subprocess.run(cmd, check=True)
    
    # --- UPLOAD ---
    print("Uploading to S3...", flush=True)
    s3 = boto3.client('s3', endpoint_url=s3_endpoint, aws_access_key_id=aws_key, aws_secret_access_key=aws_secret)
    s3_key = f"tests/renderer_{timestamp}.mp4"
    s3.upload_file(output_path, s3_bucket, s3_key, ExtraArgs={'ACL': 'public-read'})
    
    # Cleanup
    shutil.rmtree(frames_dir)
    os.remove(output_path)
    
    final_url = f"{s3_endpoint}/{s3_bucket}/{s3_key}"
    print(f"SUCCESS: {final_url}", flush=True)
    return final_url
