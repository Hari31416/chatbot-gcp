AZURE_ENV_NAME ?= dev
AZURE_LOCATION ?= centralindia

export AZURE_ENV_NAME
export AZURE_LOCATION

# Load environment variables from .env if it exists
ifneq ("$(wildcard .env)","")
  include .env
  export
endif

.PHONY: deploy-infra deploy-backend deploy-functions deploy-frontend deploy-all

deploy-infra:
	@echo "🚀 Provisioning Azure Infrastructure via Bicep..."
	az deployment sub create \
	  --location $(AZURE_LOCATION) \
	  --template-file infra/main.bicep \
	  --parameters environmentName=$(AZURE_ENV_NAME) location=$(AZURE_LOCATION) \
	               liteLlmApiKey="$(LITELLM_API_KEY)" liteLlmVisionApiKey="$(LITELLM_VISION_API_KEY)" \
	               clerkSecretKey="$(CLERK_SECRET_KEY)" \
	               clerkIssuer="$(CLERK_ISSUER)" \
	               clerkAuthorizedParties="$(CLERK_AUTHORIZED_PARTIES)"

deploy-backend:
	@echo "🚀 Building backend container and deploying to Azure Container Apps..."
	./deploy-backend.sh

deploy-functions:
	@echo "🚀 Deploying background queue worker to Azure Functions..."
	./deploy-functions.sh

deploy-frontend:
	@echo "🚀 Compiling React frontend and deploying to Azure Static Web Apps..."
	./deploy-frontend.sh

deploy-all: deploy-infra deploy-backend deploy-functions deploy-frontend
	@echo "🎉 Full Azure stack deployment complete!"

show-outputs:
	@./get-outputs.sh

logs:
	@echo "📋 Starting combined log tail..."
	@echo "Press Ctrl+C to stop."
	@echo "--- Backend (Container App) Logs ---"
	@az containerapp logs show --resource-group rg-chatbot-$(AZURE_ENV_NAME) --name chatbot-backend --follow --tail 30 & \
	BACKEND_PID=$$! ; \
	echo "--- Function App (App Insights) Logs ---" ; \
	RG="rg-chatbot-$(AZURE_ENV_NAME)" ; \
	APP_ID=$$(az resource list --resource-group $$RG --resource-type "microsoft.insights/components" --query "[0].name" -o tsv | xargs -I{} az resource show --resource-group $$RG --resource-type "microsoft.insights/components" --name {} --query "properties.AppId" -o tsv) ; \
	TOKEN=$$(az account get-access-token --resource "https://api.applicationinsights.io" --query "accessToken" -o tsv) ; \
	while true; do \
		curl -s -X POST "https://api.applicationinsights.io/v1/apps/$$APP_ID/query" \
			-H "Authorization: Bearer $$TOKEN" \
			-H "Content-Type: application/json" \
			-d '{"query": "requests | union traces | union exceptions | where timestamp > ago(1m) | order by timestamp asc | project timestamp, severityLevel, message=coalesce(message, outerMessage, name)"}' \
			| python3 -c " \
import sys, json; \
try: \
    d = json.load(sys.stdin); \
    rows = d['tables'][0]['rows']; \
    cols = [c['name'] for c in d['tables'][0]['columns']]; \
    for r in rows: \
        row = dict(zip(cols, r)); \
        print(f\\\"{row['timestamp'][11:19]} [FunctionApp] sev={row['severityLevel']} {row['message']}\\\"); \
except Exception: \
    pass" 2>/dev/null ; \
		sleep 10 ; \
	done & \
	FUNC_PID=$$! ; \
	trap 'kill $$BACKEND_PID $$FUNC_PID 2>/dev/null' INT TERM EXIT ; \
	wait
