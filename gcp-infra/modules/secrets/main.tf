variable "project_id" {
  type        = string
  description = "The GCP project ID"
}

variable "secret_ids" {
  type        = set(string)
  description = "Set of Secret Manager secret IDs to manage"
}

resource "google_secret_manager_secret" "app" {
  for_each  = var.secret_ids
  secret_id = each.value
  project   = var.project_id

  replication {
    auto {}
  }
}

output "secret_ids" {
  value = { for key, secret in google_secret_manager_secret.app : key => secret.secret_id }
}
