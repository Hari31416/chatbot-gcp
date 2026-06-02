# Phase 7 — Container Apps Migration

> Replace AWS Lambda + Lambda Web Adapter (LWA) + API Gateway with Azure Container Apps for hosting the FastAPI backend.

---

## Goal

Deploy the FastAPI backend as a standard container on Azure Container Apps (ACA). This simplifies the stack significantly — no Lambda adapter, no Mangum wrapper, no API Gateway proxy. ACA runs containers natively with built-in ingress, HTTPS, and scale-to-zero.

---

## Current State (AWS)

### Lambda + LWA Architecture

| Component                             | Purpose                                            |
| :------------------------------------ | :------------------------------------------------- |
| `run.sh`                              | Lambda entry point, starts uvicorn on port 8080    |
| `mangum`                              | Lambda ↔ ASGI adapter in `app/main.py`             |
| LWA layer (`LambdaAdapterLayerArm64`) | Proxies Lambda invocations to HTTP on port 8080    |
| API Gateway (`ChatbotHttpApi`)        | External HTTP endpoint with Cognito JWT authorizer |
| Lambda Function URL                   | Response streaming endpoint (SSE)                  |

### Environment Variables (Lambda-specific)

```yaml
AWS_LAMBDA_EXEC_WRAPPER: /opt/bootstrap
AWS_LWA_INVOKE_MODE: response_stream
PORT: "8080"
```

---

## Target State (Azure)

### Azure Container Apps Architecture

| Component                          | Purpose                                                |
| :--------------------------------- | :----------------------------------------------------- |
| **Container App**                  | Runs the FastAPI Docker container directly             |
| **ACA Ingress**                    | Built-in HTTPS reverse proxy with SSL termination      |
| **ACA Scale Rules**                | HTTP-based autoscaling, `minReplicas: 0` for free tier |
| **Azure Container Registry (ACR)** | Private Docker image registry                          |

No adapter layers, no wrappers — FastAPI runs as-is.

---

## Code Changes

### 7.1 Remove Mangum from `app/main.py`

```diff
 import logging
-from typing import Any, cast
+from typing import cast

 from fastapi import FastAPI
 from fastapi.middleware.cors import CORSMiddleware
-from mangum import Mangum

 from .api.routes import router
 from .logging_config import configure_logging

 configure_logging()

 logger = logging.getLogger(__name__)

 app = FastAPI(title="Chatbot API")

 app.add_middleware(
-    cast(Any, CORSMiddleware),
+    CORSMiddleware,
     allow_origins=["*"],
     allow_credentials=True,
     allow_methods=["*"],
     allow_headers=["*"],
 )

 app.include_router(router)


 @app.get("/health")
 def health() -> dict[str, str]:
     logger.debug("Health check requested")
     return {"status": "ok"}


 logger.info("Chatbot API initialised")
-
-handler = Mangum(app)
```

### 7.2 Remove `mangum` from `pyproject.toml`

```diff
 dependencies = [
   "fastapi>=0.115.0",
   "uvicorn>=0.30.0",
   "pydantic-settings>=2.4.0",
   "python-multipart>=0.0.9",
-  "boto3>=1.43.8",
   "azure-storage-blob>=12.20.0",
   "azure-cosmos>=4.7.0",
   "azure-ai-documentintelligence>=1.0.0",
   "azure-identity>=1.17.0",
   "azure-keyvault-secrets>=4.8.0",
   "litellm>=1.41.0",
-  "mangum>=0.17.0",
   "PyJWT>=2.8.0",
   "cryptography>=42.0.0",
 ]
```

> [!IMPORTANT]
> By this phase, `boto3` should be fully removed. If any boto3 usage remains, resolve it before removing the dependency.

### 7.3 Create Dockerfile

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ ./app/

# Expose port
EXPOSE 8080

# Run with uvicorn
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 7.4 Create `.dockerignore`

```txt
# backend/.dockerignore
.venv/
__pycache__/
.pytest_cache/
tests/
*.pyc
.env
.env.*
```

### 7.5 Update `run.sh`

Simplify to a standard uvicorn startup (no Lambda wrapper):

```bash
#!/bin/bash
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
```

### 7.6 Remove Lambda-specific Environment Variables

Remove from all configs:

- `AWS_LAMBDA_EXEC_WRAPPER`
- `AWS_LWA_INVOKE_MODE`
- `COGNITO_USER_POOL_ID` → already replaced by `AZURE_TENANT_ID`
- `COGNITO_CLIENT_ID` → already replaced by `AZURE_CLIENT_ID`

### 7.7 Remove `app/settings.py` AWS Fields

```diff
-    aws_region: str = Field(default="us-east-1", validation_alias="AWS_REGION")
-    dynamodb_table_name: str = ...
-    dynamodb_endpoint_url: str | None = ...
-    s3_bucket_name: str = ...
-    s3_endpoint_url: str | None = ...
-    s3_force_path_style: bool = ...
-    cognito_user_pool_id: str | None = ...
-    cognito_client_id: str | None = ...
-    s3_vector_bucket_name: str = ...
-    s3_vector_index_name: str = ...
-    s3_vector_endpoint_url: str | None = ...
```

---

## Deployment

### Build and Push to ACR

```bash
# Create Azure Container Registry (one-time)
az acr create --resource-group rg-chatbot-dev --name crchatbotdev --sku Basic

# Build and push
az acr build --registry crchatbotdev --image chatbot-backend:latest ./backend
```

### Deploy to Container Apps

```bash
# Create Container Apps Environment (one-time)
az containerapp env create \
  --name cae-chatbot-dev \
  --resource-group rg-chatbot-dev \
  --location centralindia

# Deploy
az containerapp create \
  --name chatbot-backend \
  --resource-group rg-chatbot-dev \
  --environment cae-chatbot-dev \
  --image crchatbotdev.azurecr.io/chatbot-backend:latest \
  --target-port 8080 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 5 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --env-vars "COSMOS_ENDPOINT=..." "AZURE_KEYVAULT_NAME=..."
```

---

## Bicep Module: `infra/modules/container-apps.bicep`

```bicep
param location string
param environmentName string
param containerRegistryName string
param containerImageTag string = 'latest'

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'cae-chatbot-${environmentName}'
  location: location
  tags: { 'azd-env-name': environmentName }
  properties: {}
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'chatbot-backend'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        allowInsecure: false
        transport: 'auto'  // Supports SSE streaming
      }
      registries: [
        {
          server: '${containerRegistryName}.azurecr.io'
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'fastapi-backend'
          image: '${containerRegistryName}.azurecr.io/chatbot-backend:${containerImageTag}'
          resources: { cpu: json('0.5'), memory: '1.0Gi' }
        }
      ]
      scale: {
        minReplicas: 0   // Scale to zero for free tier!
        maxReplicas: 5
        rules: [
          {
            name: 'http-rule'
            http: { metadata: { concurrentRequests: '10' } }
          }
        ]
      }
    }
  }
}

output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
output containerAppPrincipalId string = containerApp.identity.principalId
```

---

## Replace `deploy-backend.sh`

The old script uses `sam build` + `sam deploy`. Replace with:

```bash
#!/bin/bash
set -euo pipefail

REGISTRY="${AZURE_CONTAINER_REGISTRY:-crchatbotdev}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "Building and pushing to ACR..."
az acr build --registry "$REGISTRY" --image "chatbot-backend:$IMAGE_TAG" ./backend

echo "Updating Container App..."
az containerapp update \
  --name chatbot-backend \
  --resource-group "rg-chatbot-${AZURE_ENV_NAME:-dev}" \
  --image "$REGISTRY.azurecr.io/chatbot-backend:$IMAGE_TAG"

echo "Deployment complete!"
```

---

## Verification

- [ ] `docker build -t chatbot-backend ./backend` succeeds
- [ ] Container starts locally: `docker run -p 8080:8080 chatbot-backend`
- [ ] `/health` endpoint responds with `{"status": "ok"}`
- [ ] SSE streaming (`/chat/stream`) works through ACA ingress
- [ ] `minReplicas: 0` is configured (check with `az containerapp show`)
- [ ] System-assigned Managed Identity is enabled
- [ ] Container can access Key Vault and Cosmos DB via Managed Identity
- [ ] `mangum` is fully removed from codebase
- [ ] `boto3` is fully removed from codebase

---

## Next Phase

→ [Phase 8 — Static Web Apps](./PHASE_8_STATIC_WEB_APPS.md)
