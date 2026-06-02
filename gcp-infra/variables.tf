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
