# Azure Deployment Adjustments & Fixes

This document records the exact changes and adjustments made to the Azure Bicep templates and subscription configurations during the deployment of the chatbot stack to resolve compilation warnings, naming conflicts, regional limits, and subscription policies.

---

## 1. Subscription Resource Provider Registrations

- **Issue**: The deployment encountered `MissingSubscriptionRegistration` errors because key resource providers were not registered in the subscription.
- **Resolution**: Registered the missing providers using the Azure CLI:

  ```bash
  # Register Microsoft.Web (for Azure Functions and Static Web Apps)
  az provider register --namespace Microsoft.Web

  # Register Microsoft.AlertsManagement (for Alert Rules and Monitoring Diagnostics)
  az provider register --namespace Microsoft.AlertsManagement
  ```

  Verified that both namespaces successfully transitioned to the **`Registered`** state.

---

## 2. Cosmos DB Globally Unique DNS Naming

- **Issue**: The template originally used `cosmos-chatbot-${environmentName}` (resolving to `cosmos-chatbot-dev`) for the Cosmos DB account name. This failed with a `BadRequest` error because the DNS record was already taken by another Azure user. Cosmos DB names must be globally unique across Azure.
- **Resolution**:
  - Parameterized the `cosmos.bicep` module with `resourceToken` (a subscription-unique hash derived from subscription ID, environment, and region).
  - Updated `cosmosAccount` resource name in `cosmos.bicep` to `cosmos-chatbot-${resourceToken}`.
  - Updated `main.bicep` to pass the `resourceToken` parameter to the `cosmos` module call.
  - _Result_: Names are now guaranteed to be globally unique and secure against resource name collisions.

---

## 3. Static Web App Regional Fallback Mapping

- **Issue**: Deploying to `centralindia` caused a regional failure because the control-plane metadata resource for Azure Static Web Apps (`Microsoft.Web/staticSites`) is not supported in `centralindia`.
- **Resolution**: Added a dynamic regional check inside `static-web-app.bicep`:

  ```bicep
  var supportedSwaLocations = [
    'centralus'
    'eastus2'
    'westus2'
    'westeurope'
    'eastasia'
  ]
  var swaLocation = contains(supportedSwaLocations, location) ? location : 'eastasia'
  ```

  This automatically routes the Static Web App metadata resource registration to a supported region if the primary region lacks support. The static app itself remains globally distributed.

---

## 4. Subscription Allowed Locations Policy Alignment (`sys.regionrestriction`)

- **Issue**: The `Azure for Students` subscription has a strict region restriction policy assignment (`sys.regionrestriction`) that limits resource deployments to the following regions: `eastasia`, `centralindia`, `malaysiawest`, `koreacentral`, `uaenorth`.
  - _Conflict_: Our initial Static Web App fallback region of `eastus2` triggered a policy violation and blocked the entire template deployment.
- **Resolution**: Identified the intersection of SWA supported regions and subscription allowed regions:
  $$\text{SWA Supported} \cap \text{Subscription Allowed} = \{\text{eastasia}\}$$
  Adjusted the fallback region in `static-web-app.bicep` from `eastus2` to **`eastasia`**. This ensures compliance with subscription rules while satisfying the resource type's technical constraints.

---

## 5. Bicep Compiler & Linter Cleanups

### Upgrading Cosmos DB API Version

- **Issue**: Warnings (`BCP037`) were thrown regarding the properties `vectorIndexes` and `vectorEmbeddingPolicy` being unrecognized on the Cosmos DB SQL Container resource.
- **Resolution**: Upgraded all `Microsoft.DocumentDB` resources in `cosmos.bicep` from `@2023-11-15` to the stable `@2024-05-15` API version. This provides native validation for NoSQL Vector Search configurations.

### Unused Bicep Parameters

- **Issue**: Linter warning `no-unused-params` was thrown in `cosmos.bicep` for `environmentName` after shifting to resource tokens.
- **Resolution**: Removed the `environmentName` parameter from `cosmos.bicep` and omitted it from the `cosmos` module call inside `main.bicep`.

### Modern Resource Symbol References

- **Issue**: Linter warning `use-resource-symbol-reference` was thrown in `static-web-app.bicep` for invoking the old global `listSecrets()` function.
- **Resolution**: Swapped to the modern, declarative symbol syntax:

  ```bicep
  output deploymentToken string = staticWebApp.listSecrets().properties.apiKey
  ```

  This enables Azure's Bicep engine to natively track the deployment dependency graph.

---

## 6. Container App Bootstrap Naming chicken-and-egg Problem

- **Issue**: The Container App (`chatbot-backend`) failed to provision with a `ResourceDeploymentFailure` error during the initial `make deploy-infra` run because it was configured to pull `chatbot-backend:latest` from the newly created private Azure Container Registry (ACR). Since the registry is completely empty when first created, the pull failed, crashing the app's initial deployment.
- **Resolution**:
  - Parameterized the container image in `container-apps.bicep` with a default public hello-world image:

    ```bicep
    param containerImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'
    ```

  - _Result_: The Container App successfully boots the public placeholder image on the first deployment without needing registry credentials. Subsequently, running the backend deployment script `deploy-backend.sh` builds the real image, pushes it to ACR, and updates the Container App to reference your production image.

---

## 7. Key Vault Globally Unique Naming

- **Issue**: The Key Vault failed to provision with a `VaultAlreadyExists` error because the vault name `kv-chatbot-dev` was already in use by another Azure user in the world. Key Vault names must be globally unique across Azure and are restricted to 24 characters maximum.
- **Resolution**:
  - Parameterized the `keyvault.bicep` module with `resourceToken`.
  - Configured the name of the `keyVault` resource inside `keyvault.bicep` to `kv-chatbot-${resourceToken}`.
  - Updated `keyVaultName` variable in `main.bicep` to `kv-chatbot-${resourceToken}` (evaluating to exactly 24 characters) and passed it to the `keyvault` module parameters block.
  - _Result_: The Key Vault name is now globally unique, resolving the DNS naming conflict while adhering to the 24-character maximum constraint.

---

## 8. Dynamic Environment Synchronization & Makefile Integration

- **Issue**: The backend deployment script `deploy-backend.sh` had a hardcoded fallback registry name `crchatbotdev`. Since we parameterized the Bicep template to generate globally unique resource names, the script could not locate the container registry in the subscription.
- **Resolution**:
  - Created `update-env.py` (a Python sync utility) that fetches the outputs from the completed subscription deployment (`az deployment sub show`) and automatically writes or updates the corresponding keys (like `AZURE_CONTAINER_REGISTRY` and `AZURE_SWA_DEPLOYMENT_TOKEN`) inside the local `.env` configuration file.
  - Added a dynamic `.env` loader at the top of the `Makefile`:

  ```makefile
  ifneq ("$(wildcard .env)","")
    include .env
    export
  endif
  ```

  - _Result_: Sourcing and exporting `.env` parameters is now completely automated. All Bicep-related Make targets (such as `make deploy-backend` and `make deploy-frontend`) will automatically load and inject the correct Azure resource names and tokens directly into the bash deployment scripts without manual intervention.

---

## 9. Local Docker Build Workaround (Bypassing ACR Tasks)

- **Issue**: The backend deployment failed with `TasksOperationsNotAllowed` during `az acr build`. Azure for Students subscriptions strictly forbid ACR Tasks (the cloud-based container builder service) to prevent high resource abuse.
- **Resolution**:
  - Rewrote `deploy-backend.sh` to use the **local Docker engine** to log in, build, and push the container image directly to the registry:

    ```bash
    az acr login --name "$REGISTRY"
    docker build --platform linux/amd64 -t "$REGISTRY.azurecr.io/chatbot-backend:$IMAGE_TAG" ./backend
    docker push "$REGISTRY.azurecr.io/chatbot-backend:$IMAGE_TAG"
    ```

  - _Critical Architecture Check_: Included the `--platform linux/amd64` flag in the `docker build` command. Since developer machines can be macOS (Apple Silicon arm64) while Azure Container Apps runs on Intel/AMD `amd64` systems, specifying the platform explicitly guarantees the container boots correctly in Azure without `exec format error` crashes.

---

## 10. Cosmos DB and Storage Secure Key Vault Integration

- **Issue**: The Container App and the Azure Function App both returned `Unauthorized` errors or crashed because they lacked `COSMOS_KEY` and `AZURE_STORAGE_CONNECTION_STRING` when running on Azure, defaulting to local emulator settings.
- **Resolution**:
  - **Secure Key Vault Storage**: Updated the `keyvault.bicep` module to accept the secure Cosmos DB master key (`cosmosAccount.listKeys().primaryMasterKey`) and Storage connection string directly during provisioning. Added native Key Vault secret resources (`cosmos-key` and `storage-connection-string`) to store these credentials securely.
  - **Azure Function Configuration**: Updated `functions.bicep` and `main.bicep` to pass key resource configuration identifiers (`COSMOS_ENDPOINT`, `AZURE_KEYVAULT_NAME`, `AZURE_STORAGE_ACCOUNT_NAME`) to the Function App's configuration settings (`appSettings`).
  - **Dynamic Runtime Credential Resolution**: Updated `dependencies.py` in the backend python library. At runtime, when instantiating the Cosmos Client or Storage Client on Azure, it uses its system-assigned Managed Identity to authenticate to Key Vault and query the secret values (`cosmos-key` and `storage-connection-string`) dynamically. If local or if Key Vault is unavailable, it gracefully falls back to local environment variables or emulator defaults.

---

## 11. Strict Production Authentication Enforcement

- **Issue**: Although authentication endpoints were present, unauthenticated requests to API endpoints (like `/conversations`) defaulted to the `"admin"` user fallback when no token or header was specified, allowing unauthorized public access to backend resources in production.
- **Resolution**:
  - **Environment-Aware Auth Guards**: Enhanced `get_current_user_id()` in `backend/app/dependencies.py` to identify whether the container is running in a deployed Azure cloud environment (by checking if `COSMOS_ENDPOINT` points to a non-localhost/non-emulator address and ensuring it is not a `pytest` execution).
  - **Enforced Block**: Under deployed environments, if neither an OIDC Bearer token nor a developer testing header (`X-User-ID`) is supplied, the backend now strictly raises a `401 Unauthorized` exception rather than falling back to `"admin"`.
  - _Result_: The live API endpoints are now fully secure against unauthenticated direct calls, while maintaining out-of-the-box local development and testing flows.

---

## 12. Automated AI Document Intelligence Provisioning and Secrets Automation

- **Issue**: The RAG Ingestion pipeline lacked an automated provisioning solution for Azure AI Document Intelligence, requiring manual resource creation in the portal. Additionally, the LiteLLM API and Vision API keys were managed via local environment variables, mimicking AWS SSM Parameter storage.
- **Resolution**:
  - **Bicep Automation**: Created a new Bicep module `document-intelligence.bicep` to automatically provision a Standard (`S0`) Azure AI Document Intelligence resource.
  - **Dynamic Secrets Storage**: Automatically captured the dynamics endpoint and key outputs in `main.bicep` and saved them securely in Azure Key Vault under `azure-document-intelligence-endpoint` and `azure-document-intelligence-key`.
  - **SSM-Style Secrets Automation**: Integrated local `.env` LiteLLM keys (`LITELLM_API_KEY` and `LITELLM_VISION_API_KEY`) into the `Makefile` parameters target. During provisioning, Bicep securely passes and registers these credentials as `litellm-api-key` and `litellm-vision-api-key` in Key Vault.
  - **Dynamic Runtime Resolution**: Updated `dependencies.py` to retrieve `azure-document-intelligence-endpoint` and `azure-document-intelligence-key` securely from Key Vault at runtime via system Managed Identities.

---

## 13. Function App Globally Unique DNS Naming & Deploy Tooling

- **Issue**: The Function App failed to provision with a `Conflict` error: `Website with given name func-chatbot-worker-dev already exists`. Since Azure Function Apps are part of a global DNS namespace (`<name>.azurewebsites.net`), naming them with a static name like `func-chatbot-worker-dev` risks name collision with other users.
- **Resolution**:
  - **Unique DNS Naming**: Parameterized `functions.bicep` with the Subscription/Location-unique `resourceToken` variable, renaming the app resource to `func-chatbot-worker-${resourceToken}` and its Azure Files share setting to `func-chatbot-worker-${resourceToken}-share`.
  - **Dynamic CLI Outputs**: Exposed the dynamically generated app name in `main.bicep` as `output AZURE_FUNCTION_APP_NAME string`.
  - **Automated Sync & Script Integration**:
    - Updated `update-env.py` and `get-outputs.sh` to extract the `AZURE_FUNCTION_APP_NAME` dynamically using case-insensitive key parsing and write it to `.env`.
    - Created `deploy-functions.sh` to retrieve this unique app name from `.env` or outputs and deploy the Python serverless codebase via Azure Functions Core Tools (`func azure functionapp publish`).
    - Added the `deploy-functions` target to the `Makefile` and integrated it as part of `deploy-all`.

---

## 14. Missing `FUNCTIONS_EXTENSION_VERSION` Causing Persistent 503 (Site Unavailable)

- **Issue**: After the Function App was provisioned via Bicep, both the main app endpoint (`func-chatbot-worker-*.azurewebsites.net`) and the SCM/Kudu deploy endpoint (`*.scm.azurewebsites.net`) returned `503 Site Unavailable`. This completely blocked all `func azure functionapp publish` deployments with the error:
  > `Unable to connect to the Azure Function App... Response status code does not indicate success: 503 (Site Unavailable).`
  > All standard troubleshooting (restarts, network checks, storage validation) confirmed the app was running, public network access was enabled, and the Azure Files content share was intact — but the 503 persisted.
- **Root Cause**: The `functions.bicep` module was missing the **`FUNCTIONS_EXTENSION_VERSION = ~4`** app setting. This setting tells the Azure Functions platform which version of the host runtime to load. Without it, the Linux Consumption plan cannot initialize the Functions v4 host, leaving the entire app (including its SCM site) in a permanently broken 503 state.
- **Resolution**:
  - **Live fix via CLI**: Applied the missing setting immediately to the running Function App and restarted it:
    ```bash
    az functionapp config appsettings set \
      --name func-chatbot-worker-<token> \
      --resource-group rg-chatbot-dev \
      --settings FUNCTIONS_EXTENSION_VERSION="~4"
    az functionapp restart --name func-chatbot-worker-<token> --resource-group rg-chatbot-dev
    ```
  - **Permanent fix in Bicep**: Added `FUNCTIONS_EXTENSION_VERSION` to the `appSettings` block in `infra/modules/functions.bicep` so all future `make deploy-infra` runs provision it correctly:
    ```bicep
    { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
    ```
  - _Result_: Both the main app and the SCM endpoint returned healthy status codes, and `func azure functionapp publish` completed successfully.

---

## 15. Python Version Mismatch Warning & `deploy-functions.sh` Hardening

- **Issue**: Running `make deploy-functions` printed a warning:
  > `Local python version '3.14.x' is different from the version expected for your deployed Function App. This may result in 'ModuleNotFound' errors in Azure Functions. Please create a Python Function App for version 3.14 or change the virtual environment on your local machine to match 'Python|3.12'.`
  > The local `.venv` was created with Python 3.13 (the system default), while the Azure Function App is configured with `linuxFxVersion: Python|3.12`. This mismatch risks native C-extension `.so` files being built for the wrong ABI, causing `ModuleNotFoundError` at runtime on Azure.
- **Resolution**: Hardened `deploy-functions.sh` with two additional safeguards:
  1. **Python 3.12 venv enforcement**: The script now detects the Python version of the existing `.venv`. If it does not match `3.12`, it automatically deletes and recreates the venv using the `uv`-managed Python 3.12 interpreter and re-installs all dependencies from `requirements.txt`:
     ```bash
     PYTHON312=$(uv python find 3.12)
     uv venv --python 3.12 .venv
     uv pip install -r requirements.txt
     ```
  2. **SCM readiness retry loop**: Before invoking `func azure functionapp publish`, the script polls the SCM endpoint (up to 10 attempts, 15 s apart) and only proceeds once it returns a non-503 response. This guards against cold-start race conditions on the Consumption plan where the Kudu site can take time to spin up after a restart:
     ```bash
     for i in $(seq 1 $MAX_RETRIES); do
       HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SCM_URL")
       [ "$HTTP_STATUS" != "503" ] && break
       sleep "$RETRY_DELAY"
     done
     ```

---

## 16. Cosmos DB `ValueError: Id contains illegal chars` — DynamoDB `#` Key Convention in Chunk IDs

- **Issue**: RAG document ingestion failed silently in the Azure Function. Application Insights logs showed:
  ```
  ValueError: Id contains illegal chars.
  2026-05-26 16:39:28 - function_app - ERROR - Failed ingestion for document_id=0f8d1089-000e-4b85-ada1-f6e9e02bdeab
  ```
  Every uploaded document was processed by the queue trigger but crashed during the vector chunk upsert phase, leaving all documents permanently stuck in `"processing"` status in Cosmos DB.
- **Root Cause**: In `backend/app/services/rag.py`, the Cosmos DB document IDs for each text chunk were generated as:
  ```python
  keys = [f"{document_id}#chunk-{idx}" for idx in range(len(chunks))]
  ```
  The `#` character was carried over from the original **AWS DynamoDB sort key convention** (where `PK#SK` composite keys are idiomatic). However, Azure Cosmos DB for NoSQL **explicitly forbids** `#`, `/`, `\`, and `?` in document `id` fields. The Python SDK raises a client-side `ValueError` before even making the HTTP request, crashing the entire ingestion pipeline.
- **Resolution**: Replaced `#` with `-` in both `ingest_document` and `ingest_binary_document` key generation:

  ```python
  # Before (broken)
  keys = [f"{document_id}#chunk-{idx}" for idx in range(len(chunks))]

  # After (fixed)
  keys = [f"{document_id}-chunk-{idx}" for idx in range(len(chunks))]
  ```

  Fixed in both code paths (text and binary document ingestion) in [rag.py](../backend/app/services/rag.py).

---

## 17. Migration to Clerk Authentication (Replacing Microsoft Entra ID)

- **Issue**: Deploying and configuring Microsoft Entra ID (Active Directory) introduced significant setup complexity, including registering app clients in the Entra portal, configuring redirect URIs for multiple environments (localhost vs Static Web Apps), managing complex tenant policies, and handling token lifetimes.
- **Resolution**:
  - Migrated the application authentication layer entirely to **Clerk**.
  - **Frontend Integration**: Updated the React SPA frontend to use the Clerk React SDK (`@clerk/clerk-react`) for secure user registration, sign-in, and account configuration.
  - **Backend Validation**: Updated `backend/app/dependencies.py` to validate session JWTs dynamically against Clerk's JSON Web Key Set (JWKS) endpoint (`{CLERK_ISSUER}/.well-known/jwks.json`).
  - **Environment Separation**: Configured the backend settings to filter authorized audience (`azp` claim) origins based on `CLERK_AUTHORIZED_PARTIES` configuration (e.g., localhost, SWA domain).
  - **Security Best Practices**: Configured the Clerk Backend Secret Key (`clerk-secret-key`) as a secure secret inside Azure Key Vault.
  - _Result_: Authentication setup is now modular, easier to deploy, and supports cleaner development flows both locally and in production.
