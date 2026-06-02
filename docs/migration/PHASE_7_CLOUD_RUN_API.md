# Phase 7 — Cloud Run API Migration

> Replace Azure Container Apps and Azure Container Registry with Cloud Run and Artifact Registry.

---

## Goal

Deploy the FastAPI API container to Cloud Run with SSE support, request-based billing, and scale-to-zero behavior.

---

## Current State (Azure)

| Component         | Azure Service                        |
| :---------------- | :----------------------------------- |
| Container hosting | Azure Container Apps                 |
| Image registry    | Azure Container Registry             |
| Ingress           | Container Apps public HTTPS endpoint |
| Identity          | System-assigned managed identity     |

The existing `backend/Dockerfile` and standard uvicorn entrypoint are reusable.

---

## Target State (GCP)

| Component         | GCP Service                             |
| :---------------- | :-------------------------------------- |
| Container hosting | Cloud Run                               |
| Image registry    | Artifact Registry                       |
| Ingress           | Cloud Run public HTTPS URL              |
| Identity          | Dedicated `chatbot-api` service account |

Do not add API Gateway for the PoC. FastAPI verifies Firebase ID tokens, and direct Cloud Run ingress preserves SSE with fewer moving parts.

---

## Terraform Module

Create `gcp-infra/modules/cloud-run/main.tf`:

```hcl
variable "project_id" { type = string }
variable "region" { type = string }
variable "api_image" { type = string }
variable "bucket_name" { type = string }
variable "secret_ids" { type = map(string) }

resource "google_service_account" "api" {
  account_id   = "chatbot-api"
  display_name = "Chatbot API"
}

resource "google_service_account_iam_member" "api_can_sign_as_self" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.api.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name     = "chatbot-api"
  location = var.region

  template {
    service_account = google_service_account.api.email
    timeout         = "300s"

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.api_image
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }

      env { name = "GCP_PROJECT_ID", value = var.project_id }
      env { name = "GCS_BUCKET_NAME", value = var.bucket_name }
      env { name = "GCS_SIGNING_SERVICE_ACCOUNT", value = google_service_account.api.email }
      env { name = "FIRESTORE_DATABASE", value = "(default)" }

      env {
        name = "LITELLM_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["litellm-api-key"]
            version = "latest"
          }
        }
      }
    }
  }
}

resource "google_cloud_run_service_iam_member" "public_api" {
  location = google_cloud_run_v2_service.api.location
  service  = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "api_url" { value = google_cloud_run_v2_service.api.uri }
output "api_service_account" { value = google_service_account.api.email }
```

Grant the API service account:

- Firestore user access
- GCS object read/write access for the application bucket
- Service-account self-impersonation for V4 signed URL generation through IAM Credentials
- Secret accessor access only for API secrets

Artifact Registry is created in Phase 1 so both the worker and API images can be built before their Cloud Run revisions are deployed.

---

## Build and Deploy

```bash
export GCP_REGION=asia-south1
export IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/chatbot/api:$(git rev-parse --short HEAD)"

gcloud builds submit backend --tag "$IMAGE"
terraform -chdir=gcp-infra apply -var="api_image=$IMAGE"
```

Update `deploy-backend.sh` to build a versioned image and apply Terraform or deploy with `gcloud run deploy`. Avoid mutable `latest` tags for repeatable rollbacks.

---

## SSE Verification

```bash
curl -N \
  -H "Authorization: Bearer $FIREBASE_ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Stream a short response"}' \
  "$BACKEND_URL/chat/stream"
```

---

## Cost Control

- Use `min_instance_count = 0`.
- Keep request-based billing.
- Start with `max_instance_count = 3`.
- Set a timeout suited to SSE responses, not unbounded execution.
- Keep the worker separate so document processing cannot consume API instances.

Reference: [Cloud Run pricing](https://cloud.google.com/run/pricing)

---

## Verification

- [ ] `/health` returns `200`.
- [ ] Protected routes reject missing Firebase tokens.
- [ ] SSE chunks flush progressively.
- [ ] API scales to zero after idle time.
- [ ] API service account has no owner/editor role.

---

## Next Phase

→ [Phase 8 — Firebase Hosting](./PHASE_8_FIREBASE_HOSTING.md)
