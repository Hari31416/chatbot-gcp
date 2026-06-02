# Phase 3 — Cosmos DB Migration

> Replace Amazon DynamoDB (conversations, messages, context, RAG docs) **and** Amazon S3 Vectors with Azure Cosmos DB for NoSQL + integrated Vector Search.

---

## Goal

Migrate the single-table DynamoDB schema and the S3 Vectors store into a single Azure Cosmos DB account. Cosmos DB NoSQL supports both document storage and vector search, eliminating the need for a separate vector service.

---

## Current State (AWS)

### DynamoDB Single-Table Schema

| Partition Key (`pk`)     | Sort Key (`sk`)                     | Entity Type           | Fields                                                           |
| :----------------------- | :---------------------------------- | :-------------------- | :--------------------------------------------------------------- |
| `CONV#{conversation_id}` | `META`                              | Conversation metadata | `conversation_id`, `name`, `created_at`, `updated_at`, `user_id` |
| `CONV#{conversation_id}` | `MSG#{created_at}#{message_id}`     | Message               | `message_id`, `role`, `content`, `attachment(s)`                 |
| `CONV#{conversation_id}` | `CTX`                               | Context cache         | `messages[]`, `ttl`                                              |
| `USER#{user_id}`         | `RAGDOC#{created_at}#{document_id}` | RAG document record   | `document_id`, `filename`, `chunks_ingested`, `status`           |

**GSI:** `UserConversationsIndexV2` — pk: `user_id`, sk: `sk` (projects `conversation_id`, `name`, `created_at`, `updated_at`)

### S3 Vectors

| Setting   | Value                                                       |
| :-------- | :---------------------------------------------------------- |
| Bucket    | `chatbot-vectors-prod`                                      |
| Index     | `enterprise-kb`                                             |
| Dimension | 768                                                         |
| Distance  | cosine                                                      |
| Metadata  | `text`, `source_doc`, `document_id`, `user_id`, `chunk_idx` |

### Files Affected

| File                                          | AWS Dependency                                           |
| :-------------------------------------------- | :------------------------------------------------------- |
| `app/repositories/conversation_repository.py` | `boto3.dynamodb.conditions.Key`, DynamoDB Table resource |
| `app/services/vector_store.py`                | `boto3.client("s3vectors")`                              |
| `app/dependencies.py`                         | `get_dynamodb_table()`, `get_vector_store()`             |
| `app/settings.py`                             | `dynamodb_*`, `s3_vector_*` settings                     |

---

## Target State (Azure)

### Cosmos DB Account Setup

| Setting    | Value                                   |
| :--------- | :-------------------------------------- |
| API        | NoSQL                                   |
| Free Tier  | ✅ (1,000 RU/s + 25 GB free for life)   |
| Throughput | Manual 400 RU/s (fits within free tier) |
| Database   | `chatbot`                               |

### Container Design

Instead of a single table, use **two Cosmos DB containers**:

| Container       | Partition Key     | Purpose                                           | TTL             |
| :-------------- | :---------------- | :------------------------------------------------ | :-------------- |
| `conversations` | `/conversationId` | Conversations, Messages, Context, RAG doc records | ✅ per-item TTL |
| `vectors`       | `/userId`         | Vector embeddings for RAG                         | —               |

### Document Schema: `conversations` Container

**Conversation Metadata:**

```json
{
  "id": "{conversationId}_META",
  "conversationId": "abc-123",
  "type": "META",
  "userId": "user@example.com",
  "name": "New Chat...",
  "createdAt": "2026-05-26T00:00:00Z",
  "updatedAt": "2026-05-26T00:00:00Z"
}
```

**Message:**

```json
{
  "id": "{conversationId}_MSG_{createdAt}_{messageId}",
  "conversationId": "abc-123",
  "type": "MSG",
  "messageId": "msg-uuid",
  "role": "user",
  "content": "Hello!",
  "createdAt": "2026-05-26T00:00:00Z",
  "attachments": []
}
```

**Context Cache:**

```json
{
  "id": "{conversationId}_CTX",
  "conversationId": "abc-123",
  "type": "CTX",
  "messages": [],
  "ttl": 3600
}
```

**RAG Document Record:**

```json
{
  "id": "{userId}_RAGDOC_{createdAt}_{documentId}",
  "conversationId": "_user_{userId}",
  "type": "RAGDOC",
  "userId": "user@example.com",
  "documentId": "doc-uuid",
  "filename": "report.pdf",
  "chunksIngested": 12,
  "status": "ready",
  "createdAt": "2026-05-26T00:00:00Z"
}
```

> [!IMPORTANT]
> RAG documents use `conversationId = "_user_{userId}"` as a synthetic partition key since they're per-user, not per-conversation. This keeps everything in the same container with good partition distribution.

### Vector Schema: `vectors` Container

```json
{
  "id": "{documentId}#chunk-{idx}",
  "userId": "user@example.com",
  "documentId": "doc-uuid",
  "sourceDoc": "report.pdf",
  "chunkIdx": 0,
  "text": "The quick brown fox...",
  "embedding": [0.123, -0.456, ...]
}
```

**Vector Index Policy:**

```json
{
  "vectorIndexes": [
    {
      "path": "/embedding",
      "type": "quantizedFlat"
    }
  ]
}
```

**Vector Embedding Policy:**

```json
{
  "vectorEmbeddings": [
    {
      "path": "/embedding",
      "dataType": "float32",
      "dimensions": 768,
      "distanceFunction": "cosine"
    }
  ]
}
```

---

## Code Changes

### 3.1 Add Azure Cosmos DB SDK

```diff
 dependencies = [
   ...
   "azure-storage-blob>=12.20.0",
+  "azure-cosmos>=4.7.0",
   ...
 ]
```

### 3.2 Update `app/settings.py`

```python
# ── Azure Cosmos DB (Phase 3) ──
cosmos_endpoint: str | None = Field(
    default=None, validation_alias="COSMOS_ENDPOINT"
)
cosmos_key: str | None = Field(
    default=None, validation_alias="COSMOS_KEY"
)
cosmos_database_name: str = Field(
    default="chatbot", validation_alias="COSMOS_DATABASE_NAME"
)
cosmos_conversations_container: str = Field(
    default="conversations", validation_alias="COSMOS_CONTAINER_NAME"
)
cosmos_vectors_container: str = Field(
    default="vectors", validation_alias="COSMOS_VECTORS_CONTAINER_NAME"
)
```

### 3.3 Rewrite `app/repositories/conversation_repository.py`

Replace DynamoDB Table API with Cosmos DB container operations:

| DynamoDB Operation                        | Cosmos DB Equivalent                                                      |
| :---------------------------------------- | :------------------------------------------------------------------------ |
| `table.put_item(Item=...)`                | `container.upsert_item(body=...)`                                         |
| `table.get_item(Key=...)`                 | `container.read_item(item=id, partition_key=pk)`                          |
| `table.query(KeyCondition=...)`           | `container.query_items(query=..., partition_key=pk)`                      |
| `table.update_item(UpdateExpression=...)` | Read → modify → `container.upsert_item()`                                 |
| `table.batch_writer().delete_item()`      | Loop `container.delete_item()` (or use transactional batch)               |
| GSI query (`IndexName=...`)               | SQL query: `SELECT * FROM c WHERE c.userId = @userId AND c.type = 'META'` |

**Key method mappings:**

```python
class ConversationRepository:
    def __init__(self, container):
        self._container = container  # Cosmos ContainerProxy

    def create_conversation(self, conversation_id, created_at, user_id, name="New Chat..."):
        doc = {
            "id": f"{conversation_id}_META",
            "conversationId": conversation_id,
            "type": "META",
            "userId": user_id or "",
            "name": name,
            "createdAt": created_at,
            "updatedAt": created_at,
        }
        self._container.upsert_item(body=doc)

    def get_recent_messages(self, conversation_id, limit):
        query = (
            "SELECT * FROM c WHERE c.conversationId = @convId AND c.type = 'MSG' "
            "ORDER BY c.createdAt DESC OFFSET 0 LIMIT @limit"
        )
        params = [
            {"name": "@convId", "value": conversation_id},
            {"name": "@limit", "value": limit},
        ]
        items = list(self._container.query_items(
            query=query,
            parameters=params,
            partition_key=conversation_id,
        ))
        items.reverse()
        return items

    def get_user_conversations(self, user_id):
        query = "SELECT * FROM c WHERE c.userId = @userId AND c.type = 'META' ORDER BY c.updatedAt DESC"
        params = [{"name": "@userId", "value": user_id}]
        # Cross-partition query (no partition key filter)
        return list(self._container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        ))
```

> [!WARNING]
> `get_user_conversations` requires a **cross-partition query** since conversations have different partition keys. This uses slightly more RU/s. For scale, consider adding a separate `users` container or a change-feed based index. For development usage, this is fine within the free tier.

### 3.4 Rewrite `app/services/vector_store.py`

Replace S3 Vectors client with Cosmos DB vector operations:

```python
class VectorStoreClient:
    def __init__(self, container, embedding_model, dimension, gemini_api_key=None):
        self._container = container  # Cosmos ContainerProxy (vectors)
        self.embedding_model = embedding_model
        self.dimension = dimension
        self.gemini_api_key = gemini_api_key

    async def upsert_chunks(self, keys, texts, embeddings, source_doc, document_id, user_id):
        for idx, (key, text, vector) in enumerate(zip(keys, texts, embeddings)):
            doc = {
                "id": key,
                "userId": user_id,
                "documentId": document_id,
                "sourceDoc": source_doc,
                "chunkIdx": idx,
                "text": text,
                "embedding": list(vector),
            }
            await to_thread.run_sync(
                lambda d=doc: self._container.upsert_item(body=d)
            )

    async def similarity_search(self, query_text, user_id, top_k=3, documents=None):
        query_embeddings = await self.get_embeddings([query_text])
        if not query_embeddings:
            return []

        # Cosmos DB NoSQL Vector Search query
        vector_str = str(query_embeddings[0])
        filter_clause = "c.userId = @userId"
        params = [{"name": "@userId", "value": user_id}]

        if documents:
            placeholders = ", ".join(f"@doc{i}" for i in range(len(documents)))
            filter_clause += f" AND c.sourceDoc IN ({placeholders})"
            for i, doc in enumerate(documents):
                params.append({"name": f"@doc{i}", "value": doc})

        query = f"""
        SELECT TOP @topK
            c.id, c.text, c.sourceDoc, c.documentId,
            VectorDistance(c.embedding, {vector_str}) AS score
        FROM c
        WHERE {filter_clause}
        ORDER BY VectorDistance(c.embedding, {vector_str})
        """
        params.append({"name": "@topK", "value": top_k})

        items = list(self._container.query_items(
            query=query, parameters=params, enable_cross_partition_query=True
        ))
        return [
            {"key": item["id"], "text": item["text"], "source": item["sourceDoc"], "score": round(1 - item.get("score", 1), 4)}
            for item in items
        ]
```

### 3.5 Update `app/dependencies.py`

```python
from azure.cosmos import CosmosClient

@lru_cache
def get_cosmos_client():
    settings = get_settings()
    return CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)

@lru_cache
def get_conversations_container():
    client = get_cosmos_client()
    settings = get_settings()
    db = client.get_database_client(settings.cosmos_database_name)
    return db.get_container_client(settings.cosmos_conversations_container)

@lru_cache
def get_vectors_container():
    client = get_cosmos_client()
    settings = get_settings()
    db = client.get_database_client(settings.cosmos_database_name)
    return db.get_container_client(settings.cosmos_vectors_container)

def get_repository() -> ConversationRepository:
    container = get_conversations_container()
    return ConversationRepository(container)

def get_vector_store() -> VectorStoreClient:
    settings = get_settings()
    container = get_vectors_container()
    # ... resolve embedding API key ...
    return VectorStoreClient(
        container=container,
        embedding_model=settings.litellm_embedding_model,
        dimension=settings.embedding_dimension,
        gemini_api_key=api_key,
    )
```

---

## Bicep Module: `infra/modules/cosmos.bicep`

```bicep
param location string
param environmentName string

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: 'cosmos-chatbot-${environmentName}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    enableFreeTier: true
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableNoSQLVectorSearch' }
    ]
    locations: [{ locationName: location, failoverPriority: 0 }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-11-15' = {
  parent: cosmosAccount
  name: 'chatbot'
  properties: {
    resource: { id: 'chatbot' }
  }
}

resource conversationsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: database
  name: 'conversations'
  properties: {
    resource: {
      id: 'conversations'
      partitionKey: { paths: ['/conversationId'], kind: 'Hash' }
      defaultTtl: -1  // Enable per-item TTL
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [{ path: '/_etag/?' }]
      }
    }
    options: { throughput: 400 }  // Manual 400 RU/s (within free tier)
  }
}

resource vectorsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: database
  name: 'vectors'
  properties: {
    resource: {
      id: 'vectors'
      partitionKey: { paths: ['/userId'], kind: 'Hash' }
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [
          { path: '/embedding/*' }
          { path: '/_etag/?' }
        ]
        vectorIndexes: [
          { path: '/embedding', type: 'quantizedFlat' }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            dimensions: 768
            distanceFunction: 'cosine'
          }
        ]
      }
    }
    options: { throughput: 400 }
  }
}

output cosmosAccountName string = cosmosAccount.name
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
```

---

## Local Development

Use the **Azure Cosmos DB Emulator** for local development:

```bash
# macOS (Docker-based emulator)
docker run -p 8081:8081 -p 10250-10255:10250-10255 \
  mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:latest

# Connection settings:
COSMOS_ENDPOINT=https://localhost:8081
COSMOS_KEY=C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==
```

---

## Verification

- [ ] `ConversationRepository` CRUD operations work against Cosmos DB
- [ ] `get_user_conversations` cross-partition query returns correct results
- [ ] `VectorStoreClient.upsert_chunks` stores embeddings with correct schema
- [ ] `VectorStoreClient.similarity_search` returns ranked results using `VectorDistance`
- [ ] TTL-based expiry works for context cache documents
- [ ] All existing backend tests pass with mocked Cosmos containers
- [ ] RU/s consumption stays ≤ 400 during development

---

## Next Phase

→ [Phase 4 — Authentication](./PHASE_4_AUTH.md)
