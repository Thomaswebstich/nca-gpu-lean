# NCA-GPU-LEAN utilities

from flask import request, jsonify, current_app
from functools import wraps
import jsonschema
import os
import json
import time
from config import LOCAL_STORAGE_PATH

def validate_payload(schema):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not request.json:
                return jsonify({"message": "Missing JSON in request"}), 400

            # Remove internal fields before validation
            validation_data = request.json.copy()
            validation_data.pop('_cloud_job_id', None)
            validation_data.pop('disable_cloud_job', None)

            try:
                jsonschema.validate(instance=validation_data, schema=schema)
            except jsonschema.exceptions.ValidationError as validation_error:
                return jsonify({"message": f"Invalid payload: {validation_error.message}"}), 400

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_job_status(job_id, data):
    """Log job status to a file in the STORAGE_PATH/jobs folder."""
    jobs_dir = os.path.join(LOCAL_STORAGE_PATH, 'jobs')
    if not os.path.exists(jobs_dir):
        os.makedirs(jobs_dir, exist_ok=True)
    job_file = os.path.join(jobs_dir, f"{job_id}.json")
    with open(job_file, 'w') as f:
        json.dump(data, f, indent=2)

def queue_task_wrapper(bypass_queue=False):
    def decorator(f):
        def wrapper(*args, **kwargs):
            return current_app.queue_task(bypass_queue=bypass_queue)(f)(*args, **kwargs)
        return wrapper
    return decorator