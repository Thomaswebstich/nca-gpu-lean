# NCA-GPU-LEAN — Streamlined GPU toolkit
# Only registers the endpoints needed for the lean build:
#   - /health (startup probe)
#   - /v1/ffmpeg/compose
#   - /v1/code/execute/python
#   - /v1/toolkit/test, /v1/toolkit/authenticate
#   - /v1/toolkit/job/status, /v1/toolkit/jobs/status
#   - /v1/s3/upload, /v1/gcp/upload

from flask import Flask, request, jsonify
from queue import Queue
from services.webhook import send_webhook
import threading
import uuid
import os
import logging
import time
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

print("🚀 NCA-GPU-LEAN STARTUP: LOADING SYSTEM...")

from version import BUILD_NUMBER
from app_utils import log_job_status

MAX_QUEUE_LENGTH = int(os.environ.get('MAX_QUEUE_LENGTH', 0))


def create_app():
    app = Flask(__name__)

    # Create a queue to hold tasks
    task_queue = Queue()
    queue_id = id(task_queue)

    # ------------------------------------------------------------------ #
    # HEALTH CHECK — must respond immediately for the startup probe
    # ------------------------------------------------------------------ #
    @app.route('/health')
    def health():
        return "healthy", 200

    # ------------------------------------------------------------------ #
    # Queue processing
    # ------------------------------------------------------------------ #
    def process_queue():
        while True:
            job_id, data, task_func, queue_start_time = task_queue.get()
            queue_time = time.time() - queue_start_time
            run_start_time = time.time()
            pid = os.getpid()

            log_job_status(job_id, {
                "job_status": "running",
                "job_id": job_id,
                "queue_id": queue_id,
                "process_id": pid,
                "response": None
            })

            response = task_func()
            run_time = time.time() - run_start_time
            total_time = time.time() - queue_start_time

            response_data = {
                "endpoint": response[1],
                "code": response[2],
                "id": data.get("id"),
                "job_id": job_id,
                "response": response[0] if response[2] == 200 else None,
                "message": "success" if response[2] == 200 else response[0],
                "pid": pid,
                "queue_id": queue_id,
                "run_time": round(run_time, 3),
                "queue_time": round(queue_time, 3),
                "total_time": round(total_time, 3),
                "queue_length": task_queue.qsize(),
                "build_number": BUILD_NUMBER
            }

            log_job_status(job_id, {
                "job_status": "done",
                "job_id": job_id,
                "queue_id": queue_id,
                "process_id": pid,
                "response": response_data
            })

            if data.get("webhook_url") and data.get("webhook_url") != "":
                send_webhook(data.get("webhook_url"), response_data)

            task_queue.task_done()

    threading.Thread(target=process_queue, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Queue task decorator
    # ------------------------------------------------------------------ #
    def queue_task(bypass_queue=False):
        def decorator(f):
            def wrapper(*args, **kwargs):
                data = request.json if request.is_json else {}
                job_id = data.pop('_cloud_job_id', None) or str(uuid.uuid4())
                pid = os.getpid()
                start_time = time.time()

                # Cloud Run Job mode
                if os.environ.get("CLOUD_RUN_JOB"):
                    execution_name = os.environ.get("CLOUD_RUN_EXECUTION", "gcp_job")
                    log_job_status(job_id, {
                        "job_status": "running",
                        "job_id": job_id,
                        "queue_id": execution_name,
                        "process_id": pid,
                        "response": None
                    })
                    response = f(job_id=job_id, data=data, *args, **kwargs)
                    run_time = time.time() - start_time
                    response_obj = {
                        "endpoint": response[1],
                        "code": response[2],
                        "id": data.get("id"),
                        "job_id": job_id,
                        "response": response[0] if response[2] == 200 else None,
                        "message": "success" if response[2] == 200 else response[0],
                        "run_time": round(run_time, 3),
                        "queue_time": 0,
                        "total_time": round(run_time, 3),
                        "pid": pid,
                        "queue_id": execution_name,
                        "queue_length": 0,
                        "build_number": BUILD_NUMBER
                    }
                    log_job_status(job_id, {
                        "job_status": "done",
                        "job_id": job_id,
                        "queue_id": execution_name,
                        "process_id": pid,
                        "response": response_obj
                    })
                    if data.get("webhook_url") and data.get("webhook_url") != "":
                        send_webhook(data.get("webhook_url"), response_obj)
                    return response_obj, response[2]

                # GCP Cloud Run Job delegation (optional)
                disable_by_env = os.environ.get("DISABLE_CLOUD_JOB", "").lower() in ["true", "1"]
                disable_cloud = (
                    (disable_by_env and data.get("disable_cloud_job") is not False) or
                    data.get("disable_cloud_job") is True
                )

                if os.environ.get("GCP_JOB_NAME") and data.get("webhook_url") and not disable_cloud:
                    try:
                        from services.gcp_toolkit import trigger_cloud_run_job
                        cloud_payload = data.copy()
                        cloud_payload['_cloud_job_id'] = job_id
                        overrides = {
                            'container_overrides': [{
                                'env': [
                                    {'name': 'GCP_JOB_PATH', 'value': request.path},
                                    {'name': 'GCP_JOB_PAYLOAD', 'value': json.dumps(cloud_payload)},
                                ]
                            }],
                            'task_count': 1
                        }
                        response = trigger_cloud_run_job(
                            job_name=os.environ.get("GCP_JOB_NAME"),
                            location=os.environ.get("GCP_JOB_LOCATION", "us-central1"),
                            overrides=overrides
                        )
                        if not response.get("job_submitted"):
                            raise Exception(f"GCP job trigger failed: {response}")
                        execution_name = response.get("execution_name", "")
                        gcp_queue_id = execution_name.split('/')[-1] if execution_name else "gcp_job"
                        response_obj = {
                            "code": 200,
                            "id": data.get("id"),
                            "job_id": job_id,
                            "message": response,
                            "job_name": os.environ.get("GCP_JOB_NAME"),
                            "location": os.environ.get("GCP_JOB_LOCATION", "us-central1"),
                            "pid": pid,
                            "queue_id": gcp_queue_id,
                            "build_number": BUILD_NUMBER
                        }
                        log_job_status(job_id, {
                            "job_status": "submitted",
                            "job_id": job_id,
                            "queue_id": gcp_queue_id,
                            "process_id": pid,
                            "response": response_obj
                        })
                        return response_obj, 200
                    except Exception as e:
                        error_response = {
                            "code": 500,
                            "id": data.get("id"),
                            "job_id": job_id,
                            "message": f"GCP Cloud Run Job trigger failed: {str(e)}",
                            "pid": pid,
                            "queue_id": "gcp_job",
                            "build_number": BUILD_NUMBER
                        }
                        log_job_status(job_id, {
                            "job_status": "failed",
                            "job_id": job_id,
                            "queue_id": "gcp_job",
                            "process_id": pid,
                            "response": error_response
                        })
                        return error_response, 500

                # Bypass queue or synchronous execution
                elif bypass_queue or 'webhook_url' not in data:
                    log_job_status(job_id, {
                        "job_status": "running",
                        "job_id": job_id,
                        "queue_id": queue_id,
                        "process_id": pid,
                        "response": None
                    })
                    response = f(job_id=job_id, data=data, *args, **kwargs)
                    run_time = time.time() - start_time
                    response_obj = {
                        "endpoint": response[1],
                        "code": response[2],
                        "id": data.get("id"),
                        "job_id": job_id,
                        "response": response[0] if response[2] == 200 else None,
                        "message": "success" if response[2] == 200 else response[0],
                        "run_time": round(run_time, 3),
                        "queue_time": 0,
                        "total_time": round(run_time, 3),
                        "pid": pid,
                        "queue_id": queue_id,
                        "queue_length": task_queue.qsize(),
                        "build_number": BUILD_NUMBER
                    }
                    log_job_status(job_id, {
                        "job_status": "done",
                        "job_id": job_id,
                        "queue_id": queue_id,
                        "process_id": pid,
                        "response": response_obj
                    })
                    return response_obj, response[2]

                # Queue the task
                else:
                    if MAX_QUEUE_LENGTH > 0 and task_queue.qsize() >= MAX_QUEUE_LENGTH:
                        error_response = {
                            "code": 429,
                            "id": data.get("id"),
                            "job_id": job_id,
                            "message": f"MAX_QUEUE_LENGTH ({MAX_QUEUE_LENGTH}) reached",
                            "pid": pid,
                            "queue_id": queue_id,
                            "queue_length": task_queue.qsize(),
                            "build_number": BUILD_NUMBER
                        }
                        log_job_status(job_id, {
                            "job_status": "done",
                            "job_id": job_id,
                            "queue_id": queue_id,
                            "process_id": pid,
                            "response": error_response
                        })
                        return error_response, 429

                    log_job_status(job_id, {
                        "job_status": "queued",
                        "job_id": job_id,
                        "queue_id": queue_id,
                        "process_id": pid,
                        "response": None
                    })
                    task_queue.put((job_id, data, lambda: f(job_id=job_id, data=data, *args, **kwargs), start_time))
                    return {
                        "code": 202,
                        "id": data.get("id"),
                        "job_id": job_id,
                        "message": "processing",
                        "pid": pid,
                        "queue_id": queue_id,
                        "max_queue_length": MAX_QUEUE_LENGTH if MAX_QUEUE_LENGTH > 0 else "unlimited",
                        "queue_length": task_queue.qsize(),
                        "build_number": BUILD_NUMBER
                    }, 202
            return wrapper
        return decorator

    app.queue_task = queue_task

    # ------------------------------------------------------------------ #
    # EXPLICIT BLUEPRINT REGISTRATION — Only the lean endpoints
    # ------------------------------------------------------------------ #
    logger.info("Registering lean blueprints...")

    # Core: FFmpeg Compose
    from routes.v1.ffmpeg.ffmpeg_compose import v1_ffmpeg_compose_bp
    app.register_blueprint(v1_ffmpeg_compose_bp)
    logger.info("  ✅ /v1/ffmpeg/compose")

    # Core: Execute Python
    from routes.v1.code.execute.execute_python import v1_code_execute_bp
    app.register_blueprint(v1_code_execute_bp)
    logger.info("  ✅ /v1/code/execute/python")

    # Toolkit: Test, Auth, Job Status
    from routes.v1.toolkit.test import v1_toolkit_test_bp
    app.register_blueprint(v1_toolkit_test_bp)
    logger.info("  ✅ /v1/toolkit/test")

    from routes.v1.toolkit.authenticate import v1_toolkit_auth_bp
    app.register_blueprint(v1_toolkit_auth_bp)
    logger.info("  ✅ /v1/toolkit/authenticate")

    from routes.v1.toolkit.job_status import v1_toolkit_job_status_bp
    app.register_blueprint(v1_toolkit_job_status_bp)
    logger.info("  ✅ /v1/toolkit/job/status")

    from routes.v1.toolkit.jobs_status import v1_toolkit_jobs_status_bp
    app.register_blueprint(v1_toolkit_jobs_status_bp)
    logger.info("  ✅ /v1/toolkit/jobs/status")

    # Storage: S3 & GCP upload
    from routes.v1.s3.upload import v1_s3_upload_bp
    app.register_blueprint(v1_s3_upload_bp)
    logger.info("  ✅ /v1/s3/upload")

    from routes.v1.gcp.upload import v1_gcp_upload_bp
    app.register_blueprint(v1_gcp_upload_bp)
    logger.info("  ✅ /v1/gcp/upload")

    logger.info(f"✅ Registered 8 lean blueprints (build {BUILD_NUMBER})")

    return app

app = create_app()