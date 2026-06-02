# Phase 0 — Migration Overview & Roadmap

> Master document for the AWS → Azure migration of the Serverless Chatbot application.
> Each phase has its own dedicated plan in this directory.

---

## Migration Principles

1. **Service-by-service** — Migrate one AWS service at a time, keep the app functional after each phase.
2. **Backend first, frontend second** — Decouple cloud SDKs in Python before touching the React UI.
3. **No big-bang cutover** — Use environment variables and feature flags to toggle between AWS and Azure clients during development.
4. **Free-tier first** — Target Azure's Always Free and 12-month Free tiers to keep costs at $0 during development.
5. **IaC parity** — Replace `template.yaml` (SAM) with `infra/main.bicep` (Bicep) incrementally.

---

## Dependency Graph

```txt
Phase 1 (IaC + Project Scaffold)
    │
    ├──► Phase 2 (Blob Storage — replaces S3)
    │        │
    │        └──► Phase 5 (Event-Driven Ingestion — depends on Blob + Queue + Functions)
    │
    ├──► Phase 3 (Cosmos DB — replaces DynamoDB + S3 Vectors)
    │
    ├──► Phase 4 (Auth — replaces Cognito)
    │
    └──► Phase 6 (Secrets — replaces SSM)

Phase 7 (Container Apps — replaces Lambda)  ← depends on Phases 2-6
Phase 8 (Static Web Apps — replaces S3 Website) ← depends on Phase 4
Phase 9 (Observability — replaces CloudWatch)
Phase 10 (Cleanup & Cutover)
```

---

## Phase Summary

| Phase | Title                            | AWS Service Replaced           | Azure Target                                           | Complexity | Document                                                   |
| :---- | :------------------------------- | :----------------------------- | :----------------------------------------------------- | :--------- | :--------------------------------------------------------- |
| 0     | Overview & Roadmap               | —                              | —                                                      | —          | _(this file)_                                              |
| 1     | Project Scaffold & IaC Bootstrap | SAM `template.yaml`            | Bicep + `azd`                                          | Low        | [PHASE_1_SCAFFOLD.md](./PHASE_1_SCAFFOLD.md)               |
| 2     | Blob Storage                     | S3 (Uploads)                   | Azure Blob Storage                                     | Low        | [PHASE_2_BLOB_STORAGE.md](./PHASE_2_BLOB_STORAGE.md)       |
| 3     | Cosmos DB                        | DynamoDB + S3 Vectors          | Cosmos DB NoSQL + Vector Search                        | Medium     | [PHASE_3_COSMOS_DB.md](./PHASE_3_COSMOS_DB.md)             |
| 4     | Authentication                   | Cognito User Pools             | Microsoft Entra External ID                            | Medium     | [PHASE_4_AUTH.md](./PHASE_4_AUTH.md)                       |
| 5     | Event-Driven Ingestion           | SQS + Lambda Worker + Textract | Storage Queues + Azure Functions + AI Doc Intelligence | Medium     | [PHASE_5_INGESTION.md](./PHASE_5_INGESTION.md)             |
| 6     | Secrets Management               | SSM Parameter Store            | Azure Key Vault                                        | Low        | [PHASE_6_SECRETS.md](./PHASE_6_SECRETS.md)                 |
| 7     | Compute & Deployment             | Lambda + LWA + API Gateway     | Azure Container Apps                                   | Low        | [PHASE_7_CONTAINER_APPS.md](./PHASE_7_CONTAINER_APPS.md)   |
| 8     | Frontend Hosting                 | S3 Static Website              | Azure Static Web Apps                                  | Low        | [PHASE_8_STATIC_WEB_APPS.md](./PHASE_8_STATIC_WEB_APPS.md) |
| 9     | Observability                    | CloudWatch Logs                | Azure Monitor + App Insights                           | Low        | [PHASE_9_OBSERVABILITY.md](./PHASE_9_OBSERVABILITY.md)     |
| 10    | Cleanup & Cutover                | —                              | —                                                      | Low        | [PHASE_10_CUTOVER.md](./PHASE_10_CUTOVER.md)               |

---

## Files Affected (Full Inventory)

### Backend (`backend/`)

| File                                          | AWS Dependencies                                                | Phases        |
| :-------------------------------------------- | :-------------------------------------------------------------- | :------------ |
| `app/settings.py`                             | `aws_region`, `dynamodb_*`, `s3_*`, `cognito_*`, `s3_vector_*`  | 2, 3, 4, 6    |
| `app/dependencies.py`                         | `boto3` (DynamoDB, S3, SSM, Textract, S3 Vectors), Cognito JWKS | 2, 3, 4, 5, 6 |
| `app/main.py`                                 | `mangum` (Lambda adapter)                                       | 7             |
| `app/repositories/conversation_repository.py` | `boto3.dynamodb.conditions`, DynamoDB Table API                 | 3             |
| `app/services/storage.py`                     | S3 `put_object`, `generate_presigned_url`                       | 2             |
| `app/services/vector_store.py`                | `boto3` S3 Vectors client (`s3vectors`)                         | 3             |
| `app/services/rag.py`                         | S3 client, Textract client                                      | 2, 5          |
| `app/services/llm.py`                         | _(none — uses LiteLLM, cloud-agnostic)_                         | —             |
| `app/worker.py`                               | SQS event handler, S3 `get_object`/`delete_object`              | 5             |
| `pyproject.toml`                              | `boto3`, `mangum`                                               | 2, 3, 7       |

### Frontend (`frontend/`)

| File                          | AWS Dependencies                                        | Phases |
| :---------------------------- | :------------------------------------------------------ | :----- |
| `src/services/auth.ts`        | Cognito REST API, `VITE_COGNITO_*`, `VITE_AWS_REGION`   | 4      |
| `src/components/AuthGate.tsx` | Cognito auth functions                                  | 4      |
| `src/services/api.ts`         | Token retrieval from Cognito auth                       | 4      |
| `.env` / `.env.example`       | `VITE_COGNITO_CLIENT_ID`, `VITE_AWS_REGION`, Lambda URL | 4, 8   |

### Infrastructure

| File                 | Purpose                               | Phases                |
| :------------------- | :------------------------------------ | :-------------------- |
| `template.yaml`      | SAM/CloudFormation (entire AWS stack) | 1 (replaced by Bicep) |
| `deploy-backend.sh`  | SAM deploy script                     | 7                     |
| `deploy-frontend.sh` | S3 sync deploy script                 | 8                     |

---

## Estimated Effort

| Phase               | Estimated Time   | Risk                             |
| :------------------ | :--------------- | :------------------------------- |
| 1 — Scaffold        | 1–2 hours        | Low                              |
| 2 — Blob Storage    | 2–3 hours        | Low                              |
| 3 — Cosmos DB       | 4–6 hours        | Medium — schema redesign         |
| 4 — Auth            | 4–6 hours        | Medium — MSAL.js frontend rework |
| 5 — Ingestion       | 4–6 hours        | Medium — new trigger model       |
| 6 — Secrets         | 1–2 hours        | Low                              |
| 7 — Container Apps  | 2–3 hours        | Low — FastAPI runs natively      |
| 8 — Static Web Apps | 1–2 hours        | Low                              |
| 9 — Observability   | 1–2 hours        | Low                              |
| 10 — Cutover        | 1–2 hours        | Low                              |
| **Total**           | **~21–34 hours** |                                  |
