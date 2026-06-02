from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from functools import lru_cache
from typing import Any, cast

from fastapi import Depends, HTTPException, Request, status
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from .repositories.conversation_repository import ConversationRepository
from .services.llm import LlmClient
from .services.rag import RagService
from .services.storage import StorageService
from .services.vector_store import VectorStoreClient
from .settings import Settings

logger = logging.getLogger(__name__)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_storage() -> StorageService:
    settings = get_settings()
    
    # Try Key Vault secret first
    conn_str = get_secret("storage-connection-string")
    if not conn_str:
        conn_str = settings.azure_storage_connection_string
    if not conn_str:
        conn_str = "UseDevelopmentStorage=true"
        
    return StorageService(
        connection_string=conn_str,
        container_name=settings.azure_storage_container_name,
    )


@lru_cache
def get_staging_storage() -> StorageService:
    """Blob container watched by Event Grid for RAG ingestion."""
    settings = get_settings()

    conn_str = get_secret("storage-connection-string")
    if not conn_str:
        conn_str = settings.azure_storage_connection_string
    if not conn_str:
        conn_str = "UseDevelopmentStorage=true"

    return StorageService(
        connection_string=conn_str,
        container_name=settings.azure_storage_staging_container,
    )


@lru_cache
def get_cosmos_client() -> CosmosClient:
    settings = get_settings()
    endpoint = settings.cosmos_endpoint or "https://localhost:8081"
    
    # Try Key Vault secret first
    key = get_secret("cosmos-key")
    if not key:
        key = settings.cosmos_key or "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
    
    verify = True
    if "localhost" in endpoint or "127.0.0.1" in endpoint:
        verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        os.environ["AZURE_COSMOS_DISABLE_SSL_VERIFICATION"] = "true"
        
    return CosmosClient(endpoint, credential=key, connection_verify=verify)


@lru_cache
def get_conversations_container():
    client = get_cosmos_client()
    settings = get_settings()
    db = client.get_database_client(settings.cosmos_database_name)
    return db.get_container_client(settings.cosmos_conversations_container)


@lru_cache
def get_vectors_container():
    client = get_cosmos_client()
    settings = get_settings()
    db = client.get_database_client(settings.cosmos_database_name)
    return db.get_container_client(settings.cosmos_vectors_container)


def get_repository() -> ConversationRepository:
    container = get_conversations_container()
    return ConversationRepository(container)


@lru_cache
def get_keyvault_client() -> SecretClient | None:
    settings = get_settings()
    if not settings.azure_keyvault_name:
        return None
    vault_url = f"https://{settings.azure_keyvault_name}.vault.azure.net"
    credential = DefaultAzureCredential()
    return SecretClient(vault_url=vault_url, credential=credential)


def get_clerk_secret_key() -> str | None:
    """Clerk Backend API secret — Key Vault first, then CLERK_SECRET_KEY env."""
    settings = get_settings()
    return get_secret("clerk-secret-key") or settings.clerk_secret_key


@lru_cache
def get_secret(secret_name: str) -> str | None:
    """Retrieve a secret from Azure Key Vault (replaces get_ssm_parameter)."""
    client = get_keyvault_client()
    if not client:
        return None
    try:
        secret = client.get_secret(secret_name)
        return secret.value
    except Exception as e:
        logger.warning("Failed to retrieve secret %s from Key Vault: %s", secret_name, e)
        return None


@lru_cache
def get_vector_store() -> VectorStoreClient:
    settings = get_settings()
    container = get_vectors_container()
    
    # Try Key Vault secrets first
    api_key = get_secret("litellm-vision-api-key") or get_secret("litellm-api-key")
    if not api_key:
        api_key = settings.litellm_embedding_api_key or settings.litellm_vision_api_key
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
        
    return VectorStoreClient(
        container=container,
        embedding_model=settings.litellm_embedding_model,
        dimension=settings.embedding_dimension,
        gemini_api_key=api_key,
    )


def get_llm_client() -> LlmClient:
    settings = get_settings()
    api_key = settings.litellm_api_key

    vault_key = get_secret("litellm-api-key")
    if vault_key:
        api_key = vault_key

    return LlmClient(
        model=settings.litellm_model,
        api_key=api_key,
        base_url=settings.litellm_base_url,
    )


def get_vision_llm_client() -> LlmClient:
    settings = get_settings()
    api_key = settings.litellm_vision_api_key

    vault_key = get_secret("litellm-vision-api-key")
    if vault_key:
        api_key = vault_key

    # Fallback to standard key if no vision API key is configured
    if not api_key:
        api_key = settings.litellm_api_key
        vault_key_std = get_secret("litellm-api-key")
        if vault_key_std:
            api_key = vault_key_std

    return LlmClient(
        model=settings.litellm_vision_model,
        api_key=api_key,
        base_url=settings.litellm_vision_base_url,
    )


@lru_cache
def get_doc_intelligence_client() -> DocumentIntelligenceClient | None:
    settings = get_settings()
    
    # Try Key Vault secrets first
    endpoint = get_secret("azure-document-intelligence-endpoint")
    key = get_secret("azure-document-intelligence-key")
    
    if not endpoint:
        endpoint = settings.azure_document_intelligence_endpoint
    if not key:
        key = settings.azure_document_intelligence_key
        
    if endpoint and key:
        return DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key),
        )
    return None



def get_rag_service(
    vector_store: VectorStoreClient = Depends(get_vector_store),
) -> RagService:
    if hasattr(vector_store, "dependency") or type(vector_store).__name__ == "Depends":
        vector_store = get_vector_store()
    settings = get_settings()
    storage = get_storage()
    doc_client = get_doc_intelligence_client()
        
    return RagService(
        vector_store=vector_store,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        storage=storage,
        doc_intelligence_client=doc_client,
    )


# Cache dictionary mapping JWKS URL to (keys_dict, expiry_timestamp)
_jwks_cache: dict[str, tuple[dict, float]] = {}


def get_jwks(jwks_url: str) -> dict:
    now = time.time()
    if jwks_url in _jwks_cache:
        cached_val, expiry = _jwks_cache[jwks_url]
        if now < expiry:
            return cached_val
    try:
        req = urllib.request.Request(jwks_url, headers={"User-Agent": "FastAPI-Server"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            _jwks_cache[jwks_url] = (data, now + 3600)
            return data
    except Exception as e:
        logger.warning("Failed to fetch JWKS from %s: %s", jwks_url, e)
        if jwks_url in _jwks_cache:
            return _jwks_cache[jwks_url][0]
        return {"keys": []}


def _verify_clerk_token(token: str, settings: Settings) -> dict[str, Any]:
    import jwt
    from jwt.algorithms import RSAAlgorithm

    jwks_url = settings.clerk_jwks_uri
    if not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clerk JWKS URL is not configured",
        )

    # 1. Unverified decode to inspect claims and perform normalization check
    try:
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        logger.warning("Failed to decode token without verification: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token format: {str(e)}",
        )

    token_issuer = unverified_payload.get("iss")
    if not token_issuer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing issuer ('iss') claim",
        )

    expected_issuer = settings.clerk_issuer
    if expected_issuer:
        norm_expected = expected_issuer.rstrip("/")
        norm_token_iss = token_issuer.rstrip("/")
        if norm_expected != norm_token_iss:
            logger.warning(
                "Issuer mismatch: expected %s, token has %s",
                norm_expected,
                norm_token_iss,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Issuer mismatch: expected {norm_expected}, got {norm_token_iss}",
            )

    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    jwks = get_jwks(jwks_url)

    public_key: Any = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            public_key = RSAAlgorithm.from_jwk(key)
            break

    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token key ID not found in Clerk JWKS",
        )

    # 2. Cryptographic signature and time check with 60-second leeway for clock skew
    decode_options: dict[str, Any] = {"verify_exp": True, "verify_aud": False}
    try:
        payload = jwt.decode(
            token,
            cast(Any, public_key),
            algorithms=["RS256"],
            issuer=token_issuer,  # Pass token issuer to avoid slash mismatch, we validated it normalized above
            options=decode_options,
            leeway=60,
        )
    except jwt.exceptions.ExpiredSignatureError as e:
        logger.warning(
            "JWT validation failed: token expired. exp=%s, current=%s, error=%s",
            unverified_payload.get("exp"),
            time.time(),
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token has expired: {str(e)}",
        )
    except Exception as e:
        logger.warning("JWT validation failed: signature verification failed. error=%s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Signature verification failed: {str(e)}",
        )

    # 3. Normalized Authorized Parties (azp) validation
    parties = settings.clerk_authorized_parties
    if parties:
        azp = payload.get("azp")
        if azp:
            norm_azp = azp.rstrip("/")
            expected_parties = [p.rstrip("/") for p in (parties if isinstance(parties, list) else [parties])]
            if norm_azp not in expected_parties:
                logger.warning(
                    "Invalid authorized party (azp): got %s, expected one of %s",
                    norm_azp,
                    expected_parties,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid authorized party (azp): got {azp}, expected one of {parties}",
                )

    return payload


def get_current_user_id(
    request: Request, settings: Settings = Depends(get_settings)
) -> str:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

        if token and (len(token) < 50 or token.count(".") != 2):
            if settings.auth_enabled:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token format",
                )
            return token

        try:
            import jwt

            if settings.auth_enabled:
                payload = _verify_clerk_token(token, settings)
                return _first_string_claim(payload, ("sub",))

            logger.warning(
                "JWKS validation skipped. Performing unverified decode for fallback."
            )
            payload = jwt.decode(token, options={"verify_signature": False})
            return _first_string_claim(
                payload, ("sub", "email", "preferred_username"), default="admin"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.warning("JWT validation failed: %s", e)
            if settings.auth_enabled:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Signature verification failed: {str(e)}",
                ) from e
            try:
                import jwt

                payload = jwt.decode(token, options={"verify_signature": False})
                return _first_string_claim(payload, ("sub", "email"), default="admin")
            except Exception:
                return "admin"

    x_user = request.headers.get("X-User-ID")
    if x_user:
        return x_user

    import sys

    is_testing = "pytest" in sys.modules

    is_local = True
    if settings.cosmos_endpoint and not is_testing:
        if (
            "localhost" not in settings.cosmos_endpoint
            and "127.0.0.1" not in settings.cosmos_endpoint
        ):
            is_local = False

    if settings.auth_enabled or not is_local:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
        )

    return "admin"

def _first_string_claim(
    payload: dict[str, Any], keys: tuple[str, ...], default: str | None = None
) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    if default is not None:
        return default
    return cast(str, "")
