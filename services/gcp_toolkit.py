import os
import json
import logging
from google.oauth2 import service_account
from google.cloud import storage
from google.cloud.run_v2 import JobsClient, RunJobRequest
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)

# Lazy-initialized GCS client — avoids network calls at import time
_gcs_client = None
_gcs_initialized = False


def _get_gcs_client():
    """Lazy-initialize the GCS client on first use."""
    global _gcs_client, _gcs_initialized
    if _gcs_initialized:
        return _gcs_client

    _gcs_initialized = True
    GCP_SA_CREDENTIALS = os.getenv('GCP_SA_CREDENTIALS')

    if not GCP_SA_CREDENTIALS:
        logger.info("GCP credentials not found. GCS uploads will not be available.")
        return None

    GCS_SCOPES = ['https://www.googleapis.com/auth/devstorage.full_control']

    try:
        credentials_info = json.loads(GCP_SA_CREDENTIALS)
        gcs_credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=GCS_SCOPES
        )
        _gcs_client = storage.Client(credentials=gcs_credentials)
        logger.info("GCS client initialized successfully.")
        return _gcs_client
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        return None


def upload_to_gcs(file_path, bucket_name=None):
    client = _get_gcs_client()
    if not client:
        raise ValueError("GCS client is not initialized. Check GCP_SA_CREDENTIALS.")

    if not bucket_name:
        bucket_name = os.getenv('GCP_BUCKET_NAME')

    try:
        logger.info(f"Uploading file to Google Cloud Storage: {file_path}")
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(os.path.basename(file_path))
        blob.upload_from_filename(file_path)
        logger.info(f"File uploaded successfully to GCS: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        logger.error(f"Error uploading file to GCS: {e}")
        raise


def trigger_cloud_run_job(job_name, location="us-central1", overrides=None):
    json_str = os.environ.get("GCP_SA_CREDENTIALS")
    if not json_str:
        raise ValueError("GCP_SA_CREDENTIALS environment variable not set.")

    credentials_info = json.loads(json_str)
    credentials = service_account.Credentials.from_service_account_info(credentials_info)

    client = JobsClient(credentials=credentials)

    project_id = credentials_info.get("project_id")
    job_path = f"projects/{project_id}/locations/{location}/jobs/{job_name}"

    request = RunJobRequest(
        name=job_path,
        overrides=overrides
    )

    try:
        operation = client.run_job(request=request)
        return {
            "operation_name": operation.operation.name,
            "execution_name": operation.metadata.name,
            "job_submitted": True
        }
    except GoogleAPIError as e:
        return {
            "job_submitted": False,
            "error": str(e)
        }
