# Phase 10 — Cutover & Azure Cleanup

> Validate the GCP deployment, switch the PoC frontend, and archive Azure-specific implementation files only after acceptance checks pass.

---

## Goal

Complete the Azure → GCP migration with an empty GCP data plane. Preserve Azure history in Git, but remove active Azure runtime dependencies after the GCP deployment is verified.

---

## Pre-Cutover Checklist

### Infrastructure

- [ ] Terraform state is stored safely and is not committed.
- [ ] Firestore Native Mode exists in `asia-south1`.
- [ ] GCS bucket is private and temporary prefixes have lifecycle cleanup.
- [ ] API and worker Cloud Run services use `min_instance_count = 0`.
- [ ] API maximum instances are capped at `3`; worker maximum instances are capped at `2`.
- [ ] Worker is private and Eventarc can invoke it.
- [ ] Secret Manager access is limited to API and worker service accounts.
- [ ] Billing budget alerts are configured.

### Application

- [ ] Firebase email/password registration, login, logout, and token refresh work.
- [ ] `/health`, `/chat`, `/chat/stream`, image upload, conversation history, rename, and delete work.
- [ ] `.txt`, `.md`, PDF, and image RAG ingestion paths work.
- [ ] Duplicate Pub/Sub delivery is idempotent.
- [ ] Vector search returns user-scoped chunks.
- [ ] Frontend build and backend tests pass.

### Cost

- [ ] No minimum Cloud Run instances.
- [ ] No Cloud SQL, GKE, load balancer, NAT gateway, or dedicated VM was added.
- [ ] Document AI OCR is the default; Layout Parser remains opt-in.
- [ ] GCS Mumbai-region storage charges are understood and accepted.

---

## Cutover Steps

### 10.1 Deploy Versioned Containers

```bash
export GCP_REGION=asia-south1
export API_IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/chatbot/api:$(git rev-parse --short HEAD)"
export WORKER_IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/chatbot/worker:$(git rev-parse --short HEAD)"

gcloud builds submit backend --tag "$API_IMAGE"
gcloud builds submit backend \
  --config backend/cloudbuild.worker.yaml \
  --substitutions="_IMAGE=$WORKER_IMAGE"
terraform -chdir=gcp-infra apply \
  -var="api_image=$API_IMAGE" \
  -var="worker_image=$WORKER_IMAGE"
```

### 10.2 Deploy Frontend

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
firebase deploy --only hosting --project "$GCP_PROJECT_ID"
```

### 10.3 Smoke Test

```bash
curl -fsS "$BACKEND_URL/health"
gcloud run services logs read chatbot-api --region asia-south1 --limit 30
gcloud run services logs read chatbot-worker --region asia-south1 --limit 30
```

---

## Cleanup Tasks

Only remove Azure runtime code after cutover acceptance.

### 10.4 Remove Azure SDK Dependencies

Remove from `backend/pyproject.toml` and regenerate `backend/uv.lock`:

```txt
azure-ai-documentintelligence
azure-cosmos
azure-functions
azure-identity
azure-keyvault-secrets
azure-storage-blob
azure-storage-queue
```

### 10.5 Remove Azure Runtime Files

Archive or remove:

```txt
azure.yaml
infra/
backend/function_app.py
frontend/staticwebapp.config.json
```

Keep the Azure migration documentation under `docs/migration/` as historical context.

### 10.6 Remove Azure and Clerk References

```bash
rg -n "AZURE_|azure\\.|azure-|Cosmos|cosmos|Clerk|clerk|@clerk" \
  backend frontend deploy-*.sh Makefile get-outputs.sh
```

Resolve every active runtime reference. Historical documentation may still mention Azure and AWS.

### 10.7 Update Active Documentation

Update:

- `README.md`
- `docs/COMPREHENSIVE_ARCHITECTURE.md`
- `.env.example`
- `frontend/.env.example`
- `Makefile`
- `deploy-backend.sh`
- `deploy-functions.sh` or rename it to `deploy-worker.sh`
- `deploy-frontend.sh`
- `get-outputs.sh`

---

## Final Project Shape

```txt
chatbot-gcp/
├── gcp-infra/
│   ├── main.tf
│   └── modules/
├── backend/
│   ├── Dockerfile
│   ├── Dockerfile.worker
│   └── app/
├── frontend/
│   ├── firebase.json
│   └── src/
├── docs/
│   ├── gcp-migration/
│   └── migration/          # historical Azure migration plans
├── Makefile
├── deploy-backend.sh
├── deploy-worker.sh
└── deploy-frontend.sh
```

---

## Rollback

Before Azure resources are decommissioned, rollback is straightforward:

1. Redeploy the last known Azure frontend build.
2. Restore its Azure Container Apps API URL.
3. Keep GCP resources deployed for debugging or destroy them with Terraform after diagnosis.

This PoC starts with empty GCP data, so there is no cross-cloud data reconciliation step.

---

## Migration Complete

The application is now GCP-native:

- Cloud Run API with SSE
- Firebase Authentication
- Firestore Native Mode with vector search
- GCS object storage
- Pub/Sub + Eventarc + private Cloud Run ingestion worker
- Document AI parsing
- Secret Manager
- Firebase Hosting
- Cloud Logging, Monitoring, and budget alerts
