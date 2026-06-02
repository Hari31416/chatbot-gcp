# Serverless Chatbot and RAG Platform on GCP

A production-grade, secure, and fully serverless AI Chatbot and RAG (Retrieval-Augmented Generation) platform. The application is built using a decoupled Python FastAPI backend and a TypeScript React SPA frontend. Deployed natively on Google Cloud Platform (GCP), the platform achieves serverless real-time streaming, Firebase Authentication, and robust asynchronous document ingestion.

The architecture features Server-Sent Events (SSE) streaming through Cloud Run, Firebase Authentication on the frontend and backend, private multimodal attachment storage in Google Cloud Storage, and a decoupled event-driven RAG ingestion pipeline using Pub/Sub, Eventarc, a private Cloud Run worker, Document AI, and native Firestore for conversation history and vector storage.

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

---

## Core Technologies & Services

### GCP Services Used

- **Firebase Hosting:** Web static asset delivery over secure HTTPS, with direct rewrite support for SPA single-page routing fallback.
- **Cloud Run (FastAPI API):** Handles API requests (chat, streaming, attachments) with instant scale-to-zero capability and request-based billing.
- **Cloud Run (Ingestion Worker):** Private containerized FastAPI background worker, triggered by Eventarc events, to download and parse staging documents.
- **Firestore (Native Mode):** Stores user sessions, conversation metadata, message logs, and houses vector indexes for document search.
- **Google Cloud Storage (GCS):** Private object storage with deterministic prefixes (`uploads/` for message attachments, `staging/` for ingestion documents, and `rag-temp/` for temporary OCR operations).
- **Pub/Sub & Eventarc:** Facilitates zero-polling, event-driven decoupling. The GCS `OBJECT_FINALIZE` triggers GCS to publish to Pub/Sub, which Eventarc delivers directly to the ingestion worker.
- **Document AI:** Performs enterprise-grade OCR on multi-page PDFs and images.
- **Secret Manager:** Encrypted secret storage for third-party API keys (LiteLLM, Gemini, OpenAI). Mounts dynamically into Cloud Run environment variables.

---

## File Structure

```txt
chatbot-gcp/
├── gcp-infra/              # Terraform Infrastructure as Code (IaC)
│   ├── main.tf             # Core orchestrator
│   ├── variables.tf        # Input variable declarations
│   └── modules/            # Component modules (Storage, Firestore, Run, Ingestion, Secrets)
├── backend/                # Python FastAPI Backend
│   ├── app/
│   │   ├── main.py         # Main API app entrypoint
│   │   ├── worker.py       # Cloud Run worker event app entrypoint
│   │   ├── dependencies.py # Dependency injection providers
│   │   ├── services/       # Core business logic (RAG, Storage, LLM, Vector)
│   │   └── repositories/   # Persistence layer (Firestore ConversationRepository)
│   ├── Dockerfile          # Dockerfile for API
│   ├── Dockerfile.worker   # Dockerfile for Ingestion Worker
│   └── pyproject.toml      # Dependency & project configurations
├── frontend/               # TypeScript Vite React SPA
│   ├── src/
│   │   ├── App.tsx         # Core app UI & logic
│   │   ├── main.tsx        # React mounting entrypoint
│   │   └── services/       # Firebase and API integrations
│   ├── firebase.json       # Firebase Hosting routing declarations
│   └── package.json        # Dependencies list
├── Makefile                # Multi-command developer orchestration
├── deploy-backend.sh       # Script to build and push FastAPI API container
├── deploy-worker.sh        # Script to build and push Ingestion Worker container
└── deploy-frontend.sh      # Script to build and publish static bundle to Hosting
```

---

## Local Development

### 1. Prerequisite Setup

- Install [uv](https://github.com/astral-sh/uv) (Python package manager).
- Install [pnpm](https://pnpm.io/) (Node package manager).
- Install [Firebase CLI](https://firebase.google.com/docs/cli).
- Set up your `.env` configuration file in the project root by copying `.env.example`.

### 2. Startup Backend locally

```bash
cd backend
uv sync
uv run uvicorn app.main:app --port 8080 --reload
```

### 3. Startup Frontend locally

```bash
cd frontend
pnpm install
pnpm dev
```

### 4. Running Backend Tests

```bash
cd backend
uv run pytest
```

---

## Deployment Guide

We utilize a simple, deterministic multi-script pipeline:

### 1. Deploy GCP Infrastructure (Terraform)

Ensure you are logged into your GCP account (`gcloud auth login` and `gcloud auth application-default login`) and have created a billing-enabled project.

```bash
make deploy-infra
```

### 2. Deploy Background Ingestion Worker

```bash
make deploy-worker
```

### 3. Deploy API Application

```bash
make deploy-backend
```

### 4. Deploy SPA Frontend (Firebase Hosting)

```bash
make deploy-frontend
```
