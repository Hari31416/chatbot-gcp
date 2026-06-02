# Phase 6 — Secret Manager Migration

> Replace Azure Key Vault runtime reads with Google Secret Manager and Cloud Run secret mounts.

---

## Goal

Store third-party API keys in Secret Manager. Prefer Cloud Run secret injection over fetching secrets inside request handlers.

---

## Current State (Azure)

`backend/app/dependencies.py` creates an Azure `SecretClient` and retrieves Key Vault values such as:

- `litellm-api-key`
- `litellm-vision-api-key`
- `clerk-secret-key`
- `cosmos-key`
- `storage-connection-string`
- Document Intelligence endpoint and key

---

## Target State (GCP)

Only third-party credentials remain secrets:

| Secret                      | Purpose                         |
| :-------------------------- | :------------------------------ |
| `litellm-api-key`           | Text model gateway              |
| `litellm-vision-api-key`    | Vision model gateway            |
| `litellm-embedding-api-key` | Embedding endpoint, if separate |

Firestore, GCS, Document AI, and Firebase Admin use ADC with service-account IAM. Do not create cloud database passwords or service-account key files.

---

## Code Changes

### 6.1 Remove Azure Key Vault SDK

```diff
-  "azure-identity>=1.17.0",
-  "azure-keyvault-secrets>=4.8.0",
```

### 6.2 Remove Runtime Vault Reads

Delete `get_keyvault_client()` and `get_secret()` from `backend/app/dependencies.py`. Read secrets from environment variables already supported by `Settings`:

```python
def get_llm_client() -> LlmClient:
    settings = get_settings()
    return LlmClient(
        model=settings.litellm_model,
        api_key=settings.litellm_api_key,
        base_url=settings.litellm_base_url,
    )
```

Cloud Run resolves Secret Manager values into environment variables when a revision starts. This avoids secret-manager network calls on user requests.

---

## Terraform Module

Create `gcp-infra/modules/secrets/main.tf`:

```hcl
variable "project_id" { type = string }
variable "secret_ids" { type = set(string) }

resource "google_secret_manager_secret" "app" {
  for_each  = var.secret_ids
  secret_id = each.value

  replication {
    auto {}
  }
}

output "secret_ids" {
  value = { for key, secret in google_secret_manager_secret.app : key => secret.secret_id }
}
```

Add secret values manually after provisioning:

```bash
printf '%s' "$LITELLM_API_KEY" |
  gcloud secrets versions add litellm-api-key --data-file=-
```

Do not pass actual secret values through Terraform variables or state.

---

## IAM

Grant `roles/secretmanager.secretAccessor` only to:

- `chatbot-api` Cloud Run service account
- `chatbot-worker` Cloud Run service account

---

## Cost Control

Keep active versions limited. Disable or destroy old versions after rotation. Secret Manager includes a small free allowance for active versions and access operations.

Reference: [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)

---

## Verification

- [ ] API and worker start with Secret Manager-backed environment variables.
- [ ] Application service accounts can access only required secrets.
- [ ] No Azure Key Vault imports remain.
- [ ] No secret values appear in Terraform state, Git, or deployment logs.

---

## Next Phase

→ [Phase 7 — Cloud Run API](./PHASE_7_CLOUD_RUN_API.md)
