"""
STAGE 1-A  –  Extract raw CSV from MinIO (S3-compatible object store).
"""

import io
import logging

import pandas as pd
from minio import Minio

logger = logging.getLogger(__name__)


def extract_from_minio(
    endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    object_name: str,
    secure: bool = False,
) -> pd.DataFrame:
    """Download a CSV object from MinIO and return it as a DataFrame."""
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    logger.info("Downloading s3://%s/%s from MinIO", bucket, object_name)
    response = client.get_object(bucket, object_name)
    raw_bytes = response.read()
    response.close()
    response.release_conn()

    df = pd.read_csv(io.BytesIO(raw_bytes))
    logger.info("Extracted %d rows, %d columns", len(df), len(df.columns))
    return df
