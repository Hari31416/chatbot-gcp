# GCP Deployment Blocker Resolution: Changes Walkthrough

This document details the specific architectural modifications made to the GCP infrastructure modules to resolve the chicken-and-egg deployment failures and IAM race conditions.

---

## 1. Secrets Mounting Failure

### The Error
```text
Error waiting to create Service: Error waiting for Creating Service: Error code 9, message: spec.template.spec.containers[0].env[4].value_from.secret_key_ref.name: Permission denied on secret: projects/1011875655406/secrets/litellm-embedding-api-key/versions/latest for Revision service account chatbot-api@rag-chatbot-hari31416.iam.gserviceaccount.com.
```

### Root Cause
1. **Chicken-and-Egg Mount Failure:** Cloud Run is configured to map secrets directly from Google Secret Manager as environment variables using the `latest` version reference. However, when Secret Manager resources are first created by Terraform, they are empty (i.e. they contain no active secret versions). GCP prevents Cloud Run from creating a container revision if the referenced version (`latest`) of a secret does not exist.
2. **IAM Propagation Delay:** GCP's Identity and Access Management (IAM) is eventually consistent. Terraform sometimes attempts to provision Cloud Run services immediately after issuing the API command to bind permissions to service accounts, resulting in transient `Permission Denied` errors because GCP's IAM systems are still updating.

---

## 2. Cloud Run Deletion Protection Failure

### The Error
```text
Error: cannot destroy service without setting deletion_protection=false and running `terraform apply`
```

### Root Cause
The `google_cloud_run_v2_service` Terraform resource defaults `deletion_protection` to `true`. When changes to the service (such as added `depends_on` blocks for IAM propagation) force Terraform to **recreate** the resource, Terraform must first destroy the old one. GCP blocks this unless `deletion_protection = false` is explicitly set in the resource configuration. Both `chatbot-api` and `chatbot-worker` services triggered this error simultaneously.

---

## 3. Implemented Solutions

To resolve all issues, we updated the base infrastructure configurations to implement three robust infrastructure patterns:

### Solution A: Bootstrap Secret Versions (The Secrets Module)
We updated the secrets module to automatically seed a default placeholder version (`"placeholder-replace-me"`) for each secret managed by Terraform. This guarantees that the `latest` version exists immediately, allowing the Cloud Run revisions to deploy successfully.

Once the initial deploy completes, the user can securely overwrite these placeholder versions with live API keys via standard `gcloud` CLI commands.

### Solution B: Explicit IAM Dependencies (The Cloud Run & Ingestion Modules)
We added explicit `depends_on` blocks to both the public API Cloud Run service (`chatbot-api`) and background ingestion worker (`chatbot-worker`) declarations. The container definitions now wait for all corresponding IAM policies (such as `roles/secretmanager.secretAccessor`) to be fully applied in Terraform before initiating container revision provisioning.

### Solution C: Disable Deletion Protection (The Cloud Run & Ingestion Modules)
We set `deletion_protection = false` on both `google_cloud_run_v2_service` resources. Without this flag, Terraform cannot delete or recreate Cloud Run services (e.g. when resource configuration changes force a replacement). This is the correct pattern for Terraform-managed services where the IaC toolchain itself owns the lifecycle of the resource.

---

## 4. Detailed File Diffs

### A. [gcp-infra/modules/secrets/main.tf](file:///Users/hari/Desktop/sandbox/chatbot-gcp/gcp-infra/modules/secrets/main.tf)
Added a `google_secret_manager_secret_version` resource to bootstrap default values:

```hcl
# Seed default secret versions to unblock Cloud Run 'latest' version mounts
resource "google_secret_manager_secret_version" "app" {
  for_each    = var.secret_ids
  secret      = google_secret_manager_secret.app[each.value].id
  secret_data = "placeholder-replace-me"
}
```

### B. [gcp-infra/modules/cloud-run/main.tf](file:///Users/hari/Desktop/sandbox/chatbot-gcp/gcp-infra/modules/cloud-run/main.tf)
Introduced explicit `depends_on` constraints and `deletion_protection = false` on `chatbot-api`:

```hcl
resource "google_cloud_run_v2_service" "api" {
  name                = "chatbot-api"
  location            = var.region
  project             = var.project_id
  deletion_protection = false

  depends_on = [
    google_service_account_iam_member.api_can_sign_as_self,
    google_project_iam_member.api_firestore,
    google_storage_bucket_iam_member.api_storage,
    google_project_iam_member.api_secrets,
  ]

  template {
    # ...
  }
}
```

### C. [gcp-infra/modules/ingestion/main.tf](file:///Users/hari/Desktop/sandbox/chatbot-gcp/gcp-infra/modules/ingestion/main.tf)
Introduced identical IAM `depends_on` constraints and `deletion_protection = false` on the background RAG worker service:

```hcl
resource "google_cloud_run_v2_service" "worker" {
  name                = "chatbot-worker"
  location            = var.region
  project             = var.project_id
  deletion_protection = false

  depends_on = [
    google_project_iam_member.worker_firestore,
    google_storage_bucket_iam_member.worker_storage,
    google_project_iam_member.worker_secrets,
  ]

  template {
    # ...
  }
}
```

---

## 5. Verification and Next Steps

1. Run the base infrastructure apply command:
   ```bash
   make deploy-infra
   ```
2. Overwrite the dummy values in GCP Secret Manager with your active credentials:
   ```bash
   echo -n "YOUR_LITELLM_API_KEY" | gcloud secrets versions add litellm-api-key --data-file=- --project=rag-chatbot-hari31416
   echo -n "YOUR_LITELLM_VISION_API_KEY" | gcloud secrets versions add litellm-vision-api-key --data-file=- --project=rag-chatbot-hari31416
   echo -n "YOUR_LITELLM_EMBEDDING_API_KEY" | gcloud secrets versions add litellm-embedding-api-key --data-file=- --project=rag-chatbot-hari31416
   ```
3. Proceed with RAG container services deployment as documented in [docs/GCP_DEPLOYMENT_GUIDE.md](file:///Users/hari/Desktop/sandbox/chatbot-gcp/docs/GCP_DEPLOYMENT_GUIDE.md).
