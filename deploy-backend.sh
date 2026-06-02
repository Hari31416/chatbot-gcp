#!/bin/bash
set -euo pipefail

REGISTRY="${AZURE_CONTAINER_REGISTRY:-crchatbotdev}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
RESOURCE_GROUP="rg-chatbot-${AZURE_ENV_NAME:-dev}"
APP_NAME="${AZURE_CONTAINER_APP_NAME:-chatbot-backend}"

echo "🔐 Logging in to Azure Container Registry ($REGISTRY)..."
az acr login --name "$REGISTRY"

echo "🐳 Building container image locally via Docker for linux/amd64 platform..."
docker build --platform linux/amd64 -t "$REGISTRY.azurecr.io/chatbot-backend:$IMAGE_TAG" ./backend

echo "🚀 Pushing image to ACR..."
docker push "$REGISTRY.azurecr.io/chatbot-backend:$IMAGE_TAG"

echo "🔄 Updating Container App..."
UPDATE_ARGS=(
  --name "$APP_NAME"
  --resource-group "$RESOURCE_GROUP"
  --image "$REGISTRY.azurecr.io/chatbot-backend:$IMAGE_TAG"
)

ENV_VARS=()
if [ -n "${CLERK_ISSUER:-}" ]; then
  ENV_VARS+=("CLERK_ISSUER=${CLERK_ISSUER}")
fi
if [ -n "${CLERK_AUTHORIZED_PARTIES:-}" ]; then
  ENV_VARS+=("CLERK_AUTHORIZED_PARTIES=${CLERK_AUTHORIZED_PARTIES}")
fi
if [ -n "${LITELLM_MODEL:-}" ]; then
  ENV_VARS+=("LITELLM_MODEL=${LITELLM_MODEL}")
fi
if [ -n "${LITELLM_BASE_URL:-}" ]; then
  ENV_VARS+=("LITELLM_BASE_URL=${LITELLM_BASE_URL}")
fi
if [ -n "${LITELLM_VISION_MODEL:-}" ]; then
  ENV_VARS+=("LITELLM_VISION_MODEL=${LITELLM_VISION_MODEL}")
fi
if [ -n "${LITELLM_VISION_BASE_URL:-}" ]; then
  ENV_VARS+=("LITELLM_VISION_BASE_URL=${LITELLM_VISION_BASE_URL}")
fi
if [ -n "${LITELLM_EMBEDDING_MODEL:-}" ]; then
  ENV_VARS+=("LITELLM_EMBEDDING_MODEL=${LITELLM_EMBEDDING_MODEL}")
fi
if [ -n "${EMBEDDING_DIMENSION:-}" ]; then
  ENV_VARS+=("EMBEDDING_DIMENSION=${EMBEDDING_DIMENSION}")
fi

if [ "${#ENV_VARS[@]}" -gt 0 ]; then
  UPDATE_ARGS+=(--set-env-vars "${ENV_VARS[@]}")
fi

az containerapp update "${UPDATE_ARGS[@]}"

echo "🎉 Backend deployment complete!"
