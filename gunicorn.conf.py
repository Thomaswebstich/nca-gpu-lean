# NCA-GPU-LEAN Gunicorn Configuration
import os
import json
import requests
import time

bind = "0.0.0.0:8080"
workers = int(os.environ.get("GUNICORN_WORKERS", 1))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 3600))
keepalive = 80
worker_class = "sync"

# Faster startup: preload the app so workers fork from a ready parent
preload_app = True


def on_starting(server):
    """Hook called when Gunicorn starts (before workers)."""
    print("🚀 NCA-GPU-LEAN starting up...")


def when_ready(server):
    """Hook called when Gunicorn server is ready to accept connections."""
    print("✅ NCA-GPU-LEAN is READY and accepting connections on port 8080")

    # If running as a GCP Cloud Run Job, execute the job task
    if os.environ.get("CLOUD_RUN_JOB"):
        import threading
        thread = threading.Thread(target=cloud_run_job_task)
        thread.start()


def cloud_run_job_task():
    """Execute a single job request and shut down."""
    path = os.environ.get("GCP_JOB_PATH")
    payload_str = os.environ.get("GCP_JOB_PAYLOAD")
    api_key = os.environ.get("API_KEY")

    if not (path and payload_str and api_key):
        print("⚠️ Missing required environment variables: GCP_JOB_PATH, GCP_JOB_PAYLOAD, or API_KEY")
        os._exit(1)

    try:
        payload = json.loads(payload_str)
        webhook_url = payload.get("webhook_url")

        print(f"📤 Executing GCP job request to {path}...")
        time.sleep(1)  # Brief delay for server readiness

        response = requests.post(
            f"http://localhost:8080{path}",
            json=payload,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json"
            }
        )

        if response.status_code in [200, 202]:
            print("✅ Job completed successfully")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"❌ Job failed with status {response.status_code}")
            try:
                error_response = response.json() if response.headers.get('content-type') == 'application/json' else {"error": response.text}
            except:
                error_response = {"error": response.text}
            print(json.dumps(error_response, indent=2))

            if webhook_url:
                try:
                    webhook_data = {
                        "code": response.status_code,
                        "id": payload.get("id"),
                        "message": f"Job failed with status {response.status_code}",
                        "error": error_response
                    }
                    print(f"🔔 Sending error webhook to {webhook_url}")
                    webhook_response = requests.post(webhook_url, json=webhook_data)
                    webhook_response.raise_for_status()
                    print("✅ Error webhook sent successfully")
                except Exception as webhook_error:
                    print(f"❌ Failed to send error webhook: {webhook_error}")

    except requests.RequestException as e:
        print(f"❌ Request error: {e}")
        try:
            if webhook_url:
                webhook_data = {
                    "code": 500,
                    "id": payload.get("id"),
                    "message": f"Job request failed: {str(e)}",
                    "error": str(e)
                }
                requests.post(webhook_url, json=webhook_data)
        except:
            pass
        os._exit(1)

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        os._exit(1)

    finally:
        print("🛑 Shutting down...")
        os._exit(0)
