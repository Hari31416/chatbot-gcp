from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    ContentSettings,
    generate_blob_sas,
)

logger = logging.getLogger(__name__)

_MIME_EXTENSION_MAP = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


@dataclass(frozen=True)
class UploadResult:
    s3_key: str  # Kept for backward compatibility with frontend/routes
    mime_type: str
    size_bytes: int

    @property
    def blob_name(self) -> str:
        return self.s3_key


class StorageService:
    """Azure Blob Storage implementation replacing the S3 client."""

    def __init__(
        self,
        connection_string: str,
        container_name: str,
    ) -> None:
        self._service_client = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container_name
        self._container_client = self._service_client.get_container_client(container_name)
        try:
            self._container_client.get_container_properties()
        except Exception:
            try:
                self._container_client.create_container()
            except Exception:
                logger.warning("Could not create container %s (might already exist or read-only)", container_name)
        logger.info("StorageService initialised container=%s", container_name)

    def upload_image(self, key: str, data: bytes, mime_type: str) -> UploadResult:
        logger.debug("Uploading image key=%s mime_type=%s size=%d", key, mime_type, len(data))
        blob_client = self._container_client.get_blob_client(key)
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=mime_type),
        )
        logger.info("Image uploaded key=%s size_bytes=%d", key, len(data))
        return UploadResult(s3_key=key, mime_type=mime_type, size_bytes=len(data))

    def upload_bytes(self, key: str, data: bytes, mime_type: str) -> None:
        logger.debug("Uploading raw bytes key=%s mime_type=%s size=%d", key, mime_type, len(data))
        blob_client = self._container_client.get_blob_client(key)
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=mime_type),
        )
        logger.info("Raw bytes uploaded key=%s size_bytes=%d", key, len(data))

    def download_bytes(self, key: str) -> tuple[bytes, str]:
        """Download blob and return (data, content_type)."""
        blob_client = self._container_client.get_blob_client(key)
        download = blob_client.download_blob()
        data = download.readall()
        content_type = download.properties.content_settings.content_type or "application/octet-stream"
        return data, content_type

    def delete_blob(self, key: str) -> None:
        """Delete a blob by key."""
        blob_client = self._container_client.get_blob_client(key)
        blob_client.delete_blob()
        logger.info("Blob deleted key=%s", key)

    def generate_sas_url(self, key: str, expiration_seconds: int = 3600) -> str:
        """Generate a SAS URL (replaces S3 presigned URL)."""
        try:
            blob_client = self._container_client.get_blob_client(key)
            account_name = self._service_client.account_name
            # If standard devstoreaccount1 key is used, SAS token generation is done locally using standard credentials
            account_key = None
            if hasattr(self._service_client.credential, "account_key"):
                account_key = self._service_client.credential.account_key
            elif "AccountKey=" in self._service_client.url:
                # Attempt to extract account key from connection string
                pass

            # Fallback for local emulator or missing credential properties
            if not account_key and account_name == "devstoreaccount1":
                account_key = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="

            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self._container_name,
                blob_name=key,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(seconds=expiration_seconds),
            )
            return f"{blob_client.url}?{sas_token}"
        except Exception:
            fallback = f"https://{self._service_client.account_name}.blob.core.windows.net/{self._container_name}/{key}"
            logger.warning(
                "Failed to generate SAS URL key=%s; using fallback url=%s",
                key, fallback, exc_info=True,
            )
            return fallback

    def generate_presigned_url(self, key: str, expiration_seconds: int = 3600) -> str:
        """Alias for generate_sas_url to preserve API compatibility."""
        return self.generate_sas_url(key, expiration_seconds)


def extension_for_mime(mime_type: str) -> str:
    extension = _MIME_EXTENSION_MAP.get(mime_type)
    if not extension:
        raise ValueError(f"Unsupported mime type: {mime_type}")
    return extension


def build_image_key(conversation_id: str, message_id: str, extension: str) -> str:
    return f"{conversation_id}/{message_id}.{extension}"
