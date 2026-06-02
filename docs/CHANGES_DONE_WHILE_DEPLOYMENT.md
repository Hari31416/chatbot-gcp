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

### Solution D: Collection Group Index Exemption (The Firestore Module)
We updated the Firestore module to automatically configure a single-field index exemption for the `conversation_id` field within the `conversations` collection group scope. This ensures that any queries spanning multiple users' conversations (which are stored as subcollections under `/users/{user_id}/conversations`) can query across the entire collection group without failing.

### Solution E: Dynamic Environment Variables Passing (The Cloud Run, Ingestion, and Deploy Modules)
We updated the Terraform modules and deployment scripts to dynamically compile all active `.env` configuration keys (e.g. `LITELLM_MODEL`, `LITELLM_VISION_MODEL`, etc.) at deploy-time. These are passed as a JSON-encoded map (`additional_env_vars`) to Terraform, which dynamically mounts them on the Cloud Run and Ingestion Worker containers. This ensures the backend containers run with the correct production configurations and prevents them from falling back to hardcoded defaults (like `gpt-4o-mini`).

---

## 4. Firestore Collection Group Index Exemption

### The Error
```text
Failed: 400 The query requires a COLLECTION_GROUP_ASC index for collection conversations and field conversation_id. You can create it here:
```

### Root Cause
The persistence layer retrieves chat messages or validates conversation metadata using Firestore Collection Group queries:
```python
self._client.collection_group("conversations").where("conversation_id", "==", conversation_id).limit(1).get()
```
Because the `conversations` subcollections reside under individual user documents, a query across all user subcollections is a collection group query. Firestore requires an explicit single-field index exemption with a `COLLECTION_GROUP` query scope enabled for the filtered field (`conversation_id`). Without it, Firestore rejects the query with a 400 error.

### Implemented Solution
We resolved this comprehensively in two ways to ensure both immediate resolution and future reproducibility:

1. **Declarative Firebase CLI Index Deployment (Recommended & Instant):**
   We created a `firestore.indexes.json` file inside the `frontend` directory and registered the single-field index exemption with the `COLLECTION_GROUP` query scope:
   ```json
   {
     "indexes": [],
     "fieldOverrides": [
       {
         "collectionGroup": "conversations",
         "fieldPath": "conversation_id",
         "indexes": [
           {
             "order": "ASCENDING",
             "queryScope": "COLLECTION_GROUP"
           },
           {
             "order": "DESCENDING",
             "queryScope": "COLLECTION_GROUP"
           }
         ]
       }
     ]
   }
   ```
   We then updated `frontend/firebase.json` to configure the `firestore` property pointing to this file. Finally, we deployed these index overrides using the Firebase CLI to instantly configure the correct collection group index scope on GCP:
   ```bash
   firebase deploy --only firestore:indexes --project=rag-chatbot-hari31416
   ```

2. **Infrastructure as Code (IaC) Setup:**
   We declared a `google_firestore_field` resource in Terraform for `conversation_id` on the `conversations` collection group, setting the `query_scope` to `COLLECTION_GROUP` for both `ASCENDING` and `DESCENDING` index orders inside `gcp-infra/modules/firestore/main.tf` to ensure it is automatically provisioned for future automated environments.

---

## 5. Model Configuration / 401 Authentication Failure

### The Error
```text
openai.AuthenticationError: Error code: 401 - {'error': {'message': 'Your authentication token is not from a valid issuer.', 'type': 'invalid_request_error', 'code': 'invalid_issuer'}}
```

### Root Cause
While your local `.env` specifies a custom model endpoint token and configurations:
* `LITELLM_MODEL=openai/gpt_oss_120b`
* `LITELLM_API_KEY=eyJhbGciOiJSUzI1NiIsInR5cCIg...`

Terraform was not configuring or passing these model variables to the deployed Cloud Run services. As a result, the FastAPI container defaulted to `gpt-4o-mini` (per Pydantic setting fallbacks). When the application attempted to stream the LLM response, it sent your custom API token to the standard OpenAI endpoint, which failed with a `401 Unauthorized` token error.

### Implemented Solution
We declared a generic `additional_env_vars` map variable inside Terraform (`gcp-infra/variables.tf` and the modules). We then:
1. Updated [deploy-backend.sh](file:///Users/hari/Desktop/sandbox/chatbot-gcp/deploy-backend.sh) and [deploy-worker.sh](file:///Users/hari/Desktop/sandbox/chatbot-gcp/deploy-worker.sh) to automatically compile all active `.env` configuration keys into a JSON map at deploy time.
2. Passed this JSON map to Terraform, which dynamically injects them as environment variables into both container definitions. This correctly overrides all default model configurations in production.

---

## 6. Cloud Build Registry Timeout (ghcr.io/astral-sh/uv:latest)

### The Error
```text
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
invalid from flag value ghcr.io/astral-sh/uv:latest: Head "https://ghcr.io/v2/astral-sh/uv/manifests/latest": Client.Timeout exceeded while awaiting headers
```

### Root Cause
During remote container image building on GCP Cloud Build, pulling the `uv` package manager binary from the GitHub Container Registry (`ghcr.io`) can trigger transient network/DNS timeouts, leading to a build block and complete failure.

### Implemented Solution
We completely removed any compile-time dependency on `ghcr.io/astral-sh/uv` inside the container:
1. **Dynamic Requirements Export:** We updated the deployment scripts (`deploy-backend.sh` and `deploy-worker.sh`) to automatically run `uv export` locally at start time. This dynamically outputs the current, pinned virtual environment dependencies into a standard `requirements.txt` in the `backend/` directory.
2. **Standard Pip Installation:** We updated both `backend/Dockerfile` and `backend/Dockerfile.worker` to copy `requirements.txt` and run `pip install --no-cache-dir -r requirements.txt` on the official `python:3.12-slim` image, completely bypassing ghcr.io and ensuring robust, reliable, and fast remote builds.

---

## 7. Detailed File Diffs

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

### D. [gcp-infra/modules/firestore/main.tf](file:///Users/hari/Desktop/sandbox/chatbot-gcp/gcp-infra/modules/firestore/main.tf)
Added `google_firestore_field` to automatically establish the required collection group index exemption for the persistence layer:

```hcl
resource "google_firestore_field" "conversation_id_index" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "conversations"
  field      = "conversation_id"

  index_config {
    indexes {
      order       = "ASCENDING"
      query_scope = "COLLECTION_GROUP"
    }
    indexes {
      order       = "DESCENDING"
      query_scope = "COLLECTION_GROUP"
    }
  }
}
```

### E. [deploy-backend.sh](file:///Users/hari/Desktop/sandbox/chatbot-gcp/deploy-backend.sh) & [deploy-worker.sh](file:///Users/hari/Desktop/sandbox/chatbot-gcp/deploy-worker.sh)
Added JSON environment variable compilation, dynamic local requirements export, and passed additional variables to the `terraform apply` CLI command:

```bash
# Export requirements dynamically
echo "📦 Exporting backend requirements..."
cd backend
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
cd ..

# Construct a JSON map of non-empty environment variables to pass to Terraform
additional_env_vars="..."

terraform -chdir=gcp-infra apply \
  ...
  -var="additional_env_vars=${additional_env_vars}" \
  -auto-approve
```

### F. [gcp-infra/modules/cloud-run/main.tf](file:///Users/hari/Desktop/sandbox/chatbot-gcp/gcp-infra/modules/cloud-run/main.tf) & [gcp-infra/modules/ingestion/main.tf](file:///Users/hari/Desktop/sandbox/chatbot-gcp/gcp-infra/modules/ingestion/main.tf)
Added `additional_env_vars` input map and dynamic block to inject variables into Cloud Run container configurations:

```hcl
variable "additional_env_vars" {
  type    = map(string)
  default = {}
}

# Inside resource "google_cloud_run_v2_service" -> containers:
      # Additional environment variables dynamically loaded from variables
      dynamic "env" {
        for_each = var.additional_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
```

### G. [backend/Dockerfile](file:///Users/hari/Desktop/sandbox/chatbot-gcp/backend/Dockerfile) & [backend/Dockerfile.worker](file:///Users/hari/Desktop/sandbox/chatbot-gcp/backend/Dockerfile.worker)
Converted the Docker image package resolution from `uv` to standard `pip` using the exported `requirements.txt`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Copy dependency files
COPY requirements.txt ./

# Install dependencies using pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Expose default Cloud Run port
EXPOSE 8080

# Use standard python to run uvicorn
CMD ["/bin/sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

---

## 8. dynamic Deployment Image Reset Conflict

### The Issue
Because Terraform variables (`api_image` and `worker_image`) default to the `"gcr.io/cloudrun/hello"` placeholder, executing `deploy-backend.sh` without supplying the worker image would overwrite the ingestion worker with a Hello World container (and vice versa for `deploy-worker.sh` resetting the API). The placeholder container blindly intercepts event triggers with a `200` response but does not execute any application code, preventing RAG document ingestion.

### Implemented Solution
We updated both [deploy-backend.sh](file:///Users/hari/Desktop/sandbox/chatbot-gcp/deploy-backend.sh) and [deploy-worker.sh](file:///Users/hari/Desktop/sandbox/chatbot-gcp/deploy-worker.sh) to dynamically query the live, active container image of the other service via the `gcloud run services describe` CLI before running Terraform. The active image is passed dynamically into the `terraform apply` step, fully preserving the running state of both services and breaking the reset override conflict.

---

## 9. CORS & Custom Authorization Mismatch

### The Issue
Following the integration of Firebase passwordless authentication, the frontend began sending custom `Authorization: Bearer <token>` headers on all API requests. Standard browsers block authorized requests when the backend returns a wildcard `*` for allowed origins while having `allow_credentials = True` active.

### Implemented Solution
We edited [backend/app/main.py](file:///Users/hari/Desktop/sandbox/chatbot-gcp/backend/app/main.py) to declare an explicit list of allowed origins. It dynamically combines local development ports (`3000`, `3333`, `5173`) with your custom Firebase hosting domains (`https://{project_id}.web.app` and `https://{project_id}.firebaseapp.com`) loaded from environment parameters. We also updated the deployment scripts to automatically forward the custom text model `LITELLM_BASE_URL` to Cloud Run, resolving the `invalid_issuer` API gateway auth error.

---

## 10. Light Mode Default & UI Lock

### The Issue
To lock the application aesthetic to light mode by default, the UI must prevent any manual or keyboard toggling to dark mode.

### Implemented Solution
* **Default Theme State:** Updated [frontend/src/main.tsx](file:///Users/hari/Desktop/sandbox/chatbot-gcp/frontend/src/main.tsx) and [frontend/src/components/theme-provider.tsx](file:///Users/hari/Desktop/sandbox/chatbot-gcp/frontend/src/components/theme-provider.tsx) to default the ThemeProvider value to `"light"`.
* **Keyboard Shortcut Block:** Removed the `D` keydown event listener inside the `ThemeProvider` to completely block manual keyboard dark mode toggling.
* **Theme Selector Removal:** Removed the light/dark toggle button from the sidebar bottom action menu inside [frontend/src/components/Sidebar.tsx](file:///Users/hari/Desktop/sandbox/chatbot-gcp/frontend/src/components/Sidebar.tsx) and aligned the log-out button cleanly to the right side.
* **TypeScript Integrity:** Cleaned up all unused destructured variables and imports in `App.tsx` and `Sidebar.tsx` to ensure absolute compliance with the strict compiler rules, producing a successful production build.

---

## 11. Firestore Native Vector Search Index

### The Issue
RAG document ingestion produces text embeddings that are stored inside the `rag_chunks` subcollection. During ingestion/document searches, Firestore Native requires a flat vector index on the `embedding` field to index and query vector spaces. Without it, transactions fail with a `400 Missing vector index` error.

### Implemented Solution
* **CLI index provisioning:** Triggered immediate asynchronous index creation on Google Cloud:
  ```bash
  gcloud firestore indexes composite create \
    --project=rag-chatbot-hari31416 \
    --collection-group=rag_chunks \
    --query-scope=COLLECTION \
    --field-config=vector-config='{"dimension":"768","flat": "{}"}',field-path=embedding
  ```
* **IaC Declarative setup:** Configured the index inside the Firestore Terraform module [gcp-infra/modules/firestore/main.tf](file:///Users/hari/Desktop/sandbox/chatbot-gcp/gcp-infra/modules/firestore/main.tf) to make it highly reproducible:
  ```hcl
  resource "google_firestore_index" "rag_chunks_vector" {
    project    = var.project_id
    database   = google_firestore_database.default.name
    collection = "rag_chunks"

    fields {
      field_path = "embedding"
      vector_config {
        dimension = 768
        flat {}
      }
    }
  }
  ```

---

## 12. Verification and Next Steps

1. To apply all fixes (CORS, Light mode lock, Vector index declarative configs, and dynamic preservation), run the deployments:
   ```bash
   make deploy-backend
   make deploy-worker
   make deploy-frontend
   ```
2. Verify that the build succeeds without timing out, the RAG chunks ingest cleanly once the GCP vector index is `READY`, and the chat stream interface functions smoothly!
