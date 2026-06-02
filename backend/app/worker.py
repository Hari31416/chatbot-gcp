from __future__ import annotations

import base64
import json
import logging
from typing import Any

from anyio import to_thread
from cloudevents.http import from_http
from fastapi import FastAPI, HTTPException, Request, status

from .dependencies import (
    get_rag_service,
    get_repository,
    get_staging_storage,
)
from .utils.time import utcnow_iso

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Chatbot RAG Ingestion Worker",
    description="Asynchronously parses, chunks, and embeds uploaded documents into Firestore Native vectors",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/")
async def handle_pubsub(request: Request) -> dict[str, str]:
    """Receives GCS OBJECT_FINALIZE events from Pub/Sub via Eventarc,
    downloads the file, runs RAG ingestion, and cleanups staging.
    """
    try:
        # Parse CloudEvent headers and body
        body_bytes = await request.body()
        headers = dict(request.headers)
        event = from_http(headers, body_bytes)
    except Exception as exc:
        logger.error("Failed to parse CloudEvent from request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CloudEvent structure",
        ) from exc

    # Retrieve Pub/Sub message body
    message = event.data.get("message")
    if not isinstance(message, dict) or "data" not in message:
        logger.error("Eventarc event does not contain Pub/Sub message or data field")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing message data field in Pub/Sub body",
        )

    # Base64 decode GCS object metadata
    try:
        raw_data = base64.b64decode(message["data"]).decode("utf-8")
        notification = json.loads(raw_data)
    except Exception as exc:
        logger.error("Failed to decode or parse base64 notification payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload in Pub/Sub data",
        ) from exc

    object_name = str(notification.get("name", ""))
    logger.info("Received Eventarc push notification for object_name=%s", object_name)

    # Ignore objects outside staging/ prefix
    if not object_name.startswith("staging/"):
        logger.info("Ignoring GCS object change outside staging prefix: %s", object_name)
        return {"status": "ignored", "reason": "outside_staging"}

    # Extract staging structure: staging/{user_id}/{document_id}/{filename}
    parts = object_name.split("/")
    if len(parts) < 4:
        logger.warning("Object name staging path is malformed: %s", object_name)
        return {"status": "ignored", "reason": "malformed_path"}

    user_id = parts[1]
    document_id = parts[2]
    filename = "/".join(parts[3:])

    # download_key is user_id/document_id/filename because get_staging_storage() automatically prepends settings.gcs_staging_prefix ("staging/")
    download_key = f"{user_id}/{document_id}/{filename}"

    # Resolve dependencies directly
    staging_storage = get_staging_storage()
    rag_service = get_rag_service()
    repo = get_repository()

    try:
        # Download document bytes and mime-type
        logger.info("Downloading file user_id=%s doc_id=%s file=%s", user_id, document_id, filename)
        file_bytes, content_type = await to_thread.run_sync(
            staging_storage.download_bytes, download_key
        )

        # Ingest document chunks, generate embeddings, and upsert vectors
        logger.info("Processing ingestion worker-side for file=%s user_id=%s", filename, user_id)
        result = await rag_service.ingest_binary_document(
            filename=filename,
            data=file_bytes,
            mime_type=content_type,
            user_id=user_id,
            document_id=document_id,
        )

        # Clean up GCS staging bucket object
        logger.info("Ingestion completed successfully. Cleaning up GCS staging key=%s", download_key)
        await to_thread.run_sync(staging_storage.delete_blob, download_key)

        # Mark document as ready in Firestore
        await to_thread.run_sync(
            repo.update_rag_document_status,
            user_id,
            document_id,
            "ready",
            result.chunks_ingested,
            utcnow_iso(),
        )

        return {"status": "success", "document_id": document_id}

    except Exception as exc:
        logger.exception("Error processing document ingestion user_id=%s document_id=%s", user_id, document_id)

        # Classify failures to handle retries properly
        # Standard validation errors (e.g. file too big, too many pages, un-parsable structure) are terminal
        err_msg = str(exc)
        is_terminal = (
            "exceeds" in err_msg.lower()
            or "limit" in err_msg.lower()
            or "invalid" in err_msg.lower()
            or "unsupported" in err_msg.lower()
            or "valueerror" in err_msg.lower()
            or isinstance(exc, ValueError)
        )

        if is_terminal:
            logger.warning("Terminal ingestion failure encountered. Rejecting message to stop retries.")
            # 1. Update document status to failed in Firestore
            try:
                await to_thread.run_sync(
                    repo.update_rag_document_status,
                    user_id,
                    document_id,
                    "failed",
                    0,
                    utcnow_iso(),
                )
            except Exception as e:
                logger.error("Failed to write failure status to Firestore: %s", e)

            # 2. Delete staging object so we don't leak it
            try:
                await to_thread.run_sync(staging_storage.delete_blob, download_key)
            except Exception as e:
                logger.error("Failed to delete staging blob %s on failure: %s", download_key, e)

            # Return 200 OK so Pub/Sub does NOT retry a terminally failed document
            return {"status": "failed_terminal", "reason": err_msg}

        else:
            # Transient failure (e.g. network timeout, rate limit)
            # Return HTTP 500 so Pub/Sub/Eventarc retries the event
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Transient failure occurred: {err_msg}",
            ) from exc
