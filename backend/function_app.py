import asyncio
import json
import logging
import os
import azure.functions as func

app = func.FunctionApp()

logger = logging.getLogger(__name__)

# Configure root logger to output to stdout
if not logger.handlers:
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)


@app.queue_trigger(
    arg_name="msg",
    queue_name="ingestion-queue",
    connection="AzureWebJobsStorage",
)
def process_ingestion(msg: func.QueueMessage) -> None:
    """
    Triggered by Azure Storage Queue messages from Blob Storage Event Grid.
    Message payload contains the blob event with subject = blob path.
    """
    body = msg.get_body().decode("utf-8")
    logger.info("Received ingestion message: %s", body)

    try:
        event = json.loads(body)
    except Exception:
        logger.exception("Failed to parse message body")
        return

    # Event Grid schema: subject = /blobServices/default/containers/staging/blobs/{path}
    subject = event.get("subject", "")
    blob_url = event.get("data", {}).get("url", "")

    # Extract: staging/{user_id}/{document_id}/{filename}
    # The subject path is: /blobServices/default/containers/staging/blobs/{user_id}/{document_id}/{filename}
    blob_path = subject.split("/blobs/", 1)[-1] if "/blobs/" in subject else ""
    parts = blob_path.split("/")

    if len(parts) < 3:
        logger.warning("Unexpected blob path format: %s", blob_path)
        return

    user_id = parts[0]
    document_id = parts[1]
    filename = "/".join(parts[2:])

    logger.info(
        "Processing blob: user_id=%s, document_id=%s, filename=%s",
        user_id, document_id, filename,
    )

    # Run the async ingestion pipeline
    asyncio.run(process_staging_file(user_id, document_id, filename))


async def process_staging_file(user_id: str, document_id: str, filename: str) -> None:
    """
    Reimplementation of the Lambda worker's process_staging_file,
    using Azure services (Blob Storage, Document Intelligence, Cosmos DB).
    """
    # Import app dependencies (initialized with Azure env vars)
    from app.dependencies import get_repository, get_rag_service, get_staging_storage
    from app.utils.time import utcnow_iso
    from anyio import to_thread

    repo = get_repository()
    storage = get_staging_storage()

    try:
        # 1. Download from staging container
        staging_key = f"{user_id}/{document_id}/{filename}"
        data, content_type = await to_thread.run_sync(
            lambda: storage.download_bytes(staging_key)
        )

        # 2. Determine binary vs text
        ext = os.path.splitext(filename.lower())[1] or ""
        is_binary = ext in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif")

        # 3. Run RAG ingestion
        rag_service = get_rag_service()

        if is_binary:
            result = await rag_service.ingest_binary_document(
                filename=filename, data=data, mime_type=content_type,
                user_id=user_id, document_id=document_id,
            )
        else:
            try:
                content = data.decode("utf-8")
                result = await rag_service.ingest_document(
                    filename=filename, content=content,
                    user_id=user_id, document_id=document_id,
                )
            except UnicodeDecodeError:
                result = await rag_service.ingest_binary_document(
                    filename=filename, data=data, mime_type=content_type,
                    user_id=user_id, document_id=document_id,
                )

        # 4. Update status
        updated_at = utcnow_iso()
        await to_thread.run_sync(
            lambda: repo.update_rag_document_status(
                user_id, document_id, "ready", result.chunks_ingested, updated_at
            )
        )
        logger.info("Ingested document_id=%s, chunks=%d", document_id, result.chunks_ingested)

    except Exception:
        logger.exception("Failed ingestion for document_id=%s", document_id)
        try:
            updated_at = utcnow_iso()
            await to_thread.run_sync(
                lambda: repo.update_rag_document_status(user_id, document_id, "failed", 0, updated_at)
            )
        except Exception:
            logger.exception("Failed to write failure status for document_id=%s", document_id)

    finally:
        # 5. Clean up staging blob
        try:
            staging_key = f"{user_id}/{document_id}/{filename}"
            await to_thread.run_sync(lambda: storage.delete_blob(staging_key))
            logger.info("Cleaned up staging blob: %s", staging_key)
        except Exception:
            logger.exception("Failed to clean up staging blob")
