# Phase 10 — Cleanup & Cutover

> Final cleanup of AWS artifacts, dependency removal, and production cutover checklist.

---

## Goal

Remove all AWS-specific code, dependencies, and configuration. Archive the original `template.yaml` and deploy scripts. Verify the fully Azure-native stack is operational.

---

## Cleanup Tasks

### 10.1 Remove AWS SDK Dependencies

**`backend/pyproject.toml`** — final state:

```toml
[project]
name = "chatbot-backend"
version = "0.2.0"
description = "Backend for serverless chatbot (Azure)"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn>=0.30.0",
  "pydantic-settings>=2.4.0",
  "python-multipart>=0.0.9",
  "azure-storage-blob>=12.20.0",
  "azure-cosmos>=4.7.0",
  "azure-ai-documentintelligence>=1.0.0",
  "azure-identity>=1.17.0",
  "azure-keyvault-secrets>=4.8.0",
  "litellm>=1.41.0",
  "PyJWT>=2.8.0",
  "cryptography>=42.0.0",
]
```

Removed:

- `boto3` ❌
- `mangum` ❌

### 10.2 Remove AWS-Specific Files

| File                    | Action                                  | Reason                                                   |
| :---------------------- | :-------------------------------------- | :------------------------------------------------------- |
| `template.yaml`         | Archive to `docs/archive/template.yaml` | SAM/CFN template — no longer used                        |
| `deploy-backend.sh`     | Replace                                 | Already replaced with Azure deploy script in Phase 7     |
| `deploy-frontend.sh`    | Replace                                 | Already replaced with SWA deploy script in Phase 8       |
| `backend/app/worker.py` | Delete                                  | Replaced by `functions/ingestion_worker/` in Phase 5     |
| `get_urls.sh`           | Delete                                  | Extracts AWS CloudFormation outputs — no longer relevant |
| `.env.example`          | Replace                                 | Replaced by `.env.azure.example`                         |

### 10.3 Remove AWS Code from Backend

Verify no remaining references to:

```bash
# Run these grep checks
grep -r "boto3" backend/app/         # Should return zero results
grep -r "dynamodb" backend/app/      # Should return zero results
grep -r "s3vectors" backend/app/     # Should return zero results
grep -r "textract" backend/app/      # Should return zero results
grep -r "cognito" backend/app/       # Should return zero results
grep -r "ssm" backend/app/           # Should return zero results
grep -r "mangum" backend/app/        # Should return zero results
grep -r "aws" backend/app/           # Review any matches
grep -r "lambda" backend/app/        # Review any matches (may have valid non-AWS uses)
```

### 10.4 Remove AWS Code from Frontend

Verify no remaining references to:

```bash
grep -r "cognito" frontend/src/      # Should return zero results
grep -r "VITE_AWS" frontend/src/     # Should return zero results
grep -r "VITE_COGNITO" frontend/src/ # Should return zero results
grep -r "X-Amz" frontend/src/       # Should return zero results
```

### 10.5 Update `.env.example`

Replace the root `.env.example` with Azure-flavored variables (copy from `.env.azure.example` created in Phase 1):

```bash
cp .env.azure.example .env.example
rm .env.azure.example  # Consolidate to one file
```

### 10.6 Update `.gitignore`

```diff
+ # Azure
+ .azure/
+ local.settings.json
+
  # Environment
  .env
  .env.local
+ .env.azure
```

### 10.7 Archive AWS Infrastructure

```bash
mkdir -p docs/archive
mv template.yaml docs/archive/template.yaml
mv get_urls.sh docs/archive/get_urls.sh
```

---

## Final Project Structure

```
chatbot-azure/
├── azure.yaml                          # azd project manifest
├── infra/
│   ├── main.bicep                      # Bicep orchestrator
│   ├── main.parameters.json
│   └── modules/
│       ├── storage.bicep               # Blob Storage + Storage Queue
│       ├── cosmos.bicep
│       ├── functions.bicep
│       ├── keyvault.bicep
│       ├── container-apps.bicep
│       ├── static-web-app.bicep
│       └── monitoring.bicep
├── backend/
│   ├── Dockerfile                      # NEW (Phase 7)
│   ├── .dockerignore                   # NEW (Phase 7)
│   ├── pyproject.toml                  # Updated (no boto3, no mangum)
│   ├── app/
│   │   ├── main.py                     # No Mangum handler
│   │   ├── settings.py                 # Azure settings only
│   │   ├── dependencies.py             # Azure clients (Cosmos, Blob, KV)
│   │   ├── repositories/
│   │   │   └── conversation_repository.py  # Cosmos DB queries
│   │   ├── services/
│   │   │   ├── llm.py                  # Unchanged (cloud-agnostic)
│   │   │   ├── storage.py              # Azure Blob Storage
│   │   │   ├── vector_store.py         # Cosmos DB Vector Search
│   │   │   ├── rag.py                  # Document Intelligence
│   │   │   └── prompt.py               # Unchanged
│   │   └── utils/
│   └── tests/
├── functions/
│   └── ingestion_worker/               # NEW (Phase 5)
│       ├── function_app.py
│       ├── host.json
│       └── requirements.txt
├── frontend/
│   ├── staticwebapp.config.json        # NEW (Phase 8)
│   ├── src/
│   │   ├── services/
│   │   │   ├── auth.ts                 # MSAL.js (Entra)
│   │   │   └── api.ts                  # Updated token retrieval
│   │   └── components/
│   │       └── AuthGate.tsx            # MSAL login flow
│   └── ...
├── docs/
│   ├── migration/                      # Phase plans (this directory)
│   ├── archive/
│   │   ├── template.yaml               # Archived AWS SAM template
│   │   └── get_urls.sh                 # Archived AWS script
│   └── AZURE_MIGRATION_GUIDE.md        # Original reference guide
├── .env.example                        # Azure-flavored
├── deploy-backend.sh                   # Azure ACR + Container Apps
├── deploy-frontend.sh                  # Azure Static Web Apps
└── README.md                           # Updated for Azure
```

---

## Production Cutover Checklist

### Pre-Cutover

- [ ] All 9 phases completed and verified
- [ ] End-to-end test: sign up → sign in → create conversation → send message → receive streaming response
- [ ] End-to-end test: upload PDF → ingestion pipeline → RAG query returns relevant chunks
- [ ] End-to-end test: image upload → presigned SAS URL → image displayed in chat
- [ ] No `boto3`, `mangum`, `cognito`, `ssm`, `dynamodb`, `textract`, `s3vectors` references remain
- [ ] `pnpm build` succeeds for frontend
- [ ] `docker build` succeeds for backend
- [ ] All `pytest` tests pass

### DNS & Domain

- [ ] Configure custom domain on Azure Static Web Apps (frontend)
- [ ] Configure custom domain on Azure Container Apps (backend API)
- [ ] Update `VITE_API_BASE_URL` to production domain
- [ ] Update Entra redirect URIs with production domain

### Security

- [ ] Managed Identity RBAC configured for Container App → Key Vault, Cosmos DB, Blob Storage
- [ ] Managed Identity RBAC configured for Function App → Key Vault, Cosmos DB, Blob Storage
- [ ] Container Apps ingress set to `allowInsecure: false`
- [ ] Blob Storage `allowBlobPublicAccess: false`
- [ ] Key Vault soft-delete enabled

### Cost Validation

- [ ] Container App `minReplicas: 0` confirmed
- [ ] Cosmos DB throughput ≤ 400 RU/s (within free tier)
- [ ] Cosmos DB `enableFreeTier: true` confirmed
- [ ] Blob Storage replication set to LRS
- [ ] Application Insights ingestion < 5 GB/month
- [ ] `LOG_LEVEL=INFO` in production

### Decommission AWS (Optional)

After confirming Azure is stable:

- [ ] Delete AWS SAM stack: `sam delete --stack-name chatbot-prod`
- [ ] Delete Cognito user pool (after migrating users if needed)
- [ ] Delete S3 buckets (uploads + frontend + vectors)
- [ ] Delete CloudWatch log groups
- [ ] Revoke AWS IAM credentials used for deployment

> [!CAUTION]
> Do **not** decommission AWS resources until the Azure stack has been running in production for at least 1–2 weeks without issues. Keep `docs/archive/template.yaml` as a rollback reference.

---

## Update README

Update `README.md` to reflect the Azure architecture:

- Replace all AWS service references with Azure equivalents
- Update setup instructions (`az login`, `azd up`)
- Update local development instructions (Azurite, Cosmos Emulator, SWA CLI)
- Update deployment instructions (ACR build, ACA deploy, SWA deploy)
- Update architecture diagrams

---

## 🎉 Migration Complete

Once this phase is done, the entire chatbot stack runs on Azure:

| Layer         | Azure Service                                         | Cost         |
| :------------ | :---------------------------------------------------- | :----------- |
| Frontend      | Azure Static Web Apps (Free)                          | **$0**       |
| Auth          | Microsoft Entra External ID (50k MAU free)            | **$0**       |
| Backend API   | Azure Container Apps (scale-to-zero)                  | **$0**       |
| Database      | Azure Cosmos DB (1,000 RU/s free tier)                | **$0**       |
| Vector Search | Cosmos DB integrated vector indexes                   | **$0**       |
| File Storage  | Azure Blob Storage (5 GB LRS free)                    | **$0**       |
| Message Queue | Azure Storage Queues (bundled with Storage Account)   | **$0**       |
| Worker        | Azure Functions (1M exec/month free)                  | **$0**       |
| Document OCR  | Azure AI Document Intelligence (500 pages/month free) | **$0**       |
| Secrets       | Azure Key Vault ($0.03/10k ops)                       | **~$0**      |
| Logging       | Azure Monitor (5 GB/month free)                       | **$0**       |
| **Total**     |                                                       | **$0/month** |
