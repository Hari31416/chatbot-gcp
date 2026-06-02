from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )



    # ── Azure Blob Storage Settings ──
    azure_storage_connection_string: str | None = Field(
        default=None, validation_alias="AZURE_STORAGE_CONNECTION_STRING"
    )
    azure_storage_account_name: str | None = Field(
        default=None, validation_alias="AZURE_STORAGE_ACCOUNT_NAME"
    )
    azure_storage_container_name: str = Field(
        default="uploads", validation_alias="AZURE_STORAGE_CONTAINER_NAME"
    )
    azure_storage_staging_container: str = Field(
        default="staging", validation_alias="AZURE_STORAGE_STAGING_CONTAINER"
    )
    azure_storage_rag_temp_container: str = Field(
        default="rag-temp", validation_alias="AZURE_STORAGE_RAG_TEMP_CONTAINER"
    )

    # ── Azure Cosmos DB Settings ──
    cosmos_endpoint: str | None = Field(
        default=None, validation_alias="COSMOS_ENDPOINT"
    )
    cosmos_key: str | None = Field(
        default=None, validation_alias="COSMOS_KEY"
    )
    cosmos_database_name: str = Field(
        default="chatbot", validation_alias="COSMOS_DATABASE_NAME"
    )
    cosmos_conversations_container: str = Field(
        default="conversations", validation_alias="COSMOS_CONTAINER_NAME"
    )
    cosmos_vectors_container: str = Field(
        default="vectors", validation_alias="COSMOS_VECTORS_CONTAINER_NAME"
    )

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



    # ── Clerk Auth ──
    clerk_issuer: str | None = Field(default=None, validation_alias="CLERK_ISSUER")
    clerk_jwks_url: str | None = Field(
        default=None, validation_alias="CLERK_JWKS_URL"
    )
    clerk_authorized_parties: list[str] | str = Field(
        default_factory=list,
        validation_alias="CLERK_AUTHORIZED_PARTIES",
    )
    # Prefer Key Vault secret `clerk-secret-key`; env var is local bootstrap only
    clerk_secret_key: str | None = Field(
        default=None, validation_alias="CLERK_SECRET_KEY"
    )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.clerk_issuer)

    @property
    def clerk_jwks_uri(self) -> str | None:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        if self.clerk_issuer:
            return f"{self.clerk_issuer.rstrip('/')}/.well-known/jwks.json"
        return None

    # ── Storage Queue & Document Intelligence (Phase 5) ──
    azure_ingestion_queue_name: str = Field(
        default="ingestion-queue", validation_alias="AZURE_INGESTION_QUEUE_NAME"
    )
    azure_document_intelligence_endpoint: str | None = Field(
        default=None, validation_alias="AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"
    )
    azure_document_intelligence_key: str | None = Field(
        default=None, validation_alias="AZURE_DOCUMENT_INTELLIGENCE_KEY"
    )

    # ── Azure Key Vault (Phase 6) ──
    azure_keyvault_name: str | None = Field(
        default=None, validation_alias="AZURE_KEYVAULT_NAME"
    )

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

    @field_validator("clerk_authorized_parties", mode="before")
    @classmethod
    def _parse_authorized_parties(cls, value: object) -> list[str] | object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
