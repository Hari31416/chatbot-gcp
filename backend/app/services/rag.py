from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .vector_store import VectorStoreClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RagIngestResult:
    document_id: str
    chunks_ingested: int


class RagService:
    def __init__(
        self,
        vector_store: VectorStoreClient,
        chunk_size: int = 800,
        chunk_overlap: int = 80,
        storage: Any = None,
        doc_intelligence_client: Any = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.vector_store = vector_store
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.storage = storage
        self.doc_intelligence_client = doc_intelligence_client

    async def ingest_document(
        self, filename: str, content: str, user_id: str, document_id: str | None = None
    ) -> RagIngestResult:
        chunks = self.split_text(content)
        if not document_id:
            document_id = str(uuid4())
        if not chunks:
            return RagIngestResult(document_id=document_id, chunks_ingested=0)

        embeddings = await self.vector_store.get_embeddings(chunks)
        keys = [f"{document_id}-chunk-{idx}" for idx in range(len(chunks))]
        await self.vector_store.upsert_chunks(
            keys=keys,
            texts=chunks,
            embeddings=embeddings,
            source_doc=filename,
            document_id=document_id,
            user_id=user_id,
        )
        return RagIngestResult(
            document_id=document_id,
            chunks_ingested=len(chunks),
        )

    async def ingest_binary_document(
        self, filename: str, data: bytes, mime_type: str, user_id: str, document_id: str | None = None
    ) -> RagIngestResult:
        import os
        from anyio import to_thread
        from uuid import uuid4

        if not self.storage:
            raise ValueError("Storage client must be configured to process binary documents")
        if not self.doc_intelligence_client:
            raise ValueError("Document Intelligence client must be configured to process binary documents")

        if not document_id:
            document_id = str(uuid4())

        # 1. Upload raw binary to temporary staging container
        temp_key = f"rag-temp/{user_id}/{document_id}/{filename}"
        logger.info("Uploading raw binary document filename=%s user_id=%s temp_key=%s", filename, user_id, temp_key)
        await to_thread.run_sync(
            lambda: self.storage.upload_bytes(
                key=temp_key,
                data=data,
                mime_type=mime_type,
            )
        )

        try:
            # 2. Analyze with Document Intelligence (prebuilt-layout model)
            logger.info("Analyzing document with Azure AI Document Intelligence for temp_key=%s", temp_key)
            
            poller = await to_thread.run_sync(
                lambda: self.doc_intelligence_client.begin_analyze_document(
                    "prebuilt-layout",
                    data,
                    content_type=mime_type,
                    output_content_format="markdown",
                )
            )
            result = await to_thread.run_sync(poller.result)

            # 3. Extract markdown content
            extracted_text = result.content or ""
            logger.info(
                "Extracted %d chars from document=%s using Document Intelligence",
                len(extracted_text), filename,
            )

            # 4. Check page limit
            if result.pages and len(result.pages) > 100:
                raise ValueError(f"Document exceeds 100 page limit (got {len(result.pages)} pages)")

        finally:
            # 5. Clean up temporary staging blob
            try:
                logger.info("Cleaning up staging blob: %s", temp_key)
                await to_thread.run_sync(lambda: self.storage.delete_blob(temp_key))
            except Exception as e:
                logger.warning("Failed to clean up staging blob %s: %s", temp_key, e)

        # 6. Split text and upsert to vector store
        chunks = self.split_text(extracted_text)
        if not chunks:
            return RagIngestResult(document_id=document_id, chunks_ingested=0)

        embeddings = await self.vector_store.get_embeddings(chunks)
        keys = [f"{document_id}-chunk-{idx}" for idx in range(len(chunks))]
        await self.vector_store.upsert_chunks(
            keys=keys,
            texts=chunks,
            embeddings=embeddings,
            source_doc=filename,
            document_id=document_id,
            user_id=user_id,
        )
        return RagIngestResult(
            document_id=document_id,
            chunks_ingested=len(chunks),
        )

    def split_text(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        if len(normalized) <= self.chunk_size:
            return [normalized]

        chunks: list[str] = []
        step = self.chunk_size - self.chunk_overlap
        start = 0
        while start < len(normalized):
            end = min(start + self.chunk_size, len(normalized))
            chunks.append(normalized[start:end].strip())
            if end == len(normalized):
                break
            start += step
        return [chunk for chunk in chunks if chunk]
