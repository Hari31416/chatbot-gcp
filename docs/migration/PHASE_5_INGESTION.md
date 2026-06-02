# Phase 5 — Event-Driven Ingestion Migration

> Replace Azure Storage Queue, Event Grid, Azure Functions, and Azure AI Document Intelligence with GCS notifications, Pub/Sub, Eventarc, a private Cloud Run worker, and Document AI.

---

## Goal

Deploy document ingestion as an independently scalable Cloud Run service. Keep the API request short: write metadata, upload to `staging/`, return `202 Accepted`, and process asynchronously.

---

## Current State (Azure)

```txt
Blob staging container ──► Event Grid ──► Storage Queue ──► Azure Function
                                                             │
                                                             ▼
                                              AI Document Intelligence
```

| File                            | Azure Dependency                      |
| :------------------------------ | :------------------------------------ |
| `backend/function_app.py`       | Azure Functions queue trigger         |
| `backend/app/services/rag.py`   | Azure AI Document Intelligence        |
| `backend/app/dependencies.py`   | Document Intelligence client provider |
| `infra/modules/storage.bicep`   | Queue + Event Grid                    |
| `infra/modules/functions.bicep` | Function App                          |

---

## Target State (GCP)

```txt
GCS staging/ OBJECT_FINALIZE notification
   │
   ▼
Pub/Sub topic: chatbot-ingestion
   │
   ▼
Eventarc Pub/Sub trigger
   │
   ▼
Private Cloud Run service: chatbot-worker
   │
   ├── Download object from GCS
   ├── Parse text directly or call Document AI
   ├── Chunk and embed through LiteLLM
   ├── Upsert Firestore vector chunks
   ├── Set RAG document status to ready/failed
   └── Delete staging object
```

Publish object metadata only. Never publish document bytes to Pub/Sub.

---

## Code Changes

### 5.1 Replace Dependencies

Update `backend/pyproject.toml`:

```diff
-  "azure-ai-documentintelligence>=1.0.0b4",
-  "azure-storage-queue>=12.10.0",
-  "azure-functions",
+  "cloudevents>=1.11.0",
+  "google-cloud-documentai>=3.3.0",
```

### 5.2 Add Document AI Settings

In `backend/app/settings.py`:

```python
document_ai_location: str = Field(default="us", validation_alias="DOCUMENT_AI_LOCATION")
document_ai_processor_id: str | None = Field(default=None, validation_alias="DOCUMENT_AI_PROCESSOR_ID")
document_ai_use_layout_parser: bool = Field(default=False, validation_alias="DOCUMENT_AI_USE_LAYOUT_PARSER")
max_rag_pages: int = Field(default=25, validation_alias="MAX_RAG_PAGES")
max_rag_chunks: int = Field(default=200, validation_alias="MAX_RAG_CHUNKS")
```

### 5.3 Replace the Parser Client

In `backend/app/dependencies.py`:

```python
from google.cloud import documentai


@lru_cache
def get_document_ai_client() -> documentai.DocumentProcessorServiceClient | None:
    settings = get_settings()
    if not settings.document_ai_processor_id:
        return None
    opts = {"api_endpoint": f"{settings.document_ai_location}-documentai.googleapis.com"}
    return documentai.DocumentProcessorServiceClient(client_options=opts)
```

Update `backend/app/services/rag.py` to:

1. Decode `.txt` and `.md` locally without Document AI.
2. Submit PDFs and images to the configured processor.
3. Reject documents exceeding `MAX_RAG_PAGES`.
4. Reject generated chunk arrays exceeding `MAX_RAG_CHUNKS`.
5. Keep chunk IDs deterministic: `{document_id}:{chunk_index}`.

### 5.4 Replace the Azure Function Entrypoint

Create `backend/app/worker.py`:

```python
import base64
import json
import logging

from cloudevents.http import from_http
from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger(__name__)
app = FastAPI(title="Chatbot ingestion worker")


@app.post("/")
async def handle_pubsub(request: Request) -> dict[str, str]:
    event = from_http(dict(request.headers), await request.body())
    message = event.data.get("message")
    if not isinstance(message, dict) or "data" not in message:
        raise HTTPException(status_code=400, detail="Invalid Eventarc Pub/Sub CloudEvent")

    notification = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
    object_name = str(notification["name"])
    if not object_name.startswith("staging/"):
        logger.info("Ignoring object outside staging prefix: %s", object_name)
        return {"status": "ignored"}

    # Delegate to an idempotent application service:
    # await process_staging_object(object_name=object_name, generation=notification.get("generation"))
    return {"status": "accepted"}
```

The production implementation must call an idempotent service method and return non-`2xx` for retryable failures. Track the GCS object generation or deterministic document ID to avoid duplicate indexing.

### 5.5 Add a Worker Dockerfile

Reuse `backend/Dockerfile` with an overridable command, or create `backend/Dockerfile.worker`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app/ ./app/
EXPOSE 8080
CMD ["uv", "run", "uvicorn", "app.worker:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## Terraform Module

Create `gcp-infra/modules/ingestion/main.tf`:

```hcl
variable "project_id" { type = string }
variable "region" { type = string }
variable "bucket_name" { type = string }
variable "worker_image" { type = string }

resource "google_pubsub_topic" "ingestion" {
  name = "chatbot-ingestion"
}

data "google_storage_project_service_account" "gcs" {}

resource "google_pubsub_topic_iam_member" "gcs_publisher" {
  topic  = google_pubsub_topic.ingestion.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

resource "google_storage_notification" "staging_finalize" {
  bucket         = var.bucket_name
  topic          = google_pubsub_topic.ingestion.id
  payload_format = "JSON_API_V1"
  event_types    = ["OBJECT_FINALIZE"]
  object_name_prefix = "staging/"
  depends_on     = [google_pubsub_topic_iam_member.gcs_publisher]
}

resource "google_service_account" "worker" {
  account_id   = "chatbot-worker"
  display_name = "Chatbot ingestion worker"
}

resource "google_service_account" "eventarc_invoker" {
  account_id   = "chatbot-eventarc-invoker"
  display_name = "Eventarc Cloud Run invoker"
}

resource "google_cloud_run_v2_service" "worker" {
  name     = "chatbot-worker"
  location = var.region

  template {
    service_account = google_service_account.worker.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.worker_image
      resources { limits = { cpu = "1", memory = "1Gi" } }
    }
  }
}

resource "google_cloud_run_service_iam_member" "eventarc_invoker" {
  location = google_cloud_run_v2_service.worker.location
  service  = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.eventarc_invoker.email}"
}

resource "google_eventarc_trigger" "ingestion" {
  name     = "chatbot-ingestion"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.pubsub.topic.v1.messagePublished"
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.worker.name
      region  = var.region
    }
  }

  transport {
    pubsub { topic = google_pubsub_topic.ingestion.id }
  }

  service_account = google_service_account.eventarc_invoker.email
}
```

Add least-privilege IAM bindings:

- Worker service account: bucket object read/delete access.
- Worker service account: Firestore access.
- Worker service account: Secret Manager accessor.
- Eventarc invoker: Cloud Run invoker and the required Eventarc receiver permissions.

Use the [Eventarc Pub/Sub trigger guide](https://cloud.google.com/run/docs/triggering/pubsub-triggers) when wiring IAM because service-agent requirements depend on project history.

### 5.6 Add a Worker Cloud Build Config

Create `backend/cloudbuild.worker.yaml` because `gcloud builds submit --tag` uses `backend/Dockerfile` by default:

```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "Dockerfile.worker", "-t", "${_IMAGE}", "."]
images:
  - "${_IMAGE}"
```

Build the worker with:

```bash
gcloud builds submit backend \
  --config backend/cloudbuild.worker.yaml \
  --substitutions="_IMAGE=$WORKER_IMAGE"
```

---

## Document AI Cost Control

Document AI is explicitly billable:

- Prefer local parsing for `.txt` and `.md`.
- Use Enterprise Document OCR as the default binary parser.
- Enable Layout Parser only when layout-aware retrieval quality justifies the higher price.
- Enforce `MAX_RAG_PAGES` and `MAX_RAG_CHUNKS`.
- Set a billing budget alert before testing large documents.

Reference: [Document AI pricing](https://cloud.google.com/document-ai/pricing)

---

## Verification

- [ ] Upload to `staging/` publishes exactly one Pub/Sub message.
- [ ] Eventarc invokes the private worker.
- [ ] Duplicate delivery does not create duplicate vector chunks.
- [ ] Successful ingestion deletes the staging object and marks the document `ready`.
- [ ] Retryable failures return non-`2xx`; terminal validation failures mark the document `failed`.
- [ ] Non-`staging/` objects are ignored.

---

## Next Phase

→ [Phase 6 — Secret Manager](./PHASE_6_SECRETS.md)
