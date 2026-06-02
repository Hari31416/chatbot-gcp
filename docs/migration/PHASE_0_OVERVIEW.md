# Phase 0 — Migration Overview & Roadmap

> Master document for the Azure → GCP migration of the Serverless Chatbot application.
> AWS is historical context only. Each implementation phase has a dedicated plan in this directory.

---

## Migration Principles

1. **Azure remains deployable until cutover** — add GCP infrastructure and adapters incrementally.
2. **Minimal-cost PoC** — choose scale-to-zero compute, one Firestore database, small retention windows, and billing alerts.
3. **Mumbai-first deployment** — deploy application resources in `asia-south1` unless a documented cost trade-off justifies another region.
4. **Empty GCP data plane** — do not migrate Cosmos DB records or Blob Storage objects.
5. **Backend first, frontend second** — move server-side adapters before switching the React SPA.
6. **Terraform-managed infrastructure** — replace Azure Bicep with GCP Terraform modules without deleting Azure files before Phase 10.

---

## Target Architecture

```txt
[ STATIC SITE ]
Browser ───────────────────────────────► Firebase Hosting

[ AUTHENTICATION ]
Browser ───────────────────────────────► Firebase Authentication
   │                                          │
   └── Bearer ID token ───────────────────────┘

[ CHAT API + SSE ]
Browser ───────────────────────────────► Cloud Run: chatbot-api
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         ▼                     ▼                     ▼
                  Firestore Native       Cloud Storage        Secret Manager
              (history + vectors)    (uploads + staging)   (LiteLLM API keys)

[ ASYNC RAG INGESTION ]
Cloud Storage staging/ object finalized
   │
   ▼
Pub/Sub topic ──► Eventarc Pub/Sub trigger ──► Cloud Run: chatbot-worker
                                                   │
                                ┌──────────────────┼──────────────────┐
                                ▼                  ▼                  ▼
                         Cloud Storage        Document AI        Firestore
                                             OCR / Layout      vectors + status
```

The explicit Pub/Sub topic keeps ingestion decoupled and makes retries visible. A GCS object-finalize notification publishes metadata to the topic. The worker is a private Cloud Run service invoked by Eventarc with a dedicated service account.

---

## Dependency Graph

```txt
Phase 1 (Terraform + Project Scaffold)
    │
    ├──► Phase 2 (Cloud Storage)
    │        │
    │        └──► Phase 5 (Eventarc + Pub/Sub + Cloud Run Worker + Document AI)
    │
    ├──► Phase 3 (Firestore Native + Vector Search)
    ├──► Phase 4 (Firebase Authentication)
    └──► Phase 6 (Secret Manager)

Phase 7 (Cloud Run API)       ← depends on Phases 2–6
Phase 8 (Firebase Hosting)    ← depends on Phases 4 and 7
Phase 9 (Observability + Budgets)
Phase 10 (Cutover + Azure Cleanup)
```

---

## Phase Summary

| Phase | Title                   | Azure Service Replaced                          | GCP Target                                          | Complexity | Document                                                     |
| :---- | :---------------------- | :---------------------------------------------- | :-------------------------------------------------- | :--------- | :----------------------------------------------------------- |
| 0     | Overview & Roadmap      | —                                               | —                                                   | —          | _(this file)_                                                |
| 1     | Project Scaffold & IaC  | Bicep + `azd`                                   | Terraform + `gcloud` + Firebase CLI                 | Low        | [PHASE_1_SCAFFOLD.md](./PHASE_1_SCAFFOLD.md)                 |
| 2     | Object Storage          | Azure Blob Storage                              | Cloud Storage                                       | Low        | [PHASE_2_CLOUD_STORAGE.md](./PHASE_2_CLOUD_STORAGE.md)       |
| 3     | Firestore & Vectors     | Cosmos DB NoSQL + vectors                       | Firestore Native Mode + vector indexes              | Medium     | [PHASE_3_FIRESTORE.md](./PHASE_3_FIRESTORE.md)               |
| 4     | Authentication          | Clerk                                           | Firebase Authentication                             | Medium     | [PHASE_4_FIREBASE_AUTH.md](./PHASE_4_FIREBASE_AUTH.md)       |
| 5     | Event-Driven Ingestion  | Storage Queue + Functions + AI Doc Intelligence | Eventarc + Pub/Sub + Cloud Run worker + Document AI | Medium     | [PHASE_5_INGESTION.md](./PHASE_5_INGESTION.md)               |
| 6     | Secrets                 | Azure Key Vault                                 | Secret Manager                                      | Low        | [PHASE_6_SECRETS.md](./PHASE_6_SECRETS.md)                   |
| 7     | API Compute             | Azure Container Apps + ACR                      | Cloud Run + Artifact Registry                       | Low        | [PHASE_7_CLOUD_RUN_API.md](./PHASE_7_CLOUD_RUN_API.md)       |
| 8     | Frontend Hosting        | Azure Static Web Apps                           | Firebase Hosting                                    | Low        | [PHASE_8_FIREBASE_HOSTING.md](./PHASE_8_FIREBASE_HOSTING.md) |
| 9     | Observability & Budgets | Azure Monitor + App Insights                    | Cloud Logging + Monitoring + Billing Budgets        | Low        | [PHASE_9_OBSERVABILITY.md](./PHASE_9_OBSERVABILITY.md)       |
| 10    | Cutover & Cleanup       | Azure deployment                                | GCP deployment                                      | Low        | [PHASE_10_CUTOVER.md](./PHASE_10_CUTOVER.md)                 |

---

## Files Affected

| Area                 | Files                                                                                            | Main Change                                                                         |
| :------------------- | :----------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------- |
| Backend settings     | `backend/app/settings.py`                                                                        | Replace Azure settings with GCP project, bucket, Firebase, and Document AI settings |
| Dependency providers | `backend/app/dependencies.py`                                                                    | Replace Azure SDK clients and Clerk JWT validation                                  |
| Persistence          | `backend/app/repositories/conversation_repository.py`                                            | Replace Cosmos container operations with Firestore document operations              |
| Vector search        | `backend/app/services/vector_store.py`                                                           | Replace Cosmos `VectorDistance` query with Firestore nearest-neighbor query         |
| Object storage       | `backend/app/services/storage.py`                                                                | Replace Blob + SAS operations with GCS + signed URLs                                |
| RAG parsing          | `backend/app/services/rag.py`                                                                    | Replace Azure Document Intelligence client with Document AI                         |
| Worker               | `backend/function_app.py`, `backend/app/worker.py`                                               | Replace Azure Functions trigger with a Cloud Run CloudEvents endpoint               |
| Dependencies         | `backend/pyproject.toml`, `backend/uv.lock`                                                      | Remove Azure SDKs and add Google Cloud SDKs                                         |
| Frontend auth        | `frontend/src/main.tsx`, `frontend/src/services/auth.ts`, `frontend/src/components/AuthGate.tsx` | Replace Clerk React integration with Firebase Auth                                  |
| Frontend hosting     | `frontend/staticwebapp.config.json`, `frontend/firebase.json`, `frontend/.firebaserc`            | Replace SWA config with Firebase Hosting config                                     |
| Infrastructure       | `infra/`, `gcp-infra/`                                                                           | Preserve Bicep until cutover; add Terraform modules                                 |
| Deployment scripts   | `deploy-backend.sh`, `deploy-functions.sh`, `deploy-frontend.sh`                                 | Add GCP deployment commands                                                         |

---

## Cost Reality for `asia-south1`

The target is low cost, not a guaranteed `$0/month` deployment:

| Service           | Low-Cost Position                                                       | Important Constraint                                                                                               |
| :---------------- | :---------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------- |
| Cloud Run         | Scale API and worker to zero                                            | Use request-based billing and `min_instance_count = 0`                                                             |
| Firestore         | Free quota is suitable for a small PoC                                  | Exactly one database per project qualifies for free quota; TTL deletes are billed                                  |
| Cloud Storage     | Use `asia-south1` for latency                                           | Cloud Storage Always Free applies only to `us-west1`, `us-central1`, and `us-east1`, so Mumbai storage is billable |
| Pub/Sub           | Small PoC traffic generally fits the first 10 GiB/month free throughput | Avoid large payloads; publish object metadata, not document bytes                                                  |
| Eventarc Standard | Google and Pub/Sub source events are low cost                           | Pub/Sub transport and receiver Cloud Run usage still apply                                                         |
| Secret Manager    | Keep six or fewer active secret versions where possible                 | Free quota is aggregated per billing account                                                                       |
| Document AI       | Explicitly billable                                                     | OCR is cheaper than Layout Parser; make Layout Parser opt-in                                                       |
| Firebase Hosting  | Static hosting has a no-cost tier                                       | Monitor storage and transfer quotas                                                                                |
| Firebase Auth     | Use standard Firebase Authentication for the PoC                        | Identity Platform upgrade changes quotas and pricing                                                               |

---

## Official References

For the consolidated operational checklist, read [GCP Costing Gotchas](../GCP_COSTING_GOTCHAS.md) before provisioning resources.

- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Firestore pricing and free quota](https://firebase.google.com/docs/firestore/pricing)
- [Firestore vector search](https://firebase.google.com/docs/firestore/vector-search)
- [Firestore locations](https://cloud.google.com/firestore/docs/locations)
- [Cloud Storage pricing and Always Free regions](https://cloud.google.com/storage/pricing)
- [Pub/Sub pricing](https://cloud.google.com/pubsub/pricing)
- [Cloud Run Pub/Sub triggers through Eventarc](https://cloud.google.com/run/docs/triggering/pubsub-triggers)
- [Eventarc pricing](https://cloud.google.com/eventarc/pricing)
- [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)
- [Document AI pricing](https://cloud.google.com/document-ai/pricing)
- [Firebase Authentication](https://firebase.google.com/docs/auth)
- [Firebase Hosting quotas and pricing](https://firebase.google.com/docs/hosting/usage-quotas-pricing)

---

## Estimated Effort

| Phase             | Estimated Time  | Risk                                           |
| :---------------- | :-------------- | :--------------------------------------------- |
| 1 — Scaffold      | 2–3 hours       | Low                                            |
| 2 — Storage       | 2–4 hours       | Low                                            |
| 3 — Firestore     | 5–8 hours       | Medium — data model and vector query rewrite   |
| 4 — Firebase Auth | 4–6 hours       | Medium — frontend auth state rewrite           |
| 5 — Ingestion     | 6–9 hours       | Medium — CloudEvents, retries, and Document AI |
| 6 — Secrets       | 1–2 hours       | Low                                            |
| 7 — Cloud Run API | 2–4 hours       | Low                                            |
| 8 — Hosting       | 1–2 hours       | Low                                            |
| 9 — Observability | 1–3 hours       | Low                                            |
| 10 — Cutover      | 2–3 hours       | Low                                            |
| **Total**         | **26–44 hours** |                                                |
