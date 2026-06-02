# Azure Deployment & Authentication Setup Guide

This guide provides a comprehensive, step-by-step walk-through to provision the Azure infrastructure, configure Clerk authentication, create test users, store gateway API secrets, and deploy the decoupled FastAPI backend and React frontend.

---

## 📋 Prerequisites

Before starting the deployment, make sure you have installed and configured the following tools locally:

1. **Azure CLI**: Run `az login` to authenticate with your active Azure Subscription.
2. **Docker**: Running locally to allow packaging the FastAPI backend containers.
3. **Python & uv**: For backend local testing and packaging.
4. **Node.js & pnpm**: For building and bundling the frontend React assets.

---

## 🛠️ Step 1: Authenticate with Azure

Open your terminal and authenticate the Azure CLI using one of the following methods, depending on your development environment:

### Method A: Interactive Web Browser (Default for local machines)

Run the following command. It will automatically open your default browser to prompt for your credentials:

```bash
az login
```

### Method B: Device Code Login (For headless hosts, cloud-shells, WSL, or SSH sessions)

If you are working on a remote machine where a GUI browser cannot open automatically, use the device code flow:

```bash
az login --use-device-code
```

_This will output a one-time code (e.g., `WD32E54F3`) and request you to open `https://microsoft.com/devicelogin` on any internet-connected browser (like your phone or desktop) to complete authentication._

### Method C: Service Principal Secret (For CI/CD runners like GitHub Actions)

If you are automating deployments programmatically, authenticate using a Service Principal:

```bash
az login --service-principal \
  -u "<app-id-or-sp-name>" \
  -p "<service-principal-client-secret>" \
  --tenant "<your-tenant-id>"
```

---

### Step 1.2: Select and Set Active Subscription

Once authenticated, list your active billing scopes and set the target subscription ID:

```bash
# List all subscriptions in a readable table format
az account list --output table

# Set the active subscription context
az account set --subscription "<your-subscription-id>"
```

---

## 🏗️ Step 2: Deploy Core Infrastructure (Bicep)

The main Bicep script handles resource group provisioning, network isolation, role assignments, database containers, and computing environments.

Deploy the infrastructure using the unified `Makefile`:

```bash
# Deploys main.bicep to your subscription
# You can customize these defaults in the Makefile or override them at invocation:
# e.g., make deploy-infra AZURE_ENV_NAME=prod AZURE_LOCATION=westeurope
# Note: Make sure LITELLM_API_KEY and LITELLM_VISION_API_KEY are configured in .env before running.
make deploy-infra
```

### What this provisions:

- **Resource Group**: `rg-chatbot-dev`
- **Log Analytics Workspace & Application Insights**: Custom telemetry ingestion environment
- **Azure Storage Account**: Private file uploads containers (`uploads`), queues (`ingestion-queue`), and storage tables
- **Azure Cosmos DB NoSQL Account**: Storage database and vector indexing containers (`conversations`, `vectors`)
- **Azure Container Registry (ACR)**: Secure host for backend Docker builds
- **Azure Container Apps Environment & Container App**: High-performance FastAPI compute engine (scales down to 0 instances when idle)
- **Azure Static Web Apps (SWA)**: Global CDN host for React client assets
- **Azure Key Vault**: Highly secure KMS store for LiteLLM gateway credentials

### Extract Deployment Keys and Endpoints:

After Bicep completes, extract key outputs to use in the subsequent steps:

```bash
# Get the backend API URL
az deployment sub show \
  --name "rg-chatbot-dev-deployment" \
  --query "properties.outputs.BACKEN_URL.value"

# Get the Static Web App deployment token
az deployment sub show \
  --name "rg-chatbot-dev-deployment" \
  --query "properties.outputs.AZURE_SWA_DEPLOYMENT_TOKEN.value"
```

---

## 🔐 Step 3: Configure Clerk Authentication

User sign-in is handled by [Clerk](https://clerk.com), not Microsoft Entra ID. See **[CLERK_AUTH_SETUP.md](./CLERK_AUTH_SETUP.md)** for the full key checklist and dashboard steps.

**Quick summary — keys you need:**

| Key                          | Where to set                 |
| ---------------------------- | ---------------------------- |
| `VITE_CLERK_PUBLISHABLE_KEY` | `frontend/.env` (build-time) |
| `CLERK_ISSUER`               | Root `.env` + Container App  |
| `CLERK_AUTHORIZED_PARTIES`   | Root `.env` + Container App  |

---

### (Legacy) Microsoft Entra ID — replaced by Clerk

The steps below are **deprecated** and kept for reference only. Use Clerk instead.

Microsoft Entra ID (formerly Azure Active Directory) previously served as the Identity Provider for this chatbot platform.

### A. Create an App Registration

1. Sign in to the [Azure Portal](https://portal.azure.com/).
2. Navigate to **Microsoft Entra ID** $\rightarrow$ **App registrations** $\rightarrow$ **New registration**.
3. Set the following options:
   - **Name**: `chatbot-auth`
   - **Supported account types**: "Accounts in this organizational directory only (Single tenant)"
   - **Redirect URI**:
     - Select **Single-page application (SPA)**.
     - Enter: `http://localhost:3000` (for local React development) and your deployed Static Web App URL (extracted in Step 2).
4. Click **Register**.

### B. Extract App Registration IDs

After registration, copy the following values from the registration dashboard's **Overview** panel:

- **Application (client) ID**: _This is your Client ID_ (e.g., `VITE_AZURE_CLIENT_ID` / `AZURE_CLIENT_ID`).
- **Directory (tenant) ID**: _This is your Tenant ID_ (e.g., `AZURE_TENANT_ID`).
- **Authority Endpoint**: Format as `https://login.microsoftonline.com/<tenant-id>` (e.g., `VITE_ENTRA_AUTHORITY` / `ENTRA_AUTHORITY`).

### C. Configure User Flows and API Permissions

Ensure users can authenticate. Under **API permissions**:

1. Click **Add a permission** $\rightarrow$ **Microsoft Graph** $\rightarrow$ **Delegated permissions**.
2. Make sure `User.Read` is selected (this allows retrieving the logged-in user's email).
3. Click **Add permissions**.

---

## 👥 Step 4: Create Authorized Test Users in Clerk

Authentication is managed via Clerk. You can add users directly from your Clerk Dashboard:

1. Sign in to your [Clerk Dashboard](https://dashboard.clerk.com).
2. Navigate to **User Management** $\rightarrow$ **Users** in the left-hand menu.
3. Click **Add user** (or **Invite user**) to configure credentials for testing.
4. Fill in the email, username, and password, then click **Create**.
5. Alternatively, in development mode, you can sign up directly through the React frontend running locally at `http://localhost:3000` to create your test account.

---

## 🔑 Step 5: Store Secrets in Key Vault

The FastAPI application uses system-assigned managed identity to fetch runtime secrets securely.

> [!TIP]
> **Automated Provisioning**: The `make deploy-infra` step automatically extracts your `LITELLM_API_KEY` and `LITELLM_VISION_API_KEY` from your local `.env` file and writes them as secrets into the Key Vault during deployment!

If you want to update them manually later, or if you get a `ForbiddenByRbac` error, follow these steps:

### A. Resolve RBAC Permissions (If Blocked)

By default, the Key Vault uses Azure RBAC. To list or set secrets, grant your signed-in identity access:

```bash
# Get your active CLI Object ID
USER_OID=$(az ad signed-in-user show --query id --output tsv)

# Assign Key Vault Secrets Officer role
az role assignment create \
  --role "Key Vault Secrets Officer" \
  --assignee "$USER_OID" \
  --scope "/subscriptions/<your-subscription-id>/resourceGroups/rg-chatbot-dev/providers/Microsoft.KeyVault/vaults/kv-chatbot-jdox4gjgni76y"
```

### B. Manually Set Secrets (Optional)

```bash
# 1. Store your primary model API key
az keyvault secret set \
  --vault-name "kv-chatbot-jdox4gjgni76y" \
  --name "litellm-api-key" \
  --value "<your-api-key>"

# 2. Store your vision model API key
az keyvault secret set \
  --vault-name "kv-chatbot-jdox4gjgni76y" \
  --name "litellm-vision-api-key" \
  --value "<your-api-key>"
```

---

## 🚀 Step 6: Deploy the Backend API (Container Apps)

Build and package the Python FastAPI application using Azure Container Registry (ACR) and update the Container App:

```bash
# 1. Run local test suite to verify code sanity
cd backend
uv run pytest

# 2. Execute ACR remote build and Container App update via Makefile
cd ..
make deploy-backend
```

---

## 💻 Step 7: Deploy the Frontend Client (Static Web Apps)

Configure your React environment variables to link with Clerk and the deployed backend API:

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Create your environment configuration file (`.env`):
   ```bash
   cp .env.example .env
   ```
3. Populate the Clerk and API variables (see `docs/CLERK_AUTH_SETUP.md`):
   ```env
   VITE_API_BASE_URL=https://chatbot-backend.dev-api.azurecontainerapps.io
   VITE_CLERK_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
4. Build the application and upload it to Azure Static Web Apps:
   ```bash
   cd ..
   # Make sure AZURE_SWA_DEPLOYMENT_TOKEN is exported or loaded in your shell:
   export AZURE_SWA_DEPLOYMENT_TOKEN="<your-extracted-token>"
   make deploy-frontend
   ```

---

## 🧪 Step 8: End-to-End Verification

Now that the entire stack is successfully deployed, verify the live environment:

1. Navigate to your deployed Frontend URL (e.g. `https://swa-chatbot-dev.azurestaticapps.net`).
2. You will be redirected to the Microsoft login page. Sign in with the **Test User** credentials you created in Step 4.
3. Once authenticated, you will be redirected back to the beautiful chat dashboard.
4. Try typing a message: "Explain the benefit of Azure Container Apps."
5. Test the **RAG Document Catalog**: Upload a sample PDF or text file. Watch the system transition the status from `processing` to `ready`, and then ask questions using context-enhanced knowledge!

---

## 🗑️ Step 9: Teardown (Bring Down Infrastructure)

To completely destroy all provisioned resources and stop any active cloud costs, you can delete the entire Azure Resource Group:

```bash
az group delete --name "rg-chatbot-${AZURE_ENV_NAME:-dev}" --yes --no-wait
```

_This will immediately request Azure to asynchronously delete all resources (Cosmos DB, Key Vault, Storage, ACA, SWAs) in the background._
