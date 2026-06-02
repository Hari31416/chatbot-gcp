# Phase 1 — Project Scaffold & IaC Bootstrap

> Replace AWS SAM `template.yaml` with Azure Bicep modules and set up the Azure Developer CLI (`azd`) project structure.

---

## Goal

Set up the Azure project scaffold so that all subsequent phases have a target to deploy into. This phase creates the IaC foundation but does **not** provision any resources yet — each phase will add its own Bicep module.

---

## Current State (AWS)

| Artifact                             | Role                                                                                    |
| :----------------------------------- | :-------------------------------------------------------------------------------------- |
| `template.yaml` (SAM/CFN, 476 lines) | Declares all AWS resources: Lambda, API Gateway, DynamoDB, S3, Cognito, SQS, S3 Vectors |
| `deploy-backend.sh`                  | Runs `sam build` + `sam deploy`                                                         |
| `deploy-frontend.sh`                 | Runs `aws s3 sync` to push frontend dist                                                |
| `.env.example`                       | 38 env vars, all AWS-flavored                                                           |

---

## Target State (Azure)

```
chatbot-azure/
├── azure.yaml                      # azd project manifest
├── infra/
│   ├── main.bicep                  # Orchestrator — imports all modules
│   ├── main.parameters.json        # Environment-specific overrides
│   ├── modules/
│   │   ├── resource-group.bicep    # Resource group (Phase 1)
│   │   ├── storage.bicep           # Blob Storage + Storage Queue (Phases 2 & 5)
│   │   ├── cosmos.bicep            # Cosmos DB (Phase 3)
│   │   ├── auth.bicep              # Entra External ID (Phase 4 — manual steps)
│   │   ├── functions.bicep         # Azure Functions (Phase 5)
│   │   ├── keyvault.bicep          # Key Vault (Phase 6)
│   │   ├── container-apps.bicep    # Container Apps (Phase 7)
│   │   ├── static-web-app.bicep    # Static Web Apps (Phase 8)
│   │   └── monitoring.bicep        # Log Analytics + App Insights (Phase 9)
│   └── abbreviations.json         # Azure resource naming conventions
├── .env.azure.example              # Azure-flavored env vars
└── template.yaml                   # KEEP — do not delete until Phase 10
```

---

## Tasks

### 1.1 Install Azure Tooling

```bash
# Azure Developer CLI
brew install azd

# Azure CLI (needed for auth + resource management)
brew install azure-cli

# Azure Functions Core Tools (needed for Phase 5 local dev)
brew install azure-functions-core-tools@4

# Azure Static Web Apps CLI (needed for Phase 8 local dev)
npm install -g @azure/static-web-apps-cli

# Bicep (included with Azure CLI, verify version)
az bicep version
az bicep upgrade
```

### 1.2 Authenticate

```bash
az login
azd auth login
```

### 1.3 Initialize the `azd` Project

Create `azure.yaml` in the project root:

```yaml
# azure.yaml
name: chatbot-azure
metadata:
  template: chatbot-azure

services:
  backend:
    project: ./backend
    host: containerapp
    language: python

  worker:
    project: ./backend
    host: function
    language: python

  frontend:
    project: ./frontend
    host: staticwebapp
    language: js
```

### 1.4 Create the Bicep Orchestrator

Create `infra/main.bicep`:

```bicep
targetScope = 'subscription'

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Primary Azure region for all resources')
param location string

@description('Unique resource token for naming')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

// ──────────────────────────────────────────────
// Resource Group
// ──────────────────────────────────────────────
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-chatbot-${environmentName}'
  location: location
  tags: {
    'azd-env-name': environmentName
    project: 'chatbot-azure'
  }
}

// Module imports will be added by subsequent phases:
// Phase 2: module storage   './modules/storage.bicep'
// Phase 3: module cosmos    './modules/cosmos.bicep'
// Phase 5: (queue added to storage.bicep — no separate module)
// Phase 5: module functions './modules/functions.bicep'
// Phase 6: module keyvault  './modules/keyvault.bicep'
// Phase 7: module aca       './modules/container-apps.bicep'
// Phase 8: module swa       './modules/static-web-app.bicep'
// Phase 9: module monitor   './modules/monitoring.bicep'
```

Create `infra/main.parameters.json`:

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "environmentName": { "value": "${AZURE_ENV_NAME}" },
    "location": { "value": "${AZURE_LOCATION}" }
  }
}
```

### 1.5 Create Azure Environment Variables Template

Create `.env.azure.example`:

```bash
# ──────────────────────────────────────────────
# Azure Environment Configuration
# ──────────────────────────────────────────────

# Azure region (e.g. centralindia, eastus, westeurope)
AZURE_LOCATION=centralindia
AZURE_ENV_NAME=dev

# ── Blob Storage (Phase 2) ──
AZURE_STORAGE_ACCOUNT_NAME=
AZURE_STORAGE_CONTAINER_NAME=uploads
AZURE_STORAGE_CONNECTION_STRING=

# ── Cosmos DB (Phase 3) ──
COSMOS_ENDPOINT=
COSMOS_DATABASE_NAME=chatbot
COSMOS_CONTAINER_NAME=conversations
COSMOS_KEY=

# ── Entra Auth (Phase 4) ──
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
ENTRA_AUTHORITY=

# ── Storage Queue (Phase 5 — uses same Storage Account) ──
AZURE_INGESTION_QUEUE_NAME=ingestion-queue

# ── Document Intelligence (Phase 5) ──
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=

# ── Key Vault (Phase 6) ──
AZURE_KEYVAULT_NAME=

# ── Container Apps (Phase 7) ──
AZURE_CONTAINER_REGISTRY=
AZURE_CONTAINER_APP_NAME=chatbot-backend

# ── LLM (unchanged — cloud-agnostic via LiteLLM) ──
LITELLM_MODEL=gpt-4o-mini
LITELLM_API_KEY=
LITELLM_BASE_URL=
LITELLM_VISION_MODEL=gemini/gemini-3.1-flash-lite
LITELLM_VISION_API_KEY=
LITELLM_EMBEDDING_MODEL=gemini/gemini-embedding-2
LITELLM_EMBEDDING_API_KEY=

# ── RAG Config (unchanged) ──
EMBEDDING_DIMENSION=768
RAG_TOP_K=3
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=80

# ── App Config (unchanged) ──
CONTEXT_TTL_SECONDS=3600
MAX_IMAGE_BYTES=5242880
ALLOWED_IMAGE_MIME_TYPES=image/png,image/jpeg,image/webp
MAX_HISTORY_MESSAGES=10
LOG_LEVEL=INFO
```

---

## Verification

- [ ] `azd version` outputs ≥ 1.x
- [ ] `az bicep version` outputs ≥ 0.25.x
- [ ] `azure.yaml` is valid: `azd config list` runs without error
- [ ] `infra/main.bicep` compiles: `az bicep build --file infra/main.bicep`
- [ ] No existing code is modified — this phase is purely additive

---

## Decisions & Notes

> [!NOTE]
> The original `template.yaml` will be **preserved** throughout the entire migration and only archived in Phase 10. This allows rollback to AWS at any point.

> [!IMPORTANT]
> Bicep modules are **not provisioned** in this phase. Each subsequent phase will add its module and provision incrementally using `azd provision`.

---

## Next Phase

→ [Phase 2 — Blob Storage](./PHASE_2_BLOB_STORAGE.md)
