# GCP Costing Gotchas

> A practical guide to keeping the GCP chatbot PoC inexpensive in `asia-south1`.
> Read this before provisioning resources or uploading large documents.

---

## Quick Summary

This deployment is designed to cost very little, but it is **not guaranteed to cost `$0/month`**.

| Category                               | Services                                                                                                                                          | Cost Position                         |
| :------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------ | :------------------------------------ |
| Free quota usually covers a small PoC  | Cloud Run, Firestore, Pub/Sub, Eventarc, Secret Manager, Firebase Hosting, Firebase Authentication, Cloud Logging, Cloud Build, Artifact Registry | `$0` while usage remains within quota |
| Billable in the selected Mumbai region | Cloud Storage in `asia-south1`                                                                                                                    | Small storage and operation charges   |
| Explicitly metered                     | Document AI, third-party LLM and embedding APIs                                                                                                   | Usage-dependent                       |

The safest starting point is a `$10` billing budget alert, strict document limits, scale-to-zero Cloud Run services, and seven-day lifecycle cleanup for temporary objects.

---

## Target PoC Architecture

```txt
Firebase Hosting
   │
   ▼
Cloud Run API ──► Firestore Native Mode
   │             Cloud Storage
   │             Secret Manager
   ▼
GCS staging/ ──► Pub/Sub ──► Eventarc ──► Private Cloud Run Worker
                                               │
                                               ├──► Document AI
                                               └──► LiteLLM embeddings
```

Primary application region: `asia-south1` (Mumbai).

---

## Service Cost Matrix

| Service                 | PoC Configuration                                                         | Main Gotcha                                                               |
| :---------------------- | :------------------------------------------------------------------------ | :------------------------------------------------------------------------ |
| Cloud Run API           | Request-based billing, `min_instance_count = 0`, `max_instance_count = 3` | A minimum instance or uncapped scaling can consume free quota quickly     |
| Cloud Run worker        | Private service, `min_instance_count = 0`, `max_instance_count = 2`       | Duplicate deliveries and retries can repeat OCR and embedding work        |
| Firestore Native Mode   | One `(default)` database in `asia-south1`                                 | TTL deletes and vector index reads are billable                           |
| Cloud Storage           | One private Standard bucket in `asia-south1`                              | Mumbai is outside Cloud Storage Always Free regions                       |
| Pub/Sub                 | Metadata messages only                                                    | Publishing document bytes increases throughput and storage costs          |
| Eventarc Standard       | One Pub/Sub trigger                                                       | Receiver Cloud Run usage and Pub/Sub transport still apply                |
| Secret Manager          | Only third-party API keys                                                 | Old active secret versions accumulate                                     |
| Document AI             | OCR by default, Layout Parser opt-in                                      | Every processed page is billable                                          |
| Firebase Hosting        | Static Vite assets only                                                   | Large downloads and media files consume hosting transfer quota            |
| Firebase Authentication | Standard Firebase Auth email/password                                     | Upgrading to Identity Platform changes pricing behavior                   |
| Cloud Logging           | `INFO` level, no payload logging                                          | Streaming tokens and extracted document text can create large log volumes |
| Artifact Registry       | One Docker repository, prune old images                                   | Old container images accumulate storage                                   |
| Cloud Build             | Build only deployment images                                              | Frequent builds can exceed free build minutes                             |

---

## Configuration Traps

### Trap #1 — Cloud Run Minimum Instances

| Setting                  | Impact                                                            |
| :----------------------- | :---------------------------------------------------------------- |
| `min_instance_count = 0` | Correct for PoC: API and worker scale to zero                     |
| `min_instance_count = 1` | Keeps an instance warm continuously and creates idle compute cost |

Use:

```hcl
scaling {
  min_instance_count = 0
  max_instance_count = 3
}
```

Verify:

```bash
gcloud run services describe chatbot-api \
  --region asia-south1 \
  --format='yaml(spec.template.metadata.annotations,spec.template.spec.containerConcurrency)'
```

**Trade-off:** Scale-to-zero introduces cold-start latency. That is acceptable for this PoC.

Reference: [Cloud Run pricing](https://cloud.google.com/run/pricing)

---

### Trap #2 — Uncapped Cloud Run Scaling

Scale-to-zero does not cap burst cost. A loop, load test, or abusive client can still create many instances.

Use conservative caps:

```hcl
# API
max_instance_count = 3

# Worker
max_instance_count = 2
```

Also cap FastAPI request size and ingestion document size. Raise limits only after measuring actual load.

---

### Trap #3 — Assuming Mumbai Cloud Storage Is Always Free

Cloud Storage Always Free usage applies only in:

- `us-west1`
- `us-central1`
- `us-east1`

The selected `asia-south1` bucket is billable. It is still the correct default for this PoC because it keeps user upload latency closer to the Mumbai Cloud Run services.

Use one private Standard bucket:

```hcl
resource "google_storage_bucket" "uploads" {
  location      = "asia-south1"
  storage_class = "STANDARD"
}
```

Do not choose multi-region storage, dual-region storage, or unnecessary replication for this PoC.

Reference: [Cloud Storage pricing](https://cloud.google.com/storage/pricing)

---

### Trap #4 — Leaving Temporary GCS Objects Behind

Documents uploaded under `staging/` and intermediate files under `rag-temp/` should not accumulate.

Use lifecycle cleanup:

```hcl
lifecycle_rule {
  action { type = "Delete" }
  condition {
    age            = 7
    matches_prefix = ["staging/", "rag-temp/"]
  }
}
```

The worker should also delete staging objects after successful processing. Lifecycle cleanup is the fallback for failed jobs.

---

### Trap #5 — Sending Document Bytes Through Pub/Sub

Pub/Sub should carry object metadata, not uploaded file content.

Correct message shape:

```json
{
  "bucket": "project-chatbot-dev",
  "name": "staging/user-id/document-id/report.pdf",
  "generation": "..."
}
```

The worker downloads the object from GCS. This keeps Pub/Sub throughput small and avoids unnecessary message-storage cost.

Reference: [Pub/Sub pricing](https://cloud.google.com/pubsub/pricing)

---

### Trap #6 — Retrying OCR and Embeddings on Duplicate Events

Pub/Sub and Eventarc provide at-least-once delivery. A worker may receive the same object event more than once.

Without idempotency, duplicate processing repeats:

- GCS downloads
- Document AI page processing
- LiteLLM embedding calls
- Firestore writes

Mitigation:

1. Store the GCS object `generation`.
2. Use a deterministic document ID.
3. Use deterministic chunk IDs: `{document_id}:{chunk_index}`.
4. Skip work when the same generation is already `ready`.
5. Return non-`2xx` only for retryable failures.

See [Phase 5 — Event-Driven Ingestion](./gcp-migration/PHASE_5_INGESTION.md).

---

### Trap #7 — Treating Document AI as a Free OCR Service

Document AI is explicitly metered. It is the largest first-party GCP cost risk in this PoC.

Use this policy:

| Input                      | Parser                                     |
| :------------------------- | :----------------------------------------- |
| `.txt`, `.md`              | Decode locally                             |
| PDFs and images            | Enterprise Document OCR                    |
| Layout-sensitive documents | Layout Parser only when explicitly enabled |

Add hard limits:

```bash
DOCUMENT_AI_USE_LAYOUT_PARSER=false
MAX_RAG_PAGES=25
MAX_RAG_CHUNKS=200
```

Do not bulk-upload books or large PDF libraries during smoke testing.

Reference: [Document AI pricing](https://cloud.google.com/document-ai/pricing)

---

### Trap #8 — Firestore Vector Queries Are Not Free Reads

Firestore is suitable for this PoC, but vector search has its own billing behavior:

- Vector index entries scanned are billable.
- Returned documents are billable reads.
- Larger `RAG_TOP_K` values return more documents.
- Broad, poorly filtered searches scan more index entries.

Start with:

```bash
RAG_TOP_K=3
MAX_RAG_CHUNKS=200
```

Keep chunks in user-scoped collections and add metadata filters only with the required composite indexes.

Reference: [Firestore vector search pricing](https://firebase.google.com/docs/firestore/pricing#vector_search)

---

### Trap #9 — Firestore TTL Deletes Still Cost Money

Firestore TTL is useful for sliding context cleanup, but TTL deletes are billable delete operations. TTL is a cleanup mechanism, not free storage management.

Mitigation:

- Use TTL only for short-lived context records.
- Keep conversation history intentionally bounded.
- Do not write a new TTL document for every streamed token.

Reference: [Firestore pricing](https://firebase.google.com/docs/firestore/pricing)

---

### Trap #10 — Creating Multiple Firestore Databases

Firestore free quota applies to one database per project. Additional databases do not inherit the free quota.

Use a single database:

```bash
FIRESTORE_DATABASE=(default)
```

Choose its location carefully. Firestore database location cannot be changed after provisioning without creating a new database and migrating data.

Reference: [Firestore locations](https://cloud.google.com/firestore/docs/locations)

---

### Trap #11 — Excessive Secret Manager Versions

Secret Manager charges based partly on active secret versions and access operations.

Keep only the secrets this architecture needs:

- `litellm-api-key`
- `litellm-vision-api-key`
- `litellm-embedding-api-key`, only if separate

Disable or destroy stale versions after rotation:

```bash
gcloud secrets versions list litellm-api-key
gcloud secrets versions disable VERSION_ID --secret=litellm-api-key
```

Prefer Cloud Run startup injection over Secret Manager reads on every request.

Reference: [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)

---

### Trap #12 — Logging Tokens, Prompts, and Extracted Text

Cloud Run automatically sends stdout and stderr logs to Cloud Logging. Debug logging can become expensive and can expose sensitive data.

Use:

```bash
LOG_LEVEL=INFO
```

Never log:

- Firebase ID tokens
- LiteLLM API keys
- Signed GCS URLs
- Full prompts
- Streamed model tokens
- Extracted document contents
- Uploaded file bytes

Reference: [Google Cloud Observability pricing](https://cloud.google.com/stackdriver/pricing)

---

### Trap #13 — Artifact Registry Image Accumulation

Every deployment creates container image layers. Old tags and untagged images accumulate storage.

Mitigation:

- Use one Docker repository.
- Deploy immutable commit-based tags.
- Configure an Artifact Registry cleanup policy after validating rollback needs.
- Keep a small number of recent API and worker images.

Inspect storage:

```bash
gcloud artifacts docker images list \
  "asia-south1-docker.pkg.dev/$GCP_PROJECT_ID/chatbot" \
  --include-tags
```

Reference: [Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing)

---

### Trap #14 — Firebase Hosting Used for Uploaded Files

Firebase Hosting should contain only the built React application. User uploads, images, and RAG documents belong in GCS.

Correct:

```txt
frontend/dist/**        → Firebase Hosting
uploads/**              → Private GCS bucket
staging/**              → Private GCS bucket
```

Reference: [Firebase Hosting quotas and pricing](https://firebase.google.com/docs/hosting/usage-quotas-pricing)

---

### Trap #15 — Budget Alerts Do Not Stop Spending

A Cloud Billing budget sends notifications. It does not automatically disable services.

Create a PoC alert:

```bash
gcloud billing budgets create \
  --billing-account="$GCP_BILLING_ACCOUNT_ID" \
  --display-name="chatbot-poc-budget" \
  --budget-amount=10USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0
```

For this PoC, treat a budget notification as an operational stop signal and inspect usage before continuing tests.

Reference: [Cloud Billing budgets](https://cloud.google.com/billing/docs/how-to/budgets)

---

## Recommended PoC Guardrails

| Setting                            | Recommended Value     |
| :--------------------------------- | :-------------------- |
| `GCP_REGION`                       | `asia-south1`         |
| Cloud Run API minimum instances    | `0`                   |
| Cloud Run API maximum instances    | `3`                   |
| Cloud Run worker minimum instances | `0`                   |
| Cloud Run worker maximum instances | `2`                   |
| GCS storage class                  | `STANDARD`            |
| GCS temporary object lifecycle     | Delete after `7` days |
| `RAG_TOP_K`                        | `3`                   |
| `MAX_RAG_PAGES`                    | `25`                  |
| `MAX_RAG_CHUNKS`                   | `200`                 |
| `DOCUMENT_AI_USE_LAYOUT_PARSER`    | `false`               |
| `LOG_LEVEL`                        | `INFO`                |
| Initial billing budget             | `$10`                 |

---

## Pre-Provisioning Checklist

- [ ] Billing account is linked to the GCP project.
- [ ] A `$10` budget alert exists with `50%`, `90%`, and `100%` thresholds.
- [ ] Firestore uses only the `(default)` database.
- [ ] Cloud Run API and worker use `min_instance_count = 0`.
- [ ] Both Cloud Run services have conservative maximum instance counts.
- [ ] The GCS bucket is Standard storage with seven-day cleanup for temporary prefixes.
- [ ] Pub/Sub messages contain object metadata only.
- [ ] Worker processing is idempotent for duplicate delivery.
- [ ] OCR uses Document AI only for PDFs and images.
- [ ] Layout Parser is disabled by default.
- [ ] Logs do not contain secrets, prompts, tokens, signed URLs, or document content.
- [ ] Artifact Registry cleanup is planned after rollback images are identified.

---

## Useful Cost Inspection Commands

```bash
# Cloud Run configuration
gcloud run services describe chatbot-api --region asia-south1
gcloud run services describe chatbot-worker --region asia-south1

# Stored objects and approximate sizes
gcloud storage du --summarize "gs://$GCS_BUCKET_NAME/**"

# Container images
gcloud artifacts docker images list \
  "asia-south1-docker.pkg.dev/$GCP_PROJECT_ID/chatbot" \
  --include-tags

# Secrets and versions
gcloud secrets list
gcloud secrets versions list litellm-api-key

# Recent errors
gcloud logging read \
  'resource.type="cloud_run_revision" severity>=ERROR' \
  --limit 50
```

---

## Related Migration Plans

- [Phase 0 — GCP Migration Overview](./gcp-migration/PHASE_0_OVERVIEW.md)
- [Phase 2 — Cloud Storage](./gcp-migration/PHASE_2_CLOUD_STORAGE.md)
- [Phase 3 — Firestore Native Mode](./gcp-migration/PHASE_3_FIRESTORE.md)
- [Phase 5 — Event-Driven Ingestion](./gcp-migration/PHASE_5_INGESTION.md)
- [Phase 7 — Cloud Run API](./gcp-migration/PHASE_7_CLOUD_RUN_API.md)
- [Phase 9 — Observability & Budgets](./gcp-migration/PHASE_9_OBSERVABILITY.md)

---

## Official References

- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Cloud Storage pricing](https://cloud.google.com/storage/pricing)
- [Firestore pricing](https://firebase.google.com/docs/firestore/pricing)
- [Firestore vector search](https://firebase.google.com/docs/firestore/vector-search)
- [Firestore locations](https://cloud.google.com/firestore/docs/locations)
- [Pub/Sub pricing](https://cloud.google.com/pubsub/pricing)
- [Eventarc pricing](https://cloud.google.com/eventarc/pricing)
- [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)
- [Document AI pricing](https://cloud.google.com/document-ai/pricing)
- [Firebase Hosting quotas and pricing](https://firebase.google.com/docs/hosting/usage-quotas-pricing)
- [Firebase Authentication](https://firebase.google.com/docs/auth)
- [Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing)
- [Cloud Build pricing](https://cloud.google.com/build/pricing)
- [Google Cloud Observability pricing](https://cloud.google.com/stackdriver/pricing)
- [Cloud Billing budgets](https://cloud.google.com/billing/docs/how-to/budgets)
