"""Content-addressed Artifact storage on an S3-compatible object store."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

import boto3

from benchmark.config import require_env


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    s3_uri: str
    size_bytes: int


class ArtifactStore:
    """Puts/gets content-addressed blobs in one S3-compatible bucket."""

    def __init__(self) -> None:
        self._bucket = require_env("RUNENGINE_S3_BUCKET")
        self._client = boto3.client(
            "s3",
            endpoint_url=require_env("RUNENGINE_S3_ENDPOINT_URL"),
            aws_access_key_id=require_env("RUNENGINE_S3_ACCESS_KEY"),
            aws_secret_access_key=require_env("RUNENGINE_S3_SECRET_KEY"),
        )

    def ensure_bucket(self) -> None:
        """Create the configured bucket if it doesn't exist yet (dev convenience)."""
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if self._bucket not in existing:
            self._client.create_bucket(Bucket=self._bucket)

    def put(self, data: bytes, *, content_type: str) -> StoredArtifact:
        """Store `data` under its sha256 digest; re-storing identical bytes is a no-op."""
        digest = sha256(data).hexdigest()
        key = f"sha256/{digest}"
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )
        return StoredArtifact(
            sha256=digest, s3_uri=f"s3://{self._bucket}/{key}", size_bytes=len(data)
        )

    def get(self, sha256_digest: str) -> bytes:
        """Fetch a previously stored blob by its sha256 digest."""
        response = self._client.get_object(Bucket=self._bucket, Key=f"sha256/{sha256_digest}")
        return response["Body"].read()
