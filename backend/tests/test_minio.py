from __future__ import annotations

from pathlib import Path

import pytest

from backend.utils.minio import MinioClient, download_object


class _FakeObject:
    def __init__(self, object_name: str) -> None:
        self.object_name = object_name


class FakeMinio:
    def __init__(self) -> None:
        self.storage: dict[str, dict[str, bytes]] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.storage

    def make_bucket(self, bucket: str) -> None:
        self.storage.setdefault(bucket, {})

    def fput_object(self, bucket: str, object_name: str, file_path: str) -> None:
        self.storage.setdefault(bucket, {})[object_name] = Path(file_path).read_bytes()

    def fget_object(self, bucket: str, object_name: str, file_path: str) -> None:
        Path(file_path).write_bytes(self.storage[bucket][object_name])

    def remove_object(self, bucket: str, object_name: str) -> None:
        self.storage.setdefault(bucket, {}).pop(object_name, None)

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = True):
        for object_name in self.storage.get(bucket, {}):
            if object_name.startswith(prefix):
                yield _FakeObject(object_name)

    def list_buckets(self):
        return list(self.storage)


@pytest.mark.asyncio
async def test_minio_upload_list_delete(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello minio", encoding="utf-8")

    client = MinioClient(client=FakeMinio())
    object_url = client.upload_file(source, "test-bucket", "folder/source.txt")

    assert object_url == "minio://test-bucket/folder/source.txt"
    assert client.list_files("test-bucket", prefix="folder") == ["folder/source.txt"]

    downloaded = client.download_file("test-bucket", "folder/source.txt", tmp_path / "downloaded.txt")
    assert downloaded.read_text(encoding="utf-8") == "hello minio"
    assert client.delete_file("test-bucket", "folder/source.txt") is True


def test_download_object_supports_local_paths(tmp_path: Path) -> None:
    source = tmp_path / "local.txt"
    source.write_text("local", encoding="utf-8")

    assert download_object(str(source)) == str(source)
