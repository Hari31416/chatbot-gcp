from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from google.cloud import storage

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
    """Google Cloud Storage implementation replacing Azure Blob Storage."""

    def __init__(
        self,
        client: storage.Client,
        bucket_name: str,
        prefix: str,
        signing_service_account: str | None = None,
    ) -> None:
        self._client = client
        self._bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self._bucket = self._client.bucket(bucket_name)
        
        # Verify/ensure bucket exists or log a warning
        try:
            # We don't try to create bucket programmatically for production security,
            # but we initialize the reference.
            logger.info("StorageService initialised bucket=%s prefix=%s", bucket_name, prefix)
        except Exception as exc:
            logger.warning("Failed to verify GCS bucket: %s", exc)

        self.signing_service_account = signing_service_account

    def _blob_key(self, key: str) -> str:
        clean_key = key.lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{clean_key}"
        return clean_key

    def upload_image(self, key: str, data: bytes, mime_type: str) -> UploadResult:
        logger.debug("Uploading image key=%s mime_type=%s size=%d", key, mime_type, len(data))
        blob_key = self._blob_key(key)
        blob = self._bucket.blob(blob_key)
        blob.upload_from_string(data, content_type=mime_type)
        logger.info("Image uploaded key=%s size_bytes=%d", blob_key, len(data))
        return UploadResult(s3_key=key, mime_type=mime_type, size_bytes=len(data))

    def upload_bytes(self, key: str, data: bytes, mime_type: str) -> None:
        logger.debug("Uploading raw bytes key=%s mime_type=%s size=%d", key, mime_type, len(data))
        blob_key = self._blob_key(key)
        blob = self._bucket.blob(blob_key)
        blob.upload_from_string(data, content_type=mime_type)
        logger.info("Raw bytes uploaded key=%s size_bytes=%d", blob_key, len(data))

    def download_bytes(self, key: str) -> tuple[bytes, str]:
        """Download blob and return (data, content_type)."""
        blob_key = self._blob_key(key)
        blob = self._bucket.blob(blob_key)
        
        # In GCS, we have to reload the blob metadata to get the content_type
        blob.reload()
        data = blob.download_as_bytes()
        content_type = blob.content_type or "application/octet-stream"
        return data, content_type

    def delete_blob(self, key: str) -> None:
        """Delete a blob by key."""
        blob_key = self._blob_key(key)
        blob = self._bucket.blob(blob_key)
        blob.delete()
        logger.info("Blob deleted key=%s", blob_key)

    def generate_sas_url(self, key: str, expiration_seconds: int = 3600) -> str:
        """Generate a GCS signed URL (equivalent to Azure SAS URL)."""
        try:
            blob_key = self._blob_key(key)
            blob = self._bucket.blob(blob_key)

            if self.signing_service_account:
                import google.auth
                from google.auth import impersonated_credentials
                source_credentials, _ = google.auth.default()
                signing_credentials = impersonated_credentials.Credentials(
                    source_credentials=source_credentials,
                    target_principal=self.signing_service_account,
                    target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
                    lifetime=min(expiration_seconds, 3600),
                )
                return blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=expiration_seconds),
                    method="GET",
                    credentials=signing_credentials,
                )

            # Fallback to standard signed URL generation (requires private key or ADC credentials)
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expiration_seconds),
                method="GET",
            )
        except Exception as exc:
            fallback = f"https://storage.googleapis.com/{self._bucket_name}/{self._blob_key(key)}"
            logger.warning(
                "Failed to generate GCS signed URL key=%s; using fallback url=%s. Error: %s",
                key, fallback, exc,
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
