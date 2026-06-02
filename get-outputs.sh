#!/bin/bash
set -euo pipefail

echo "🔍 Fetching GCP Chatbot stack deployment outputs..."
echo "--------------------------------------------------------"

cd gcp-infra
API_URL=$(terraform output -raw api_url 2>/dev/null || echo "Not Deployed")
WORKER_URL=$(terraform output -raw worker_url 2>/dev/null || echo "Not Deployed")
BUCKET_NAME=$(terraform output -raw bucket_name 2>/dev/null || echo "Not Deployed")

echo "🚀 Live Chatbot GCP Status Dashboard:"
echo "--------------------------------------------------------"
printf "%-30s : %s\n" "GCP Project ID" "${GCP_PROJECT_ID:-Not Set}"
printf "%-30s : %s\n" "GCS Bucket Name" "$BUCKET_NAME"
printf "%-30s : %s\n" "Backend API URL" "$API_URL"
printf "%-30s : %s\n" "Ingestion Worker URL" "$WORKER_URL"
echo "--------------------------------------------------------"
printf "%-30s : %s\n" "Swagger API Docs" "$API_URL/docs"
echo "--------------------------------------------------------"
