import asyncio, os, shutil, subprocess, time, sys
from datetime import datetime
from playwright.async_api import async_playwright
import boto3

# --- SAFE PARAMETERS (CPU RENDERING) ---
# Use these settings to ensure reliability and avoid timeouts
FPS = 30
DURATION = 2
WIDTH = 1280
HEIGHT = 720
total_frames = FPS * DURATION

async def render_video():
    print("--- STARTING SAFE CPU RENDER ---", flush=True)

    # Clean previous sessions
    subprocess.run("pkill Xvfb", shell=True)
    subprocess.run("rm /tmp/.X99-lock", shell=True)

    # Start Xvfb
    xvfb = subprocess.Popen(['Xvfb', ':99', '-screen', '0', f'{WIDTH}x{HEIGHT}x24'])
    os.environ["DISPLAY"] = ":99"

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    frames_dir = f'/tmp/frames_{timestamp}'
    os.makedirs(frames_dir, exist_ok=True)
    output_path = f"/tmp/render_{timestamp}.mp4"

    try:
        async with async_playwright() as p:
            print(f"🚀 Launching Chromium ({WIDTH}x{HEIGHT})...", flush=True)
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    f'--window-size={WIDTH},{HEIGHT}',
                    # No GPU flags -> Forces reliable SwiftShader (CPU)
                ]
            )
            page = await browser.new_page(viewport={'width': WIDTH, 'height': HEIGHT})
            
            # --- THREE.JS SCENE SETUP ---
            html = """<!DOCTYPE html>
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
                const renderer = new THREE.WebGLRenderer({ antialias: true });
                renderer.setSize(1280, 720);
                renderer.toneMapping = THREE.ACESFilmicToneMapping;
                renderer.toneMappingExposure = 1.0;
                document.body.appendChild(renderer.domElement);

                const scene = new THREE.Scene();
                const camera = new THREE.PerspectiveCamera(50, 1280/720, 1, 500);
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
            
            await page.set_content(html)
            
            print("⏳ Waiting for HDR...", flush=True)
            await page.wait_for_function("window.__isLoaded === true", timeout=30000)
            print("✅ Assets loaded. starting capture...", flush=True)

            for i in range(total_frames):
                await page.evaluate('window.__advanceFrame()')
                await page.screenshot(path=f"{frames_dir}/f{i:04d}.png")
                if i % 10 == 0: print(f"Captured {i}/{total_frames}", flush=True)
                
            await browser.close()
            
    finally:
        xvfb.terminate()

    # Encode with CPU (libx264)
    print("Encoding with libx264...", flush=True)
    subprocess.run([
        'ffmpeg', '-y', 
        '-framerate', str(FPS),
        '-i', f'{frames_dir}/f%04d.png',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', output_path
    ], check=True)

    # Upload (Using inserted variables)
    print("Uploading...", flush=True)
    s3 = boto3.client('s3',
        endpoint_url='${S3_ENDPOINT}',
        aws_access_key_id='${AWS_ACCESS_KEY}',
        aws_secret_access_key='${AWS_SECRET_KEY}'
    )
    s3_key = f"tests/safe_mode_render_{timestamp}.mp4"
    s3.upload_file(output_path, '${S3_BUCKET}', s3_key, ExtraArgs={'ACL': 'public-read'})
    
    shutil.rmtree(frames_dir)
    os.remove(output_path)
    
    return f"SUCCESS: ${S3_ENDPOINT}/${S3_BUCKET}/{s3_key}"

# Run Sync
# (In n8n you would wrap this in loop.run_until_complete)
if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(render_video())
