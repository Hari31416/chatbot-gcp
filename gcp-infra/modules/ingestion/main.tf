variable "project_id" { type = string }
variable "region" { type = string }
variable "bucket_name" { type = string }
variable "worker_image" { type = string }
variable "secret_ids" { type = map(string) }
variable "additional_env_vars" {
  type    = map(string)
  default = {}
}

resource "google_pubsub_topic" "ingestion" {
  name    = "chatbot-ingestion"
  project = var.project_id
}

data "google_storage_project_service_account" "gcs" {
  project = var.project_id
}

resource "google_pubsub_topic_iam_member" "gcs_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.ingestion.id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

resource "google_storage_notification" "staging_finalize" {
  bucket             = var.bucket_name
  topic              = google_pubsub_topic.ingestion.id
  payload_format     = "JSON_API_V1"
  event_types        = ["OBJECT_FINALIZE"]
  object_name_prefix = "staging/"
  depends_on         = [google_pubsub_topic_iam_member.gcs_publisher]
}

resource "google_service_account" "worker" {
  account_id   = "chatbot-worker"
  display_name = "Chatbot Ingestion Worker"
  project      = var.project_id
}

resource "google_project_iam_member" "worker_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_storage_bucket_iam_member" "worker_storage" {
  bucket = var.bucket_name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.worker.email}"
}

# Grant Worker access to secrets if they exist
resource "google_project_iam_member" "worker_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_service_account" "eventarc_invoker" {
  account_id   = "chatbot-eventarc-invoker"
  display_name = "Eventarc Cloud Run invoker"
  project      = var.project_id
}

# Grant Eventarc invoker permissions to invoke Cloud Run
resource "google_project_iam_member" "eventarc_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.eventarc_invoker.email}"
}

resource "google_cloud_run_v2_service" "worker" {
  name                = "chatbot-worker"
  location            = var.region
  project             = var.project_id
  deletion_protection = false

  depends_on = [
    google_project_iam_member.worker_firestore,
    google_storage_bucket_iam_member.worker_storage,
    google_project_iam_member.worker_secrets,
  ]

  template {
    service_account = google_service_account.worker.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.worker_image
      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
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
        name  = "FIRESTORE_DATABASE"
        value = "(default)"
      }

      # Ingestion settings
      env {
        name  = "DOCUMENT_AI_LOCATION"
        value = "us"
      }
      env {
        name  = "DOCUMENT_AI_PROCESSOR_ID"
        value = ""
      }
      env {
        name  = "DOCUMENT_AI_USE_LAYOUT_PARSER"
        value = "false"
      }
      env {
        name  = "MAX_RAG_PAGES"
        value = "25"
      }
      env {
        name  = "MAX_RAG_CHUNKS"
        value = "200"
      }

      # LLM keys (injected from Secret Manager at run time)
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

      # Additional environment variables dynamically loaded from variables
      dynamic "env" {
        for_each = var.additional_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "eventarc_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.worker.location
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.eventarc_invoker.email}"
}

resource "google_eventarc_trigger" "ingestion" {
  name     = "chatbot-ingestion"
  location = var.region
  project  = var.project_id

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.pubsub.topic.v1.messagePublished"
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.worker.name
      region  = var.region
    }
  }

  transport {
    pubsub {
      topic = google_pubsub_topic.ingestion.id
    }
  }

  service_account = google_service_account.eventarc_invoker.email
}

output "worker_url" {
  value = google_cloud_run_v2_service.worker.uri
}
