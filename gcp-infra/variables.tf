variable "project_id" {
  type        = string
  description = "The GCP project ID to deploy resources in"
}

variable "region" {
  type        = string
  default     = "asia-south1"
  description = "The GCP region for resources (Mumbai by default)"
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "The deployment environment (e.g. dev, prod)"
}

variable "firebase_web_app_id" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Optional Firebase Web App ID if already created"
}

variable "api_image" {
  type        = string
  default     = "gcr.io/cloudrun/hello"
  description = "The docker image URL for the FastAPI chatbot API"
}

variable "worker_image" {
  type        = string
  default     = "gcr.io/cloudrun/hello"
  description = "The docker image URL for the ingestion worker"
}

variable "notification_channel_id" {
  type        = string
  default     = ""
  description = "Optional notification channel ID for alerts"
}
