# Phase 2 — Blob Storage Migration

> Replace Amazon S3 with Azure Blob Storage for file uploads, presigned URLs, and staging area.

---

## Goal

Swap all S3 client operations in the backend to Azure Blob Storage. This affects image uploads, presigned URL generation, RAG staging uploads, and the worker's file download/delete operations.

---

## Current State (AWS)

### Files Using S3

| File                      | S3 Operations                                              | Purpose                            |
| :------------------------ | :--------------------------------------------------------- | :--------------------------------- |
| `app/dependencies.py`     | `boto3.client("s3")` client creation                       | Dependency injection               |
| `app/services/storage.py` | `put_object`, `generate_presigned_url`                     | Image upload + signed URL          |
| `app/services/rag.py`     | `put_object`, `delete_object`                              | RAG raw file upload to S3, cleanup |
| `app/worker.py`           | `get_object`, `delete_object`                              | Download staging files, cleanup    |
| `app/settings.py`         | `s3_bucket_name`, `s3_endpoint_url`, `s3_force_path_style` | Configuration                      |

### S3 Key Patterns

| Pattern                                        | Usage                               |
| :--------------------------------------------- | :---------------------------------- |
| `{conversation_id}/{message_id}.{ext}`         | User image attachments              |
| `staging/{user_id}/{document_id}/{filename}`   | RAG document staging (triggers SQS) |
| `rag-raw-uploads/{user_id}/{document_id}{ext}` | Temporary Textract input            |

---

## Target State (Azure)

### Azure SDK

Replace `boto3` S3 client with `azure-storage-blob`:

```
pip install azure-storage-blob
```

### Container Layout

Single storage account with multiple **containers** (Azure's equivalent of S3 prefixes):

| Azure Container | Maps to AWS               | Purpose                               |
| :-------------- | :------------------------ | :------------------------------------ |
| `uploads`       | `chatbot-uploads-*` root  | User image attachments                |
| `staging`       | `staging/` prefix         | RAG document staging area             |
| `rag-temp`      | `rag-raw-uploads/` prefix | Temporary Document Intelligence input |

---

## Code Changes

### 2.1 Update `pyproject.toml`

```diff
 dependencies = [
   "fastapi>=0.115.0",
   "uvicorn>=0.30.0",
   "pydantic-settings>=2.4.0",
   "python-multipart>=0.0.9",
-  "boto3>=1.43.8",
+  "boto3>=1.43.8",          # Keep during migration — used by other services
+  "azure-storage-blob>=12.20.0",
   "litellm>=1.41.0",
   "mangum>=0.17.0",
   "PyJWT>=2.8.0",
   "cryptography>=42.0.0",
 ]
```

### 2.2 Update `app/settings.py`

Add Azure Blob Storage settings alongside existing S3 settings:

```python
# ── Azure Blob Storage (Phase 2) ──
azure_storage_connection_string: str | None = Field(
    default=None, validation_alias="AZURE_STORAGE_CONNECTION_STRING"
)
azure_storage_account_name: str | None = Field(
    default=None, validation_alias="AZURE_STORAGE_ACCOUNT_NAME"
)
azure_storage_container_name: str = Field(
    default="uploads", validation_alias="AZURE_STORAGE_CONTAINER_NAME"
)
```

### 2.3 Rewrite `app/services/storage.py`

Replace the S3-based `StorageService` with an Azure Blob-backed implementation:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from azure.storage.blob import (
    BlobClient,
    BlobSasPermissions,
    BlobServiceClient,
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
    blob_name: str  # was s3_key
    mime_type: str
    size_bytes: int


class StorageService:
    """Azure Blob Storage implementation replacing the S3 client."""

    def __init__(
        self,
        connection_string: str,
        container_name: str,
    ) -> None:
        self._service_client = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container_name
        # Ensure the container exists
        self._container_client = self._service_client.get_container_client(container_name)
        try:
            self._container_client.get_container_properties()
        except Exception:
            self._container_client.create_container()
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
        return UploadResult(blob_name=key, mime_type=mime_type, size_bytes=len(data))

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
            account_key = self._service_client.credential.account_key

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
```

> [!NOTE]
> The `UploadResult.s3_key` field is renamed to `blob_name`. All callers in `routes.py` must be updated to use the new field name.

### 2.4 Update `app/dependencies.py`

Replace the S3 client factory with a Blob Storage factory:

```python
# Remove:
#   get_s3_client() -> boto3.client("s3", ...)
#
# Add:
@lru_cache
def get_storage() -> StorageService:
    settings = get_settings()
    return StorageService(
        connection_string=settings.azure_storage_connection_string,
        container_name=settings.azure_storage_container_name,
    )
```

### 2.5 Update `app/services/rag.py`

Replace S3 `put_object` / `delete_object` with `StorageService.upload_bytes` / `StorageService.delete_blob`:

```diff
- self.s3_client = s3_client
- self.s3_bucket_name = s3_bucket_name
+ self.storage = storage  # StorageService instance
```

The `ingest_binary_document` method should use `self.storage.upload_bytes()` and `self.storage.delete_blob()` instead of raw boto3 calls.

### 2.6 Update `app/worker.py`

Replace `s3_client.get_object()` with `StorageService.download_bytes()` and `s3_client.delete_object()` with `StorageService.delete_blob()`.

### 2.7 Update Callers in `app/api/routes.py`

Search for `s3_key` references and update to `blob_name`. Update `generate_presigned_url` → `generate_sas_url`.

---

## Bicep Module: `infra/modules/storage.bicep`

```bicep
param location string
param environmentName string
param resourceToken string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'stchatbot${resourceToken}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  tags: { 'azd-env-name': environmentName }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource uploadsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'uploads'
  properties: { publicAccess: 'None' }
}

resource stagingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'staging'
  properties: { publicAccess: 'None' }
}

// Lifecycle management: auto-delete blobs after 7 days
resource lifecyclePolicy 'Microsoft.Storage/storageAccounts/managementPolicies@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-staging-uploads'
          type: 'Lifecycle'
          definition: {
            actions: {
              baseBlob: { delete: { daysAfterModificationGreaterThan: 7 } }
            }
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['staging/', 'rag-temp/']
            }
          }
        }
      ]
    }
  }
}

output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
```

---

## Local Development

For local development, use **Azurite** (Azure Storage emulator) instead of MinIO:

```bash
# Install Azurite
npm install -g azurite

# Run Azurite (Blob only)
azurite-blob --blobHost 0.0.0.0 --blobPort 10000

# Connection string for local dev:
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
```

---

## Verification

- [ ] `StorageService` can upload an image and return a valid `UploadResult`
- [ ] `generate_sas_url` returns a working signed URL
- [ ] `download_bytes` correctly retrieves uploaded content
- [ ] `delete_blob` removes the blob
- [ ] All existing tests pass with the new storage backend
- [ ] Local dev works with Azurite

---

## Next Phase

→ [Phase 3 — Cosmos DB](./PHASE_3_COSMOS_DB.md)
