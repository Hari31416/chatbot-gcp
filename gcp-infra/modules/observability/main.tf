variable "project_id" {
  type        = string
  description = "The GCP project ID"
}

variable "notification_channel_id" {
  type        = string
  default     = ""
  description = "Optional notification channel ID for alerts"
}

resource "google_monitoring_alert_policy" "api_errors" {
  display_name = "chatbot-api-HTTP-5xx"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run 5xx responses"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = var.notification_channel_id == "" ? [] : [var.notification_channel_id]
}
