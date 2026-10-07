from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from dms_core.config import Settings

MISSING_CODES = {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}


def blob_key(sha256: str) -> str:
    return f"blobs/{sha256}"


class S3BlobStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bucket = settings.s3_bucket
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.s3_endpoint,
                region_name="us-east-1",
                aws_access_key_id=self.settings.s3_access_key,
                aws_secret_access_key=self.settings.s3_secret_key,
                config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
            )
        return self._client

    def put(self, sha256: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=blob_key(sha256),
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )

    def get(self, sha256: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=blob_key(sha256))
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in MISSING_CODES:
                raise KeyError(sha256) from error
            raise
        return response["Body"].read()

    def exists(self, sha256: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=blob_key(sha256))
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in MISSING_CODES:
                return False
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise
        return True

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = error.response.get("Error", {}).get("Code")
            if status != 404 and code not in MISSING_CODES:
                raise
        try:
            self.client.create_bucket(Bucket=self.bucket)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise
