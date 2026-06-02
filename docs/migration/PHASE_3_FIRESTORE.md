# Phase 3 — Firestore Native Mode & Vector Search

> Replace Azure Cosmos DB NoSQL and Cosmos vector queries with one Firestore Native Mode database.

---

## Goal

Use Firestore for conversation metadata, messages, sliding context, RAG document status, and vector chunks. Start with an empty GCP database; do not copy Cosmos DB records.

---

## Current State (Azure)

| File                                                  | Cosmos Dependency                                 |
| :---------------------------------------------------- | :------------------------------------------------ |
| `backend/app/repositories/conversation_repository.py` | Cosmos CRUD and TTL documents                     |
| `backend/app/services/vector_store.py`                | Cosmos vector container and `VectorDistance()`    |
| `backend/app/dependencies.py`                         | `CosmosClient`, database, and container providers |
| `backend/app/settings.py`                             | endpoint, key, database, and container names      |
| `infra/modules/cosmos.bicep`                          | Cosmos account, database, and two containers      |

---

## Target Data Model

```txt
users/{user_id}/conversations/{conversation_id}
users/{user_id}/conversations/{conversation_id}/messages/{message_id}
users/{user_id}/conversations/{conversation_id}/state/context
users/{user_id}/rag_documents/{document_id}
users/{user_id}/rag_chunks/{chunk_id}
```

Example vector chunk:

```python
{
    "document_id": "doc_123",
    "chunk_index": 0,
    "text": "...",
    "embedding": Vector([...]),
    "created_at": firestore.SERVER_TIMESTAMP,
}
```

User-scoped subcollections keep authorization and query boundaries obvious. Use deterministic IDs where retries must be idempotent.

---

## Code Changes

### 3.1 Replace the SDK

Update `backend/pyproject.toml`:

```diff
-  "azure-cosmos>=4.7.0",
+  "google-cloud-firestore>=2.19.0",
```

### 3.2 Update Settings

Replace Cosmos settings in `backend/app/settings.py`:

```python
# ── Firestore Native Mode ──
gcp_project_id: str | None = Field(default=None, validation_alias="GCP_PROJECT_ID")
firestore_database: str = Field(default="(default)", validation_alias="FIRESTORE_DATABASE")
```

### 3.3 Replace Dependency Providers

In `backend/app/dependencies.py`:

```python
from google.cloud import firestore


@lru_cache
def get_firestore_client() -> firestore.Client:
    settings = get_settings()
    return firestore.Client(
        project=settings.gcp_project_id,
        database=settings.firestore_database,
    )


def get_repository() -> ConversationRepository:
    return ConversationRepository(get_firestore_client())
```

### 3.4 Rewrite the Conversation Repository

Rewrite `backend/app/repositories/conversation_repository.py` around `firestore.Client`. Preserve the repository public API used by `backend/app/api/routes.py`.

Key implementation rules:

- Check `user_id` in every repository method.
- Use batch writes for message + context updates.
- Store timestamps with `firestore.SERVER_TIMESTAMP`.
- Store an explicit `expires_at` timestamp for context records.
- Keep list queries bounded and ordered.
- Treat missing documents as normal empty-state results.

### 3.5 Rewrite Vector Search

In `backend/app/services/vector_store.py`:

```python
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector


def upsert_chunk(self, user_id: str, chunk_id: str, payload: dict, embedding: list[float]) -> None:
    self._client.collection("users").document(user_id).collection("rag_chunks").document(chunk_id).set(
        {**payload, "embedding": Vector(embedding)}
    )


def similarity_search(self, user_id: str, embedding: list[float], top_k: int) -> list[dict]:
    query = (
        self._client.collection("users")
        .document(user_id)
        .collection("rag_chunks")
        .find_nearest(
            vector_field="embedding",
            query_vector=Vector(embedding),
            distance_measure=DistanceMeasure.COSINE,
            limit=top_k,
        )
    )
    return [snapshot.to_dict() for snapshot in query.stream()]
```

Create the required vector index:

```bash
gcloud firestore indexes composite create \
  --collection-group=rag_chunks \
  --query-scope=COLLECTION \
  --field-config field-path=embedding,vector-config='{"dimension":"768","flat":"{}"}' \
  --database='(default)'
```

If later queries add metadata filters, create the additional composite vector index from the failed-query error or define it explicitly with additional `--field-config` arguments.

---

## Terraform

Add to `gcp-infra/modules/firestore/main.tf`:

```hcl
variable "project_id" { type = string }
variable "region" { type = string }

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
}
```

Firestore can have only one `(default)` database, and location selection is effectively permanent. Confirm the project is dedicated to this PoC before applying.

---

## Local Development

Use the Firestore emulator for CRUD repository tests:

```bash
firebase emulators:start --only firestore
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
```

Run vector search integration tests against a dedicated GCP development project. Do not claim emulator coverage for vector nearest-neighbor behavior.

---

## Cost Notes

- Firestore provides free quota for exactly one database per project.
- TTL deletes are billable operations.
- Vector search has index-entry read charges in addition to document reads.
- Bound `RAG_TOP_K`, cap document pages, and reject excessive chunk counts.

References:

- [Firestore pricing](https://firebase.google.com/docs/firestore/pricing)
- [Firestore vector search](https://firebase.google.com/docs/firestore/vector-search)
- [Firestore locations](https://cloud.google.com/firestore/docs/locations)

---

## Verification

- [ ] Firestore database is Native Mode in `asia-south1`.
- [ ] Repository CRUD tests run against the emulator.
- [ ] Vector upsert and nearest-neighbor query pass against a development GCP project.
- [ ] A user cannot query another user's conversations or chunks.
- [ ] Chunk count is capped before embedding and indexing.

---

## Next Phase

→ [Phase 4 — Firebase Authentication](./PHASE_4_FIREBASE_AUTH.md)
