variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }

resource "google_storage_bucket" "uploads" {
  name                        = "${var.project_id}-${var.name_prefix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  lifecycle_rule {
    action { type = "Delete" }
    condition {
      age            = 7
      matches_prefix = ["staging/", "rag-temp/"]
    }
  }
}

output "bucket_name" { value = google_storage_bucket.uploads.name }
