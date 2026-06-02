from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Google Cloud Settings ──
    gcp_project_id: str | None = Field(default=None, validation_alias="GCP_PROJECT_ID")
    gcp_region: str = Field(default="asia-south1", validation_alias="GCP_REGION")

    # ── Google Cloud Storage Settings ──
    gcs_bucket_name: str | None = Field(default=None, validation_alias="GCS_BUCKET_NAME")
    gcs_uploads_prefix: str = Field(default="uploads", validation_alias="GCS_UPLOADS_PREFIX")
    gcs_staging_prefix: str = Field(default="staging", validation_alias="GCS_STAGING_PREFIX")
    gcs_rag_temp_prefix: str = Field(default="rag-temp", validation_alias="GCS_RAG_TEMP_PREFIX")
    gcs_signing_service_account: str | None = Field(
        default=None, validation_alias="GCS_SIGNING_SERVICE_ACCOUNT"
    )

    # ── Firestore Settings ──
    firestore_database: str = Field(default="(default)", validation_alias="FIRESTORE_DATABASE")

    # ── Firebase Auth Settings ──
    firebase_project_id: str | None = Field(default=None, validation_alias="FIREBASE_PROJECT_ID")
    firebase_auth_emulator_host: str | None = Field(
        default=None, validation_alias="FIREBASE_AUTH_EMULATOR_HOST"
    )

    # ── Document AI Settings ──
    document_ai_location: str = Field(default="us", validation_alias="DOCUMENT_AI_LOCATION")
    document_ai_processor_id: str | None = Field(default=None, validation_alias="DOCUMENT_AI_PROCESSOR_ID")
    document_ai_use_layout_parser: bool = Field(default=False, validation_alias="DOCUMENT_AI_USE_LAYOUT_PARSER")
    max_rag_pages: int = Field(default=25, validation_alias="MAX_RAG_PAGES")
    max_rag_chunks: int = Field(default=200, validation_alias="MAX_RAG_CHUNKS")

    # ── General Settings ──
    context_ttl_seconds: int = Field(
        default=3600, validation_alias="CONTEXT_TTL_SECONDS"
    )
    max_image_bytes: int = Field(
        default=5 * 1024 * 1024, validation_alias="MAX_IMAGE_BYTES"
    )
    allowed_image_mime_types: list[str] | str = Field(
        default_factory=lambda: ["image/png", "image/jpeg", "image/webp"],
        validation_alias="ALLOWED_IMAGE_MIME_TYPES",
    )
    max_history_messages: int = Field(
        default=10, validation_alias="MAX_HISTORY_MESSAGES"
    )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.firebase_project_id)

    # ── LiteLLM & RAG Settings ──
    litellm_model: str = Field(default="gpt-4o-mini", validation_alias="LITELLM_MODEL")
    litellm_api_key: str | None = Field(
        default=None, validation_alias="LITELLM_API_KEY"
    )
    litellm_base_url: str | None = Field(
        default=None, validation_alias="LITELLM_BASE_URL"
    )

    litellm_vision_model: str = Field(
        default="gemini/gemini-3.1-flash-lite", validation_alias="LITELLM_VISION_MODEL"
    )
    litellm_vision_api_key: str | None = Field(
        default=None, validation_alias="LITELLM_VISION_API_KEY"
    )
    litellm_vision_base_url: str | None = Field(
        default=None, validation_alias="LITELLM_VISION_BASE_URL"
    )

    litellm_embedding_model: str = Field(
        default="gemini/gemini-embedding-2",
        validation_alias="LITELLM_EMBEDDING_MODEL",
    )
    litellm_embedding_api_key: str | None = Field(
        default=None, validation_alias="LITELLM_EMBEDDING_API_KEY"
    )
    embedding_dimension: int = Field(
        default=768, validation_alias="EMBEDDING_DIMENSION"
    )
    rag_top_k: int = Field(default=3, validation_alias="RAG_TOP_K")
    rag_chunk_size: int = Field(default=800, validation_alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(default=80, validation_alias="RAG_CHUNK_OVERLAP")

    @field_validator("allowed_image_mime_types", mode="before")
    @classmethod
    def _parse_mime_types(cls, value: object) -> list[str] | object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
