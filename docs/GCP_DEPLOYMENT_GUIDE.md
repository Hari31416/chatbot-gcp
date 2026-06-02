# GCP Serverless Chatbot & RAG Platform: Deployment Guide

This guide details the step-by-step pipeline to provision the base infrastructure, deploy containerized backend compute, configure event-driven document ingestion, and publish the Vite React SPA to Firebase Hosting.

---

## Prerequisites

Before starting, ensure you have installed the following developer command-line tools locally:
- [Google Cloud CLI (gcloud)](https://cloud.google.com/sdk/docs/install)
- [Terraform CLI (>= 1.7.0)](https://developer.hashicorp.com/terraform/downloads)
- [Firebase CLI](https://firebase.google.com/docs/cli)
- [uv (Python Package Manager)](https://github.com/astral-sh/uv)
- [pnpm (Node Package Manager)](https://pnpm.io/)

---

## Step 1: GCP Project Authentication

1. Open your shell and authenticate your Google Account credentials:
   ```bash
   gcloud auth login
   ```

2. Establish your project context:
   ```bash
   gcloud config set project YOUR_GCP_PROJECT_ID
   ```

3. Generate local Application Default Credentials (ADC) so Terraform can authenticate requests against GCP APIs seamlessly:
   ```bash
   gcloud auth application-default login
   ```

> [!IMPORTANT]
> Make sure your GCP project has an active **billing account** linked in the GCP Console. Secret Manager, Cloud Run scaling, and Document AI APIs require billing to be enabled.

---

## Step 2: Initialize Firebase Console

1. Open the [Firebase Console](https://console.firebase.google.com/).
2. Click **Add project** and search/select your existing GCP Project ID.
3. Switch your Firebase project to the **Blaze (Pay-as-you-go)** plan (required to support serverless compute integrations).
4. Under **Build** -> **Authentication** -> **Sign-in method**, click **Get Started** and enable the **Email/Password** provider.
5. Register a new **Web App** inside your Firebase project settings (click the `</>` icon) to get your client-side keys:
   - `apiKey`
   - `authDomain`
   - `projectId`
   - `appId`

---

## Step 3: Base Infrastructure Provisioning

Configure input parameters for Terraform:
```bash
cp gcp-infra/terraform.tfvars.example gcp-infra/terraform.tfvars
```

Edit `gcp-infra/terraform.tfvars` and set your project details:
```hcl
project_id  = "YOUR_GCP_PROJECT_ID"
region      = "asia-south1"
environment = "dev"
```

Provision resources (APIs enablement, GCS buckets, and Firestore Native Database):
```bash
make deploy-infra
```

---

## Step 4: Populate secrets in Secret Manager

For security, LiteLLM third-party API keys are populated directly through `gcloud` to keep credentials out of Terraform state files and git history.

Ensure your `.env` file has the three keys set:
```bash
LITELLM_API_KEY=your_main_llm_api_key
LITELLM_VISION_API_KEY=your_vision_api_key
LITELLM_EMBEDDING_API_KEY=your_embedding_api_key
```

Then push all three keys to Secret Manager in one command:
```bash
make push-secrets
```

This reads the values directly from `.env` and pushes each as a new version in Secret Manager. The previously bootstrapped placeholder values are superseded by these live keys.

> [!NOTE]
> You can re-run `make push-secrets` at any time to rotate credentials. Cloud Run will pick up the new `latest` version on next deployment.

---

## Step 5: Document AI Processor Setup

1. In the Google Cloud Console, navigate to **Document AI** -> **Processors**.
2. Click **Create Processor** and select standard **Document OCR**.
3. Name it `chatbot-ocr`, keep region set to **us**, and click **Create**.
4. Copy the **Processor ID** displayed on the processor dashboard.
5. Open your local root `.env` file and append the processor ID:
   - `DOCUMENT_AI_PROCESSOR_ID="YOUR_PROCESSOR_ID"`

---

## Step 6: Build & Deploy Container Services

`GCP_PROJECT_ID` and other variables are automatically loaded from your `.env` file — no manual `export` needed.

Use the make targets (recommended):
```bash
# 1. Build and deploy private RAG ingestion worker
make deploy-worker

# 2. Build and deploy public FastAPI API container
make deploy-backend

# 3. Pull live Terraform outputs (API URL, bucket name) into your root .env
python3 update-env.py
```

> [!NOTE]
> You can also run the scripts directly (`./deploy-worker.sh`, `./deploy-backend.sh`) — both scripts source `.env` automatically if run from the project root.

---

## Step 7: Deploy TypeScript SPA Frontend

Log in to the Firebase CLI and publish static assets to Firebase Hosting:

```bash
# 1. Log in to Firebase
firebase login

# 2. Bind target environment
cd frontend
firebase use --add YOUR_GCP_PROJECT_ID
```

Query the active API URL using:
```bash
cd ..
./show-outputs.sh
```

Create `frontend/.env` file and populate Firebase web client keys and backend URL:
```bash
PORT=3333
VITE_API_BASE_URL=https://chatbot-api-xxxxx.a.run.app  # Deployed API URL
ALLOWED_HOSTS=localhost,127.0.0.1
VITE_FIREBASE_API_KEY=YOUR_FIREBASE_API_KEY
VITE_FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=YOUR_PROJECT_ID
VITE_FIREBASE_APP_ID=YOUR_FIREBASE_APP_ID
```

Compile React assets and deploy to Firebase Hosting:
```bash
./deploy-frontend.sh
```

---

## Step 8: Verification

Retrieve the active URLs of the live stack:
```bash
./show-outputs.sh
```

Verify that the health check returns `200 OK`:
```bash
curl -fsS "https://chatbot-api-xxxxx.a.run.app/health"
```
