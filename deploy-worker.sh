#!/usr/bin/env bash
set -euo pipefail

# Load environment variables from .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

export GCP_REGION="${GCP_REGION:-asia-south1}"
export IMAGE_TAG="$(git rev-parse --short HEAD 2>/dev/null || echo latest)"
export WORKER_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}/chatbot/worker:${IMAGE_TAG}"

echo "🐳 Building ingestion worker container image via Cloud Build..."
gcloud builds submit backend \
  --config backend/cloudbuild.worker.yaml \
  --substitutions="_IMAGE=${WORKER_IMAGE}" \
  --project "$GCP_PROJECT_ID"

echo "🔄 Deploying via Terraform..."
terraform -chdir=gcp-infra apply \
  -var="project_id=${GCP_PROJECT_ID}" \
  -var="region=${GCP_REGION}" \
  -var="worker_image=${WORKER_IMAGE}" \
  -auto-approve

echo "🎉 Ingestion worker deployment complete!"
