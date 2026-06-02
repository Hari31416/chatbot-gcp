locals {
  name_prefix = "chatbot-${var.environment}"
}

resource "google_project_service" "required" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "documentai.googleapis.com",
    "eventarc.googleapis.com",
    "firestore.googleapis.com",
    "iamcredentials.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "chatbot"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

module "storage" {
  source      = "./modules/storage"
  project_id  = var.project_id
  region      = var.region
  name_prefix = local.name_prefix
}

module "firestore" {
  source     = "./modules/firestore"
  project_id = var.project_id
  region     = var.region
}

module "secrets" {
  source     = "./modules/secrets"
  project_id = var.project_id
  secret_ids = ["litellm-api-key", "litellm-vision-api-key", "litellm-embedding-api-key"]
  
  depends_on = [google_project_service.required]
}

module "cloud_run" {
  source      = "./modules/cloud-run"
  project_id  = var.project_id
  region      = var.region
  api_image   = var.api_image
  bucket_name = module.storage.bucket_name
  secret_ids  = module.secrets.secret_ids

  depends_on = [google_project_service.required]
}

module "ingestion" {
  source       = "./modules/ingestion"
  project_id   = var.project_id
  region       = var.region
  bucket_name  = module.storage.bucket_name
  worker_image = var.worker_image
  secret_ids   = module.secrets.secret_ids

  depends_on = [google_project_service.required]
}

module "observability" {
  source                  = "./modules/observability"
  project_id              = var.project_id
  notification_channel_id = var.notification_channel_id
}

output "api_url" {
  value       = module.cloud_run.api_url
  description = "The URL of the deployed FastAPI API"
}

output "worker_url" {
  value       = module.ingestion.worker_url
  description = "The URL of the deployed ingestion worker"
}

output "bucket_name" {
  value       = module.storage.bucket_name
  description = "The name of the GCS bucket"
}

