GCP_REGION ?= asia-south1
export GCP_REGION

# Load environment variables from .env if it exists
ifneq ("$(wildcard .env)","")
  include .env
  export
endif

.PHONY: deploy-infra push-secrets deploy-backend deploy-worker deploy-frontend deploy-all show-outputs logs

deploy-infra:
	@echo "🚀 Provisioning GCP Infrastructure via Terraform..."
	cd gcp-infra && terraform init && terraform apply -var="project_id=$(GCP_PROJECT_ID)" -var="region=$(GCP_REGION)" -auto-approve

push-secrets:
	@echo "🔐 Pushing LiteLLM API keys from .env to GCP Secret Manager..."
	@[ -n "$(LITELLM_API_KEY)" ] || (echo "❌ LITELLM_API_KEY is not set in .env" && exit 1)
	@[ -n "$(LITELLM_VISION_API_KEY)" ] || (echo "❌ LITELLM_VISION_API_KEY is not set in .env" && exit 1)
	@[ -n "$(LITELLM_EMBEDDING_API_KEY)" ] || (echo "❌ LITELLM_EMBEDDING_API_KEY is not set in .env" && exit 1)
	@printf '%s' "$(LITELLM_API_KEY)" | gcloud secrets versions add litellm-api-key --data-file=- --project=$(GCP_PROJECT_ID)
	@echo "  ✅ litellm-api-key updated"
	@printf '%s' "$(LITELLM_VISION_API_KEY)" | gcloud secrets versions add litellm-vision-api-key --data-file=- --project=$(GCP_PROJECT_ID)
	@echo "  ✅ litellm-vision-api-key updated"
	@printf '%s' "$(LITELLM_EMBEDDING_API_KEY)" | gcloud secrets versions add litellm-embedding-api-key --data-file=- --project=$(GCP_PROJECT_ID)
	@echo "  ✅ litellm-embedding-api-key updated"
	@echo "🎉 All secrets pushed successfully!"

deploy-backend:
	@echo "🚀 Building backend container and deploying to Cloud Run..."
	./deploy-backend.sh

deploy-worker:
	@echo "🚀 Deploying background RAG ingestion worker to Cloud Run..."
	./deploy-worker.sh

deploy-frontend:
	@echo "🚀 Compiling React frontend and deploying to Firebase Hosting..."
	./deploy-frontend.sh

deploy-all: deploy-infra deploy-backend deploy-worker deploy-frontend
	@echo "🎉 Full GCP stack deployment complete!"

show-outputs:
	@./get-outputs.sh

logs:
	@echo "📋 Tailing chatbot-api Cloud Run logs..."
	gcloud run services logs read chatbot-api --region $(GCP_REGION) --project $(GCP_PROJECT_ID) --limit 50
	@echo ""
	@echo "📋 Tailing chatbot-worker Cloud Run logs..."
	gcloud run services logs read chatbot-worker --region $(GCP_REGION) --project $(GCP_PROJECT_ID) --limit 50

