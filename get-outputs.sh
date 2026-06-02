#!/bin/bash
set -euo pipefail

echo "🔍 Fetching Azure Chatbot stack deployment outputs..."
echo "--------------------------------------------------------"

# Run query once to fetch all outputs as a JSON block to minimize API latency
OUTPUTS=$(az deployment sub show --name main --query "properties.outputs" -o json 2>/dev/null || true)

if [ -z "$OUTPUTS" ] || [ "$OUTPUTS" == "null" ]; then
  echo "❌ Error: Could not find deployment 'main' in your Azure subscription."
  echo "Please verify you have run 'make deploy-infra' successfully and are logged in."
  exit 1
fi

# Function to parse JSON keys safely using built-in Python JSON module
parse_val() {
  echo "$OUTPUTS" | python3 -c "import sys, json; data = json.load(sys.stdin); key = '$1'.lower(); val = next((v.get('value') for k, v in data.items() if k.lower() == key), 'N/A'); print(val)"
}

# Extract values
REGISTRY=$(parse_val "AZURE_CONTAINER_REGISTRY")
REGISTRY_SERVER=$(parse_val "AZURE_CONTAINER_REGISTRY_LOGIN_SERVER")
KEYVAULT=$(parse_val "AZURE_KEYVAULT_NAME")
STORAGE=$(parse_val "AZURE_STORAGE_ACCOUNT_NAME")
COSMOS_DB=$(parse_val "COSMOS_DATABASE_NAME")
COSMOS_ENDPOINT=$(parse_val "COSMOS_ENDPOINT")
BACKEND_URL=$(parse_val "BACKEND_URL")
FRONTEND_URL=$(parse_val "FRONTEND_URL")
FUNCTION_APP_NAME=$(parse_val "AZURE_FUNCTION_APP_NAME")

echo "🚀 Live Chatbot Azure Status Dashboard:"
echo "--------------------------------------------------------"
printf "%-30s : %s\n" "Resource Group" "rg-chatbot-${AZURE_ENV_NAME:-dev}"
printf "%-30s : %s\n" "Azure Container Registry" "$REGISTRY ($REGISTRY_SERVER)"
printf "%-30s : %s\n" "Azure Key Vault" "$KEYVAULT"
printf "%-30s : %s\n" "Azure Storage Account" "$STORAGE"
printf "%-30s : %s\n" "Cosmos DB Database" "$COSMOS_DB"
printf "%-30s : %s\n" "Cosmos DB Endpoint" "$COSMOS_ENDPOINT"
printf "%-30s : %s\n" "Backend API URL" "https://$BACKEND_URL"
printf "%-30s : %s\n" "Function App Name" "$FUNCTION_APP_NAME"
printf "%-30s : %s\n" "Frontend URL" "$FRONTEND_URL"
echo "--------------------------------------------------------"
printf "%-30s : %s\n" "Swagger API Docs" "https://$BACKEND_URL/docs"
echo "--------------------------------------------------------"
