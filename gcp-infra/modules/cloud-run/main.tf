variable "project_id" { type = string }
variable "region" { type = string }
variable "api_image" { type = string }
variable "bucket_name" { type = string }
variable "secret_ids" { type = map(string) }

resource "google_service_account" "api" {
  account_id   = "chatbot-api"
  display_name = "Chatbot API Service Account"
  project      = var.project_id
}

resource "google_service_account_iam_member" "api_can_sign_as_self" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "api_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_storage_bucket_iam_member" "api_storage" {
  bucket = var.bucket_name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "api_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name     = "chatbot-api"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.api.email
    timeout         = "300s"

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.api_image
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = var.bucket_name
      }
      env {
        name  = "GCS_SIGNING_SERVICE_ACCOUNT"
        value = google_service_account.api.email
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = "(default)"
      }

      # Set up Firebase settings (auth is enabled dynamically by presence of project id)
      env {
        name  = "FIREBASE_PROJECT_ID"
        value = var.project_id
      }

      # Mount secrets dynamically from Secret Manager
      dynamic "env" {
        for_each = var.secret_ids
        content {
          name = upper(replace(env.key, "-", "_"))
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "api_service_account" {
  value = google_service_account.api.email
}
