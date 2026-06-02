# Phase 1 — Project Scaffold & Terraform Bootstrap

> Add the GCP deployment scaffold while preserving the Azure Bicep deployment for rollback.

---

## Goal

Create a Terraform project for a minimal-cost PoC in `asia-south1`. This phase enables APIs and defines shared variables but does not remove Azure infrastructure.

---

## Current State (Azure)

| Artifact                | Role                                  |
| :---------------------- | :------------------------------------ |
| `azure.yaml`            | Azure Developer CLI project           |
| `infra/main.bicep`      | Subscription-level Azure orchestrator |
| `infra/modules/*.bicep` | Azure service modules                 |
| `deploy-*.sh`           | Azure deployment scripts              |

---

## Target State (GCP)

```txt
gcp-infra/
├── versions.tf
├── variables.tf
├── terraform.tfvars.example
├── main.tf
├── outputs.tf
└── modules/
    ├── storage/
    ├── firestore/
    ├── ingestion/
    ├── secrets/
    ├── cloud-run/
    ├── hosting/
    └── observability/
frontend/
├── firebase.json
└── .firebaserc.example
```

---

## Tasks

### 1.1 Install Tooling

```bash
brew install --cask google-cloud-sdk
brew install terraform
npm install -g firebase-tools

gcloud version
terraform version
firebase --version
```

### 1.2 Authenticate and Select a Project

```bash
gcloud auth login
gcloud auth application-default login
gcloud projects create "$GCP_PROJECT_ID"
gcloud config set project "$GCP_PROJECT_ID"
firebase login
firebase projects:addfirebase "$GCP_PROJECT_ID"
```

Billing must be enabled because Cloud Run, Eventarc, Artifact Registry, and Document AI require a billing-backed project even when PoC use remains within free quotas.

### 1.3 Enable APIs

```bash
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  documentai.googleapis.com \
  eventarc.googleapis.com \
  firestore.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com
```

### 1.4 Create Terraform Bootstrap Files

Create `gcp-infra/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
```

Create `gcp-infra/variables.tf`:

```hcl
variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "environment" {
  type    = string
  default = "dev"
}
variable "firebase_web_app_id" {
  type      = string
  default   = ""
  sensitive = true
}
```

Create `gcp-infra/main.tf`:

```hcl
locals {
  name_prefix = "chatbot-${var.environment}"
}

resource "google_project_service" "required" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "documentai.googleapis.com",
    "eventarc.googleapis.com",
    "firestore.googleapis.com",
    "iamcredentials.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "chatbot"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}
```

Create `gcp-infra/terraform.tfvars.example`:

```hcl
project_id  = "replace-with-project-id"
region      = "asia-south1"
environment = "dev"
```

### 1.5 Create a GCP Environment Template

Create `.env.gcp.example`:

```bash
GCP_PROJECT_ID=
GCP_REGION=asia-south1
GCS_BUCKET_NAME=
FIRESTORE_DATABASE=(default)
FIREBASE_PROJECT_ID=
FIREBASE_WEB_API_KEY=
FIREBASE_AUTH_EMULATOR_HOST=
DOCUMENT_AI_LOCATION=us
DOCUMENT_AI_PROCESSOR_ID=
DOCUMENT_AI_USE_LAYOUT_PARSER=false
PUBSUB_INGESTION_TOPIC=chatbot-ingestion
WORKER_BASE_URL=
LITELLM_MODEL=gpt-4o-mini
LITELLM_API_KEY=
LITELLM_VISION_MODEL=gemini/gemini-3.1-flash-lite
LITELLM_VISION_API_KEY=
LITELLM_EMBEDDING_MODEL=gemini/gemini-embedding-2
LITELLM_EMBEDDING_API_KEY=
EMBEDDING_DIMENSION=768
RAG_TOP_K=3
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=80
```

---

## Verification

- [ ] `gcloud config get-value project` prints the intended project ID.
- [ ] `gcloud services list --enabled` includes the required APIs.
- [ ] `terraform -chdir=gcp-infra fmt -check`
- [ ] `terraform -chdir=gcp-infra init`
- [ ] `terraform -chdir=gcp-infra validate`
- [ ] `terraform -chdir=gcp-infra apply` creates the `chatbot` Artifact Registry repository before Phase 5 container builds.
- [ ] Existing Azure files remain unchanged.

---

## Decisions & Notes

> [!IMPORTANT]
> Commit `terraform.tfvars.example`, never a real `terraform.tfvars`. Keep Terraform state out of Git.

> [!NOTE]
> `asia-south1` is the default application region. Document AI processor availability must be checked when the processor is created; its processor location can differ from the application region.

---

## Next Phase

→ [Phase 2 — Cloud Storage](./PHASE_2_CLOUD_STORAGE.md)
