from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from backend.core.config import DATA_DIR, get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


class MinioClient:
    def __init__(self, client: Minio | None = None) -> None:
        self.client = client or Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def _ensure_bucket(self, bucket: str) -> None:
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def _download_target(self, bucket: str, object_name: str) -> Path:
        target = DATA_DIR / "minio_cache" / bucket / object_name
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def upload_file(self, file_path: str | Path, bucket: str, object_name: str) -> str:
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(src)
        self._ensure_bucket(bucket)
        self.client.fput_object(bucket, object_name, str(src))
        return f"minio://{bucket}/{object_name}"

    def download_file(self, bucket: str, object_name: str, file_path: str | Path | None = None) -> Path:
        target = Path(file_path) if file_path else self._download_target(bucket, object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.client.fget_object(bucket, object_name, str(target))
        return target

    def delete_file(self, bucket: str, object_name: str) -> bool:
        try:
            self.client.remove_object(bucket, object_name)
            return True
        except S3Error:
            logger.exception("Failed to delete MinIO object %s/%s", bucket, object_name)
            return False

    def list_files(self, bucket: str, prefix: str = "") -> list[str]:
        self._ensure_bucket(bucket)
        return [obj.object_name for obj in self.client.list_objects(bucket, prefix=prefix, recursive=True)]

    def healthcheck(self) -> dict[str, str]:
        self.client.list_buckets()
        return {"status": "ok", "endpoint": settings.minio_endpoint}


minio_client = MinioClient()


def _parse_minio_url(url: str) -> tuple[str, str] | None:
    if not url.startswith("minio://"):
        return None
    parsed = urlparse(url)
    bucket = parsed.netloc
    object_name = parsed.path.lstrip("/")
    if not bucket or not object_name:
        raise ValueError(f"Invalid MinIO URL: {url}")
    return bucket, object_name

async def upload_to_minio(file_path: str | Path, bucket: str, object_name: str) -> str:
    return await asyncio.to_thread(minio_client.upload_file, file_path, bucket, object_name)


async def download_from_minio(bucket: str, object_name: str, file_path: str | Path | None = None) -> Path:
    return await asyncio.to_thread(minio_client.download_file, bucket, object_name, file_path)


def upload_file(file_path: str | Path, bucket: str, object_name: str) -> str:
    return minio_client.upload_file(file_path, bucket, object_name)


def download_object(url: str) -> str:
    parsed = _parse_minio_url(url)
    if parsed is None:
        path = Path(url)
        if not path.exists():
            raise FileNotFoundError(url)
        return str(path)
    bucket, object_name = parsed
    return str(minio_client.download_file(bucket, object_name))
