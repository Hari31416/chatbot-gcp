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
        processor_name: str | None = None,
        max_pages: int = 25,
        max_chunks: int = 200,
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
        self.processor_name = processor_name
        self.max_pages = max_pages
        self.max_chunks = max_chunks

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
        from anyio import to_thread
        from uuid import uuid4
        from google.cloud import documentai

        if not self.storage:
            raise ValueError("Storage client must be configured to process binary documents")

        if not document_id:
            document_id = str(uuid4())

        # 1. Check local text file parsing
        if mime_type in ("text/plain", "text/markdown") or filename.lower().endswith((".txt", ".md")):
            logger.info("Processing plain text document locally: %s", filename)
            extracted_text = data.decode("utf-8", errors="ignore")
        else:
            if not self.doc_intelligence_client or not self.processor_name:
                raise ValueError("Document AI client and processor_name must be configured to process binary documents")

            # Upload raw binary to temporary staging container
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
                # 2. Analyze with GCP Document AI
                logger.info("Analyzing document with GCP Document AI for temp_key=%s", temp_key)
                
                def _call_doc_ai():
                    request = documentai.ProcessRequest(
                        name=self.processor_name,
                        raw_document=documentai.RawDocument(content=data, mime_type=mime_type)
                    )
                    return self.doc_intelligence_client.process_document(request=request)

                result = await to_thread.run_sync(_call_doc_ai)
                document = result.document

                # 3. Check page limit
                if document.pages and len(document.pages) > self.max_pages:
                    raise ValueError(f"Document exceeds {self.max_pages} page limit (got {len(document.pages)} pages)")

                # 4. Extract markdown content
                extracted_text = document.text or ""
                logger.info(
                    "Extracted %d chars from document=%s using Document AI",
                    len(extracted_text), filename,
                )

            finally:
                # 5. Clean up temporary staging blob
                try:
                    logger.info("Cleaning up staging blob: %s", temp_key)
                    await to_thread.run_sync(lambda: self.storage.delete_blob(temp_key))
                except Exception as e:
                    logger.warning("Failed to clean up staging blob %s: %s", temp_key, e)

        # 6. Split text and check chunk limits
        chunks = self.split_text(extracted_text)
        if not chunks:
            return RagIngestResult(document_id=document_id, chunks_ingested=0)

        if len(chunks) > self.max_chunks:
            raise ValueError(f"Document chunk count {len(chunks)} exceeds maximum limit of {self.max_chunks}")

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
