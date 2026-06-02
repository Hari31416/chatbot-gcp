# Phase 2 — Cloud Storage Migration

> Replace Azure Blob Storage and SAS URLs with Google Cloud Storage (GCS) and V4 signed URLs.

---

## Goal

Move uploads, staging files, and temporary RAG objects to one private GCS bucket. Preserve the existing logical prefixes so Phase 5 can attach ingestion events only to `staging/`.

---

## Current State (Azure)

| File                              | Azure Dependency                                        |
| :-------------------------------- | :------------------------------------------------------ |
| `backend/app/services/storage.py` | `azure.storage.blob`                                    |
| `backend/app/dependencies.py`     | Key Vault `storage-connection-string`                   |
| `backend/app/settings.py`         | storage account, connection string, and container names |
| `infra/modules/storage.bicep`     | Blob containers, queue, Event Grid, lifecycle rules     |

Azure uses separate containers: `uploads`, `staging`, and `rag-temp`.

---

## Target State (GCP)

Use one private bucket, consistent with the project convention:

```txt
gs://<project-id>-chatbot-dev/
├── uploads/
├── staging/
└── rag-temp/
```

Use Application Default Credentials (ADC) locally and Cloud Run service-account identity in GCP. Do not store service-account JSON keys in `.env`.

---

## Code Changes

### 2.1 Replace the SDK

Update `backend/pyproject.toml`:

```diff
-  "azure-storage-blob>=12.20.0",
+  "google-cloud-storage>=2.18.0",
```

### 2.2 Update Settings

Replace Azure Blob settings in `backend/app/settings.py`:

```python
# ── Google Cloud Storage ──
gcp_project_id: str | None = Field(default=None, validation_alias="GCP_PROJECT_ID")
gcs_bucket_name: str | None = Field(default=None, validation_alias="GCS_BUCKET_NAME")
gcs_uploads_prefix: str = Field(default="uploads", validation_alias="GCS_UPLOADS_PREFIX")
gcs_staging_prefix: str = Field(default="staging", validation_alias="GCS_STAGING_PREFIX")
gcs_rag_temp_prefix: str = Field(default="rag-temp", validation_alias="GCS_RAG_TEMP_PREFIX")
gcs_signing_service_account: str | None = Field(
    default=None,
    validation_alias="GCS_SIGNING_SERVICE_ACCOUNT",
)
```

### 2.3 Rewrite `StorageService`

Replace Blob operations in `backend/app/services/storage.py` with:

```python
from datetime import timedelta

import google.auth
from google.auth import impersonated_credentials
from google.cloud import storage


class StorageService:
    def __init__(
        self,
        client: storage.Client,
        bucket_name: str,
        prefix: str,
        signing_service_account: str | None = None,
    ) -> None:
        self.bucket = client.bucket(bucket_name)
        self.prefix = prefix.strip("/")
        self.signing_service_account = signing_service_account

    def _blob(self, object_name: str) -> storage.Blob:
        return self.bucket.blob(f"{self.prefix}/{object_name.lstrip('/')}")

    def upload_bytes(self, object_name: str, data: bytes, content_type: str) -> str:
        blob = self._blob(object_name)
        blob.upload_from_string(data, content_type=content_type)
        return blob.name

    def download_bytes(self, object_name: str) -> bytes:
        return self._blob(object_name).download_as_bytes()

    def delete(self, object_name: str) -> None:
        self._blob(object_name).delete()

    def create_read_url(self, object_name: str, expires_seconds: int = 3600) -> str:
        if not self.signing_service_account:
            raise RuntimeError("GCS_SIGNING_SERVICE_ACCOUNT is required")
        source_credentials, _ = google.auth.default()
        signing_credentials = impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=self.signing_service_account,
            target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
            lifetime=min(expires_seconds, 3600),
        )
        return self._blob(object_name).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expires_seconds),
            method="GET",
            credentials=signing_credentials,
        )
```

Retain the public `StorageService` method names already used by routes and tests where possible. Adjust the snippet to the current interface rather than changing route contracts.

### 2.4 Update Dependency Providers

In `backend/app/dependencies.py`:

```python
from google.cloud import storage


@lru_cache
def get_storage_client() -> storage.Client:
    settings = get_settings()
    return storage.Client(project=settings.gcp_project_id)


def _storage_for(prefix: str) -> StorageService:
    settings = get_settings()
    if not settings.gcs_bucket_name:
        raise RuntimeError("GCS_BUCKET_NAME is required")
    return StorageService(
        get_storage_client(),
        settings.gcs_bucket_name,
        prefix,
        signing_service_account=settings.gcs_signing_service_account,
    )
```

Provide `get_storage()`, `get_staging_storage()`, and `get_rag_temp_storage()` using their configured prefixes.

### 2.5 Configure URL Signing Without JSON Keys

The Python Storage helper examples that use `Blob.generate_signed_url()` commonly assume a service-account key file. Do **not** add a JSON key file to this project. Enable `iamcredentials.googleapis.com`, impersonate a signing service account as shown above, and grant the caller `iam.serviceAccounts.signBlob` through `roles/iam.serviceAccountTokenCreator` on that signer.

The signer also needs permission to read the objects covered by download URLs. Test this path on Cloud Run and with local ADC because it differs from ordinary GCS uploads.

---

## Terraform Module

Create `gcp-infra/modules/storage/main.tf`:

```hcl
variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }

resource "google_storage_bucket" "uploads" {
  name                        = "${var.project_id}-${var.name_prefix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  lifecycle_rule {
    action { type = "Delete" }
    condition {
      age            = 7
      matches_prefix = ["staging/", "rag-temp/"]
    }
  }
}

output "bucket_name" { value = google_storage_bucket.uploads.name }
```

Wire it into `gcp-infra/main.tf`:

```hcl
module "storage" {
  source      = "./modules/storage"
  project_id  = var.project_id
  region      = var.region
  name_prefix = local.name_prefix
}
```

---

## Local Development

There is no official full-fidelity GCS emulator. Use one of these approaches:

1. Use a dedicated development bucket with ADC.
2. Keep unit tests isolated behind a fake `StorageService`.
3. Optionally use a third-party emulator only for local convenience, never as proof of GCP parity.

```bash
gcloud auth application-default login
export GCS_BUCKET_NAME="<project-id>-chatbot-dev"
```

---

## Cost Note

Cloud Storage Always Free storage is limited to `us-west1`, `us-central1`, and `us-east1`. This plan intentionally keeps the bucket in `asia-south1` for latency and accepts small storage and operation charges. Lifecycle rules limit accumulation.

Reference: [Cloud Storage pricing](https://cloud.google.com/storage/pricing)

Signed URL reference: [V4 signing with Cloud Storage tools](https://cloud.google.com/storage/docs/access-control/signing-urls-with-helpers)

---

## Verification

- [ ] Bucket rejects public access.
- [ ] Upload, download, signed URL, and delete tests pass.
- [ ] `staging/` and `rag-temp/` lifecycle deletion is configured.
- [ ] No service-account JSON key is committed or stored in `.env`.
- [ ] V4 signed URLs are generated through IAM Credentials impersonation and expire as configured.

---

## Next Phase

→ [Phase 3 — Firestore Native Mode](./PHASE_3_FIRESTORE.md)
