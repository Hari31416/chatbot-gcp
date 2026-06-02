#!/bin/bash
set -euo pipefail

export GCP_REGION="${GCP_REGION:-asia-south1}"
export IMAGE_TAG="$(git rev-parse --short HEAD 2>/dev/null || echo latest)"
export IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}/chatbot/api:${IMAGE_TAG}"

echo "🐳 Building FastAPI API container image via Cloud Build..."
gcloud builds submit backend --tag "$IMAGE" --project "$GCP_PROJECT_ID"

echo "🔄 Deploying via Terraform..."
terraform -chdir=gcp-infra apply \
  -var="project_id=${GCP_PROJECT_ID}" \
  -var="region=${GCP_REGION}" \
  -var="api_image=${IMAGE}" \
  -auto-approve

echo "🎉 Backend deployment complete!"
