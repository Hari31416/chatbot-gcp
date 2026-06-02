variable "project_id" { type = string }
variable "region" { type = string }

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
}

resource "google_firestore_field" "conversation_id_index" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "conversations"
  field      = "conversation_id"

  index_config {
    indexes {
      order       = "ASCENDING"
      query_scope = "COLLECTION_GROUP"
    }
    indexes {
      order       = "DESCENDING"
      query_scope = "COLLECTION_GROUP"
    }
  }
}

resource "google_firestore_index" "rag_chunks_vector" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "rag_chunks"

  fields {
    field_path = "embedding"
    vector_config {
      dimension = 768
      flat {}
    }
  }
}


