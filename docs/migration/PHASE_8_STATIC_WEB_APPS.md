# Phase 8 — Static Web Apps Migration

> Replace S3 Static Website Hosting with Azure Static Web Apps (ASWA) for the React/Vite frontend.

---

## Goal

Deploy the frontend to Azure Static Web Apps, which provides free hosting with built-in CDN, SSL certificates, custom domains, and SPA routing — with zero configuration overhead.

---

## Current State (AWS)

### S3 Static Website Hosting

| Component       | Details                                             |
| :-------------- | :-------------------------------------------------- |
| Bucket          | `chatbot-frontend-{account_id}-{env}`               |
| Public access   | Enabled (public read policy)                        |
| Index/Error doc | `index.html` / `index.html` (SPA fallback)          |
| CDN             | None (direct S3 website URL)                        |
| SSL             | None (HTTP only via S3 website URL)                 |
| Deploy script   | `deploy-frontend.sh` → `pnpm build` + `aws s3 sync` |

### Frontend Configuration

```bash
# frontend/.env
VITE_API_BASE_URL=https://...lambda-url...on.aws/
VITE_COGNITO_CLIENT_ID=...    # → replaced by VITE_AZURE_CLIENT_ID in Phase 4
VITE_AWS_REGION=ap-south-1    # → no longer needed
```

---

## Target State (Azure)

### Azure Static Web Apps (Free Plan)

| Feature            | Value                                               |
| :----------------- | :-------------------------------------------------- |
| **Hosting**        | Free (always free tier)                             |
| **SSL**            | Automatic, free certificates                        |
| **CDN**            | Built-in global CDN                                 |
| **Custom domains** | Supported (free)                                    |
| **SPA routing**    | Automatic fallback to `index.html`                  |
| **Bandwidth**      | 100 GB/month (free)                                 |
| **Build**          | Can build from GitHub or deploy pre-built artifacts |

---

## Code Changes

### 8.1 Update Frontend Environment Variables

```bash
# frontend/.env (production)
VITE_API_BASE_URL=https://chatbot-backend.{region}.azurecontainerapps.io
VITE_AZURE_CLIENT_ID=your-entra-app-client-id
VITE_ENTRA_AUTHORITY=https://your-tenant.ciamlogin.com
```

Remove all AWS-specific env vars:

```diff
- VITE_COGNITO_CLIENT_ID=...
- VITE_COGNITO_USER_POOL_ID=...
- VITE_AWS_REGION=...
```

### 8.2 Update `frontend/.env.example`

```bash
PORT=3333
VITE_API_BASE_URL=http://localhost:8080
ALLOWED_HOSTS=localhost,127.0.0.1

# Azure Auth (Phase 4)
VITE_AZURE_CLIENT_ID=
VITE_ENTRA_AUTHORITY=
```

### 8.3 Add SWA Configuration File

Create `frontend/staticwebapp.config.json`:

```json
{
  "navigationFallback": {
    "rewrite": "/index.html",
    "exclude": ["/assets/*", "/*.ico", "/*.svg", "/*.png"]
  },
  "globalHeaders": {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin"
  },
  "mimeTypes": {
    ".json": "application/json",
    ".woff2": "font/woff2"
  }
}
```

### 8.4 Remove `vercel.json`

The `frontend/vercel.json` is no longer needed:

```diff
- {
-   "rewrites": [{ "source": "/(.*)", "destination": "/" }]
- }
```

---

## Deployment

### Option A: Deploy Pre-Built Artifacts (Recommended)

```bash
# Build the frontend
cd frontend
pnpm build

# Deploy to Azure Static Web Apps
swa deploy ./dist \
  --deployment-token $AZURE_SWA_DEPLOYMENT_TOKEN \
  --env production
```

### Option B: Deploy via Azure CLI

```bash
# Create Static Web App (one-time)
az staticwebapp create \
  --name swa-chatbot-dev \
  --resource-group rg-chatbot-dev \
  --source ./frontend \
  --location centralindia \
  --sku Free

# Deploy
az staticwebapp deploy \
  --name swa-chatbot-dev \
  --resource-group rg-chatbot-dev \
  --app-location ./frontend \
  --output-location dist
```

### Option C: GitHub Actions (CI/CD)

Azure Static Web Apps can auto-deploy from a GitHub repository. Running `az staticwebapp create` with `--login-with-github` sets up a GitHub Actions workflow automatically.

---

## Replace `deploy-frontend.sh`

```bash
#!/bin/bash
set -euo pipefail

echo "Building frontend..."
cd frontend
pnpm install --frozen-lockfile
pnpm build

echo "Deploying to Azure Static Web Apps..."
npx @azure/static-web-apps-cli deploy ./dist \
  --deployment-token "${AZURE_SWA_DEPLOYMENT_TOKEN}" \
  --env production

echo "Frontend deployment complete!"
```

---

## Bicep Module: `infra/modules/static-web-app.bicep`

```bicep
param location string
param environmentName string

resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: 'swa-chatbot-${environmentName}'
  location: location
  tags: { 'azd-env-name': environmentName }
  sku: { name: 'Free', tier: 'Free' }
  properties: {
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
    buildProperties: {
      appLocation: '/frontend'
      outputLocation: 'dist'
    }
  }
}

output staticWebAppName string = staticWebApp.name
output staticWebAppUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output deploymentToken string = listSecrets(staticWebApp.id, staticWebApp.apiVersion).properties.apiKey
```

---

## Local Development

Use the SWA CLI to simulate the full stack locally:

```bash
# Start backend locally
cd backend && uvicorn app.main:app --port 8080

# In another terminal, start frontend with SWA CLI
cd frontend
swa start http://localhost:5173 --api-location http://localhost:8080
```

The SWA CLI:

- Serves the Vite dev server
- Proxies API calls to the backend
- Emulates Entra authentication headers

---

## Verification

- [ ] `pnpm build` succeeds with updated env vars
- [ ] `staticwebapp.config.json` is included in `dist/` output
- [ ] SWA deployment succeeds
- [ ] SPA routing works (deep links to `/chat/123` serve `index.html`)
- [ ] Frontend can reach the Container Apps backend via `VITE_API_BASE_URL`
- [ ] Authentication flow works end-to-end (Entra login → API calls)
- [ ] HTTPS is automatically enabled
- [ ] `vercel.json` is removed
- [ ] Old `deploy-frontend.sh` (S3 sync) is replaced

---

## Next Phase

→ [Phase 9 — Observability](./PHASE_9_OBSERVABILITY.md)
