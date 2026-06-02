#!/bin/bash
set -euo pipefail

# Load environment variables from .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

if ! command -v func > /dev/null 2>&1; then
  echo "❌ Azure Functions Core Tools not found."
  echo "   Install:"
  echo "     brew tap azure/functions"
  echo "     brew install azure-functions-core-tools@4"
  exit 1
fi

FUNCTION_APP_NAME="${AZURE_FUNCTION_APP_NAME:-}"

if [ -z "$FUNCTION_APP_NAME" ]; then
  echo "🔍 Fetching Azure Function App name from deployment outputs..."
  FUNCTION_APP_NAME=$(az deployment sub show --name main --query "properties.outputs.azure_function_app_name.value" -o tsv 2>/dev/null || true)
fi

if [ -z "$FUNCTION_APP_NAME" ] || [ "$FUNCTION_APP_NAME" == "null" ]; then
  echo "❌ Error: Could not find Azure Function App Name. Please run 'make deploy-infra' first."
  exit 1
fi

# ── Python 3.12 virtual environment ──────────────────────────────────────────
# Azure Function App is configured with Python|3.12. We must build with the
# same version locally to avoid ModuleNotFoundError at runtime.
PYTHON312=$(uv python find 3.12 2>/dev/null || true)
if [ -z "$PYTHON312" ]; then
  echo "🔽 Python 3.12 not found via uv, installing..."
  uv python install 3.12
  PYTHON312=$(uv python find 3.12)
fi
echo "✅ Using Python: $PYTHON312 ($(${PYTHON312} --version))"

cd backend

# Recreate the .venv with Python 3.12 if it doesn't match
VENV_PYTHON_VERSION=$(.venv/bin/python --version 2>/dev/null | awk '{print $2}' | cut -d. -f1-2 || echo "")
if [ "$VENV_PYTHON_VERSION" != "3.12" ]; then
  echo "🔄 Recreating .venv with Python 3.12 (current: ${VENV_PYTHON_VERSION:-none})..."
  rm -rf .venv
  uv venv --python 3.12 .venv
  uv pip install -r requirements.txt
  echo "✅ .venv recreated with Python 3.12"
fi

# ── Wait for SCM endpoint to be ready ────────────────────────────────────────
SCM_URL="https://${FUNCTION_APP_NAME}.scm.azurewebsites.net"
MAX_RETRIES=10
RETRY_DELAY=15

echo "🚀 Deploying Python Function App to $FUNCTION_APP_NAME..."
echo "⏳ Waiting for SCM endpoint to be ready ($SCM_URL)..."

for i in $(seq 1 $MAX_RETRIES); do
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SCM_URL" 2>/dev/null || echo "000")
  if [ "$HTTP_STATUS" != "503" ] && [ "$HTTP_STATUS" != "000" ]; then
    echo "✅ SCM endpoint ready (HTTP $HTTP_STATUS)"
    break
  fi
  echo "   Attempt $i/$MAX_RETRIES: SCM returned $HTTP_STATUS, retrying in ${RETRY_DELAY}s..."
  if [ "$i" -eq "$MAX_RETRIES" ]; then
    echo "❌ SCM endpoint still unavailable after $MAX_RETRIES attempts."
    echo "   Try restarting the Function App: az functionapp restart --name $FUNCTION_APP_NAME --resource-group <rg>"
    exit 1
  fi
  sleep "$RETRY_DELAY"
done

# Deploy utilizing the Azure Functions Core Tools
func azure functionapp publish "$FUNCTION_APP_NAME" --python

echo "🎉 Function App deployment complete!"
