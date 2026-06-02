from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from anyio import to_thread
from litellm import embedding

logger = logging.getLogger(__name__)


class VectorStoreClient:
    def __init__(
        self,
        container: Any,
        embedding_model: str,
        dimension: int,
        gemini_api_key: str | None = None,
    ) -> None:
        self._container = container
        self.embedding_model = embedding_model
        self.dimension = dimension
        self.gemini_api_key = gemini_api_key
        logger.info(
            "VectorStoreClient initialized for Cosmos DB DB model=%s dimension=%d",
            embedding_model,
            dimension,
        )

    def initialize_storage(self) -> None:
        """No-op for Cosmos DB as containers and indexing policies are handled by Bicep."""
        logger.info("initialize_storage no-op called (handled by Azure Bicep)")

    async def get_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        cleaned = [text for text in texts if text]
        if not cleaned:
            return []

        def embed_texts() -> Any:
            return embedding(
                model=self.embedding_model,
                input=cleaned,
                api_key=self.gemini_api_key,
                dimensions=self.dimension,
            )

        try:
            response = await to_thread.run_sync(embed_texts)
        except Exception:
            logger.exception("Failed to generate embeddings")
            raise

        vectors = [item["embedding"] for item in response["data"]]
        for vector in vectors:
            if len(vector) != self.dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {self.dimension}, "
                    f"got {len(vector)}"
                )
        return vectors

    async def upsert_chunks(
        self,
        keys: Sequence[str],
        texts: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        source_doc: str,
        document_id: str,
        user_id: str,
    ) -> None:
        if not (len(keys) == len(texts) == len(embeddings)):
            raise ValueError("keys, texts, and embeddings must have matching lengths")

        for idx, (key, text, vector) in enumerate(zip(keys, texts, embeddings)):
            doc = {
                "id": key,
                "userId": user_id,
                "user_id": user_id,  # Keep both for safety
                "documentId": document_id,
                "document_id": document_id,  # Keep both for safety
                "sourceDoc": source_doc,
                "source_doc": source_doc,  # Keep both for safety
                "chunkIdx": idx,
                "chunk_idx": idx,  # Keep both for safety
                "text": text,
                "embedding": list(vector),
            }
            
            await to_thread.run_sync(
                lambda: self._container.upsert_item(body=doc)
            )

        logger.info("Ingested %d chunks into Cosmos DB vectors container", len(keys))

    async def similarity_search(
        self,
        query_text: str,
        user_id: str,
        top_k: int = 3,
        documents: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        query_embeddings = await self.get_embeddings([query_text])
        if not query_embeddings:
            return []

        # Convert query embedding vector to a string representation for VectorDistance
        vector_str = str(list(query_embeddings[0]))
        
        # Build query filters
        # Note: Bicep partition key is /userId. We must specify enable_cross_partition_query
        # but filtering by userId inside the query leverages indices.
        filter_clause = "c.userId = @userId"
        params = [{"name": "@userId", "value": user_id}]

        if documents:
            doc_list = [d for d in documents if d]
            if doc_list:
                placeholders = ", ".join(f"@doc{i}" for i in range(len(doc_list)))
                filter_clause += f" AND c.sourceDoc IN ({placeholders})"
                for i, doc in enumerate(doc_list):
                    params.append({"name": f"@doc{i}", "value": doc})

        # Query using native VectorDistance NoSQL function
        query = f"""
        SELECT TOP @topK
            c.id, c.text, c.sourceDoc, c.documentId,
            VectorDistance(c.embedding, {vector_str}) AS distance
        FROM c
        WHERE {filter_clause}
        ORDER BY VectorDistance(c.embedding, {vector_str})
        """
        params.append({"name": "@topK", "value": top_k})

        try:
            items = await to_thread.run_sync(
                lambda: list(self._container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                ))
            )
        except Exception:
            logger.exception("Cosmos DB native vector search query failed")
            raise

        results: list[dict[str, Any]] = []
        for item in items:
            distance = item.get("distance")
            # Distance is between 0 and 2 for Cosine Distance in Cosmos DB.
            # Convert to similarity score between 0 and 1: similarity = 1 - (distance / 2)
            score = 1.0
            if distance is not None:
                score = max(0.0, 1.0 - (float(distance) / 2.0))
                
            results.append(
                {
                    "key": item.get("id"),
                    "text": item.get("text", ""),
                    "source": item.get("sourceDoc") or item.get("source_doc") or "unknown",
                    "score": round(score, 4),
                }
            )
        return results
