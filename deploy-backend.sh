#!/bin/bash
set -euo pipefail

# Load environment variables from .env if present (for direct script invocation)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "========================================="
echo "📦 Exporting backend requirements..."
echo "========================================="
cd backend
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
cd ..

export GCP_REGION="${GCP_REGION:-asia-south1}"
export IMAGE_TAG="$(git rev-parse --short HEAD 2>/dev/null || echo latest)"
if ! git diff --quiet HEAD 2>/dev/null; then
  export IMAGE_TAG="${IMAGE_TAG}-dirty-$(date +%s)"
fi
export IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}/chatbot/api:${IMAGE_TAG}"

echo "🐳 Building FastAPI API container image via Cloud Build..."
gcloud builds submit backend --tag "$IMAGE" --project "$GCP_PROJECT_ID"

echo "🔄 Deploying via Terraform..."

# Construct a JSON map of non-empty environment variables to pass to Terraform
additional_env_vars="{"
first=true

add_var() {
  local name="$1"
  local val="${!name:-}"
  if [ -n "$val" ]; then
    if [ "$first" = false ]; then
      additional_env_vars="${additional_env_vars},"
    fi
    additional_env_vars="${additional_env_vars}\"${name}\":\"${val}\""
    first=false
  fi
}

add_var "LITELLM_MODEL"
add_var "LITELLM_BASE_URL"
add_var "LITELLM_VISION_MODEL"
add_var "LITELLM_EMBEDDING_MODEL"
add_var "EMBEDDING_DIMENSION"
add_var "DOCUMENT_AI_LOCATION"
add_var "DOCUMENT_AI_PROCESSOR_ID"
add_var "DOCUMENT_AI_USE_LAYOUT_PARSER"
add_var "MAX_RAG_PAGES"
add_var "MAX_RAG_CHUNKS"
add_var "RAG_TOP_K"
add_var "RAG_CHUNK_SIZE"
add_var "RAG_CHUNK_OVERLAP"

additional_env_vars="${additional_env_vars}}"

terraform -chdir=gcp-infra apply \
  -var="project_id=${GCP_PROJECT_ID}" \
  -var="region=${GCP_REGION}" \
  -var="api_image=${IMAGE}" \
  -var="additional_env_vars=${additional_env_vars}" \
  -auto-approve

echo "🎉 Backend deployment complete!"
