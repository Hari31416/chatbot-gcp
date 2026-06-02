# Phase 5 — Event-Driven Ingestion Migration

> Replace the SQS + Lambda Worker + Textract pipeline with Azure Storage Queues + Azure Functions + Azure AI Document Intelligence.

---

## Goal

Migrate the asynchronous RAG document ingestion pipeline. When a user uploads a PDF to staging, it should trigger an Azure Function that parses the document and stores vector embeddings — exactly like the current AWS flow but using Azure-native services.

---

## Current State (AWS)

### Event Flow

```
S3 Upload (staging/) → S3 Event Notification → SQS Queue → Lambda Worker → Textract → S3 Vectors
```

### Components

| Component          | AWS Service                                          | File                                            |
| :----------------- | :--------------------------------------------------- | :---------------------------------------------- |
| Staging upload     | S3 bucket (`staging/` prefix)                        | `app/api/routes.py`                             |
| Event notification | S3 → SQS                                             | `template.yaml` (NotificationConfiguration)     |
| Message queue      | SQS + DLQ                                            | `template.yaml` (IngestionQueue + IngestionDLQ) |
| Worker function    | Lambda (handler: `app.worker.handler`)               | `app/worker.py`                                 |
| Document parsing   | AWS Textract (async `start_document_text_detection`) | `app/services/rag.py`                           |
| Vector storage     | S3 Vectors                                           | `app/services/vector_store.py`                  |

### Worker Entry Point (`app/worker.py`)

1. Receives SQS event with S3 notification payload
2. Parses S3 key: `staging/{user_id}/{document_id}/{filename}`
3. Downloads file from S3
4. Calls `rag_service.ingest_binary_document()` (or `.ingest_document()` for text)
5. Updates DynamoDB status: `processing` → `ready` / `failed`
6. Cleans up staging file

---

## Target State (Azure)

### Event Flow

```
Blob Upload (staging/) → Event Grid → Storage Queue → Azure Function → AI Document Intelligence → Cosmos DB Vectors
```

### Components

| Component          | Azure Service                           | File                                                         |
| :----------------- | :-------------------------------------- | :----------------------------------------------------------- |
| Staging upload     | Blob Storage (`staging` container)      | `app/api/routes.py` (already migrated in Phase 2)            |
| Event notification | Event Grid (Blob Created event)         | Bicep module                                                 |
| Message queue      | Azure Storage Queue                     | Bicep module (uses same Storage Account from Phase 2)        |
| Worker function    | Azure Functions (Queue Storage trigger) | `functions/ingestion_worker/` (new)                          |
| Document parsing   | Azure AI Document Intelligence          | `app/services/rag.py` (updated)                              |
| Vector storage     | Cosmos DB Vector Search                 | `app/services/vector_store.py` (already migrated in Phase 3) |

---

## Code Changes

### 5.1 Add Azure SDKs

```diff
 dependencies = [
   ...
   "azure-storage-blob>=12.20.0",
   "azure-cosmos>=4.7.0",
+  "azure-ai-documentintelligence>=1.0.0",
+  "azure-storage-queue>=12.10.0",
   ...
 ]
```

> [!NOTE]
> We use `azure-storage-queue` instead of `azure-servicebus` to avoid the ~$10/month Service Bus Standard base fee. Azure Storage Queues are covered under the same Storage Account provisioned in Phase 2 and fall within the 12-month free tier (20,000 transactions/month free).

### 5.2 Replace Textract with Document Intelligence in `app/services/rag.py`

```python
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentAnalysisFeature
from azure.core.credentials import AzureKeyCredential

class RagService:
    def __init__(
        self,
        vector_store: VectorStoreClient,
        chunk_size: int = 800,
        chunk_overlap: int = 80,
        storage: StorageService | None = None,
        doc_intelligence_client: DocumentIntelligenceClient | None = None,
    ) -> None:
        # ...
        self.storage = storage
        self.doc_intelligence_client = doc_intelligence_client

    async def ingest_binary_document(
        self, filename: str, data: bytes, mime_type: str, user_id: str, document_id: str | None = None
    ) -> RagIngestResult:
        if not self.storage or not self.doc_intelligence_client:
            raise ValueError("Storage and Document Intelligence clients must be configured")

        if not document_id:
            document_id = str(uuid4())

        # 1. Upload to temporary storage
        temp_key = f"rag-temp/{user_id}/{document_id}/{filename}"
        await to_thread.run_sync(
            lambda: self.storage.upload_bytes(temp_key, data, mime_type)
        )

        try:
            # 2. Analyze with Document Intelligence (prebuilt-layout model)
            #    Send the raw bytes directly instead of a URL reference
            poller = await to_thread.run_sync(
                lambda: self.doc_intelligence_client.begin_analyze_document(
                    "prebuilt-layout",
                    analyze_request=data,
                    content_type=mime_type,
                    output_content_format="markdown",
                )
            )
            result = await to_thread.run_sync(poller.result)

            # 3. Extract markdown content
            extracted_text = result.content or ""
            logger.info(
                "Extracted %d chars from document=%s using Document Intelligence",
                len(extracted_text), filename,
            )

            # 4. Check page limit
            if result.pages and len(result.pages) > 100:
                raise ValueError(f"Document exceeds 100 page limit (got {len(result.pages)} pages)")

        finally:
            # 5. Clean up temporary file
            try:
                await to_thread.run_sync(lambda: self.storage.delete_blob(temp_key))
            except Exception as e:
                logger.warning("Failed to clean up temp file %s: %s", temp_key, e)

        # 6. Chunk and ingest
        chunks = self.split_text(extracted_text)
        if not chunks:
            return RagIngestResult(document_id=document_id, chunks_ingested=0)

        embeddings = await self.vector_store.get_embeddings(chunks)
        keys = [f"{document_id}#chunk-{idx}" for idx in range(len(chunks))]
        await self.vector_store.upsert_chunks(
            keys=keys, texts=chunks, embeddings=embeddings,
            source_doc=filename, document_id=document_id, user_id=user_id,
        )
        return RagIngestResult(document_id=document_id, chunks_ingested=len(chunks))
```

> [!NOTE]
> Document Intelligence outputs **Markdown** natively when `output_content_format="markdown"` is set. This is superior to Textract's line-by-line output and preserves tables, headings, and lists for better RAG chunk quality.

### 5.3 Create Azure Function Worker

Create a new directory structure:

```
functions/
├── ingestion_worker/
│   ├── function_app.py        # Function entry point
│   ├── host.json              # Functions host config
│   ├── local.settings.json    # Local dev settings
│   └── requirements.txt       # Python dependencies
```

**`functions/ingestion_worker/function_app.py`:**

```python
import asyncio
import json
import logging
import os

import azure.functions as func

app = func.FunctionApp()

logger = logging.getLogger(__name__)


@app.queue_trigger(
    arg_name="msg",
    queue_name="ingestion-queue",
    connection="AzureWebJobsStorage",
)
def process_ingestion(msg: func.QueueMessage) -> None:
    """
    Triggered by Azure Storage Queue messages from Blob Storage Event Grid.
    Message payload contains the blob event with subject = blob path.
    """
    body = msg.get_body().decode("utf-8")
    logger.info("Received ingestion message: %s", body)

    try:
        event = json.loads(body)
    except Exception:
        logger.exception("Failed to parse message body")
        return

    # Event Grid schema: subject = /blobServices/default/containers/staging/blobs/{path}
    subject = event.get("subject", "")
    blob_url = event.get("data", {}).get("url", "")

    # Extract: staging/{user_id}/{document_id}/{filename}
    # The subject path is: /blobServices/default/containers/staging/blobs/{user_id}/{document_id}/{filename}
    blob_path = subject.split("/blobs/", 1)[-1] if "/blobs/" in subject else ""
    parts = blob_path.split("/")

    if len(parts) < 3:
        logger.warning("Unexpected blob path format: %s", blob_path)
        return

    user_id = parts[0]
    document_id = parts[1]
    filename = "/".join(parts[2:])

    logger.info(
        "Processing blob: user_id=%s, document_id=%s, filename=%s",
        user_id, document_id, filename,
    )

    # Run the async ingestion pipeline
    asyncio.run(process_staging_file(user_id, document_id, filename))


async def process_staging_file(user_id: str, document_id: str, filename: str) -> None:
    """
    Reimplementation of the Lambda worker's process_staging_file,
    using Azure services (Blob Storage, Document Intelligence, Cosmos DB).
    """
    # Import app dependencies (initialized with Azure env vars)
    from app.dependencies import get_repository, get_rag_service, get_storage
    from app.utils.time import utcnow_iso
    from anyio import to_thread

    repo = get_repository()
    storage = get_storage()

    try:
        # 1. Download from staging container
        staging_key = f"{user_id}/{document_id}/{filename}"
        data, content_type = await to_thread.run_sync(
            lambda: storage.download_bytes(staging_key)
        )

        # 2. Determine binary vs text
        ext = os.path.splitext(filename.lower())[1] or ""
        is_binary = ext in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif")

        # 3. Run RAG ingestion
        rag_service = get_rag_service()

        if is_binary:
            result = await rag_service.ingest_binary_document(
                filename=filename, data=data, mime_type=content_type,
                user_id=user_id, document_id=document_id,
            )
        else:
            try:
                content = data.decode("utf-8")
                result = await rag_service.ingest_document(
                    filename=filename, content=content,
                    user_id=user_id, document_id=document_id,
                )
            except UnicodeDecodeError:
                result = await rag_service.ingest_binary_document(
                    filename=filename, data=data, mime_type=content_type,
                    user_id=user_id, document_id=document_id,
                )

        # 4. Update status
        updated_at = utcnow_iso()
        await to_thread.run_sync(
            lambda: repo.update_rag_document_status(
                user_id, document_id, "ready", result.chunks_ingested, updated_at
            )
        )
        logger.info("Ingested document_id=%s, chunks=%d", document_id, result.chunks_ingested)

    except Exception:
        logger.exception("Failed ingestion for document_id=%s", document_id)
        try:
            updated_at = utcnow_iso()
            await to_thread.run_sync(
                lambda: repo.update_rag_document_status(user_id, document_id, "failed", 0, updated_at)
            )
        except Exception:
            logger.exception("Failed to write failure status for document_id=%s", document_id)

    finally:
        # 5. Clean up staging blob
        try:
            staging_key = f"{user_id}/{document_id}/{filename}"
            await to_thread.run_sync(lambda: storage.delete_blob(staging_key))
            logger.info("Cleaned up staging blob: %s", staging_key)
        except Exception:
            logger.exception("Failed to clean up staging blob")
```

**`functions/ingestion_worker/host.json`:**

```json
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  },
  "logging": {
    "logLevel": {
      "default": "Information"
    }
  }
}
```

### 5.4 Update `app/dependencies.py`

Add Document Intelligence client factory:

```python
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

@lru_cache
def get_doc_intelligence_client() -> DocumentIntelligenceClient | None:
    settings = get_settings()
    endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    key = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
    if endpoint and key:
        return DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key),
        )
    return None

def get_rag_service(
    vector_store: VectorStoreClient = Depends(get_vector_store),
) -> RagService:
    settings = get_settings()
    storage = get_storage()
    doc_client = get_doc_intelligence_client()
    return RagService(
        vector_store=vector_store,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        storage=storage,
        doc_intelligence_client=doc_client,
    )
```

### 5.5 Remove `app/worker.py`

The original Lambda worker is replaced by the Azure Function at `functions/ingestion_worker/function_app.py`. The old `worker.py` can be deleted (or archived) since:

- It processes SQS event payloads (AWS-specific format)
- It uses `boto3` S3 client directly
- The `handler(event, context)` signature is Lambda-specific

---

## Bicep Modules

### Storage Queue (added to `infra/modules/storage.bicep`)

The ingestion queue is provisioned inside the **same Storage Account** created in Phase 2 — no separate Service Bus namespace needed.

Add the following to the existing `infra/modules/storage.bicep`:

```bicep
// ── Queue Service (Phase 5) ──
resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource ingestionQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = {
  parent: queueService
  name: 'ingestion-queue'
  properties: {
    metadata: {
      purpose: 'RAG document ingestion pipeline'
      maxDequeueCount: '3'  // Application-level retry tracking
    }
  }
}
```

> [!NOTE]
> Azure Storage Queues don't have native dead-lettering like Service Bus or SQS. Messages that fail processing are retried by the Azure Functions runtime up to 5 times (configurable via `host.json`). After exhausting retries, the message is moved to a **poison queue** (`ingestion-queue-poison`) automatically by the Functions runtime.

### `infra/modules/functions.bicep`

```bicep
param location string
param environmentName string
param storageAccountConnectionString string

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: 'func-chatbot-worker-${environmentName}'
  location: location
  kind: 'functionapp,linux'
  properties: {
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: storageAccountConnectionString }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
      ]
    }
    reserved: true // Required for Linux
  }
}
```

> [!TIP]
> `AzureWebJobsStorage` serves double duty — it is the Functions runtime storage **and** the queue connection. Since the ingestion queue lives in the same Storage Account, no additional connection string is needed.

### Event Grid Subscription

Connect Blob Storage events to the Storage Queue:

```bicep
resource eventGridSubscription 'Microsoft.EventGrid/eventSubscriptions@2023-12-15-preview' = {
  name: 'blob-to-storage-queue'
  scope: storageAccount
  properties: {
    destination: {
      endpointType: 'StorageQueue'
      properties: {
        resourceId: storageAccount.id
        queueName: 'ingestion-queue'
        queueMessageTimeToLiveInSeconds: 1209600  // 14 days (matches SQS DLQ retention)
      }
    }
    filter: {
      subjectBeginsWith: '/blobServices/default/containers/staging/blobs/'
      includedEventTypes: ['Microsoft.Storage.BlobCreated']
    }
  }
}
```

---

## Settings Updates

```bash
# .env.azure.example additions
# Storage Queue uses the same AZURE_STORAGE_CONNECTION_STRING from Phase 2 — no extra connection string needed
AZURE_INGESTION_QUEUE_NAME=ingestion-queue
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=
```

---

## Verification

- [ ] Uploading a PDF to `staging` container triggers Event Grid → Storage Queue → Function
- [ ] Azure Function correctly parses blob event and extracts `user_id`, `document_id`, `filename`
- [ ] Document Intelligence extracts text as Markdown from PDF
- [ ] Chunks are upserted into Cosmos DB `vectors` container
- [ ] Document status is updated to `ready` in Cosmos DB
- [ ] Failed documents get `failed` status and poison messages go to `ingestion-queue-poison`
- [ ] Staging blobs are cleaned up after processing
- [ ] `func host start` runs the function locally for testing
- [ ] No Service Bus namespace is provisioned (cost = $0)

---

## Cost & Trade-Off Notes

> [!TIP]
> **$0/month for queuing.** Azure Storage Queues are bundled with the Storage Account provisioned in Phase 2. The 12-month free tier includes 20,000 queue transactions/month — more than enough for a dev/staging RAG pipeline.

> [!NOTE]
> **Why not Service Bus?** Azure Service Bus Standard has a ~$10/month base fee. It offers dead-letter queues, sessions, and at-least-once delivery guarantees — but for this use case, the Azure Functions runtime's built-in poison-queue mechanism (`{queue}-poison`) provides equivalent retry/failure handling at zero cost. If you need advanced message routing in the future, Service Bus can be swapped in by changing the trigger decorator and adding a connection string.

---

## Next Phase

→ [Phase 6 — Secrets Management](./PHASE_6_SECRETS.md)
