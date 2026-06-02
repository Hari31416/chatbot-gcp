from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from anyio import to_thread
from google.cloud import firestore
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector
from litellm import embedding

logger = logging.getLogger(__name__)


class VectorStoreClient:
    def __init__(
        self,
        client: firestore.Client,
        embedding_model: str,
        dimension: int,
        gemini_api_key: str | None = None,
    ) -> None:
        self._client = client
        self.embedding_model = embedding_model
        self.dimension = dimension
        self.gemini_api_key = gemini_api_key
        logger.info(
            "VectorStoreClient initialized for Firestore model=%s dimension=%d",
            embedding_model,
            dimension,
        )

    def initialize_storage(self) -> None:
        """No-op for Firestore vector index (managed by manual gcloud command or console)."""
        logger.info("initialize_storage no-op called (handled by gcloud Firestore composite index)")

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
                "embedding": Vector(list(vector)),
            }
            
            doc_ref = (
                self._client.collection("users")
                .document(user_id)
                .collection("rag_chunks")
                .document(key)
            )
            await to_thread.run_sync(lambda: doc_ref.set(doc))

        logger.info("Ingested %d chunks into Firestore rag_chunks", len(keys))

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

        query_vector = Vector(query_embeddings[0])
        
        # Build Firestore query
        chunks_ref = (
            self._client.collection("users")
            .document(user_id)
            .collection("rag_chunks")
        )
        
        query = chunks_ref
        if documents:
            doc_list = [d for d in documents if d]
            if doc_list:
                # Firestore supports 'in' operator for up to 10/30 items
                query = query.where("sourceDoc", "in", doc_list)

        # Call find_nearest on Firestore query
        vector_query = query.find_nearest(
            vector_field="embedding",
            query_vector=query_vector,
            distance_measure=DistanceMeasure.COSINE,
            limit=top_k,
        )

        try:
            snapshots = await to_thread.run_sync(lambda: list(vector_query.get()))
        except Exception:
            logger.exception("Firestore native vector search query failed")
            raise

        results: list[dict[str, Any]] = []
        for snapshot in snapshots:
            item = snapshot.to_dict()
            # If distance is returned, use it to calculate score, otherwise default to 0.95
            distance = getattr(snapshot, "distance", None)
            score = 0.95
            if distance is not None:
                score = max(0.0, 1.0 - (float(distance) / 2.0))

            results.append(
                {
                    "key": snapshot.id,
                    "text": item.get("text", ""),
                    "source": item.get("sourceDoc") or item.get("source_doc") or "unknown",
                    "score": round(score, 4),
                }
            )
        return results
