from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.services.rag import RagService


class NoopVectorStore:
    pass


def test_rag_split_text_uses_overlap() -> None:
    service = RagService(NoopVectorStore(), chunk_size=10, chunk_overlap=2)  # type: ignore[arg-type]
    chunks = service.split_text("abcdefghijklmnopqrstuvwxyz")

    assert chunks == ["abcdefghij", "ijklmnopqr", "qrstuvwxyz"]


def test_rag_ingest_endpoint(test_client: TestClient) -> None:
    response = test_client.post(
        "/rag/ingest",
        json={
            "filename": "company_rules.txt",
            "content": "The secure Wi-Fi password is AntigravityRAG2026.",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["filename"] == "company_rules.txt"
    assert payload["document_id"]
    assert payload["chunks_ingested"] == 0


def test_rag_documents_endpoint_lists_ingested_items(test_client: TestClient) -> None:
    ingest_response = test_client.post(
        "/rag/ingest",
        json={
            "filename": "company_rules.txt",
            "content": "The secure Wi-Fi password is AntigravityRAG2026.",
        },
    )
    assert ingest_response.status_code == 202
    doc_id = ingest_response.json()["document_id"]

    response = test_client.get("/rag/documents")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["document_id"] == doc_id
    assert payload[0]["filename"] == "company_rules.txt"
    assert payload[0]["source_doc"] == "company_rules.txt"
    assert payload[0]["chunks_ingested"] == 0
    assert payload[0]["status"] == "processing"
    assert payload[0]["created_at"]
    assert payload[0]["updated_at"]


def test_rag_search_endpoint(test_client: TestClient) -> None:
    response = test_client.post(
        "/rag/search",
        json={"query": "What is the Wi-Fi password?", "top_k": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "What is the Wi-Fi password?"
    assert payload["results"][0]["source"] == "company_rules.txt"


def test_chat_with_rag_injects_retrieved_context(test_client: TestClient) -> None:
    response = test_client.post(
        "/chat",
        json={
            "message": "What is the Wi-Fi password?",
            "use_rag": True,
            "rag_documents": ["company_rules.txt"],
        },
    )

    assert response.status_code == 200
    llm_messages = getattr(test_client, "fake_llm").messages[-1]
    assert llm_messages[0]["role"] == "system"
    assert "AntigravityRAG2026" in llm_messages[0]["content"]
    assert "company_rules.txt" in llm_messages[0]["content"]
    assert getattr(test_client, "fake_vector_store").search_calls[-1] == {
        "query_text": "What is the Wi-Fi password?",
        "user_id": "admin",
        "top_k": 3,
        "documents": ["company_rules.txt"],
    }


def test_rag_file_ingest_text_file(test_client: TestClient) -> None:
    response = test_client.post(
        "/rag/ingest/file",
        files={"file": ("test.txt", b"plain text content", "text/plain")}
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["filename"] == "test.txt"
    assert payload["chunks_ingested"] == 0


def test_rag_file_ingest_binary_file(test_client: TestClient) -> None:
    response = test_client.post(
        "/rag/ingest/file",
        files={"file": ("test.pdf", b"%PDF-1.4 dummy", "application/pdf")}
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["filename"] == "test.pdf"
    assert payload["chunks_ingested"] == 0


def test_rag_file_ingest_too_large(test_client: TestClient) -> None:
    large_data = b"x" * (20 * 1024 * 1024 + 100)
    response = test_client.post(
        "/rag/ingest/file",
        files={"file": ("big.pdf", large_data, "application/pdf")}
    )
    assert response.status_code == 413


class MockVectorStore:
    def __init__(self):
        self.upserts = []

    async def get_embeddings(self, texts):
        return [[0.1] * 768 for _ in range(len(texts))]

    async def upsert_chunks(self, keys, texts, embeddings, source_doc, document_id, user_id):
        self.upserts.append({
            "keys": keys,
            "texts": texts,
            "embeddings": embeddings,
            "source_doc": source_doc,
            "document_id": document_id,
            "user_id": user_id
        })


class MockStorage:
    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def upload_bytes(self, key, data, mime_type):
        self.uploaded.append({"key": key, "data": data, "mime_type": mime_type})

    def delete_blob(self, key):
        self.deleted.append(key)


class MockDocument:
    def __init__(self, text: str, pages_count: int):
        self.text = text
        self.pages = [object() for _ in range(pages_count)]


class MockProcessResponse:
    def __init__(self, text: str, pages_count: int):
        self.document = MockDocument(text, pages_count)


class MockDocumentAiClient:
    def __init__(self, pages: int = 5, fail: bool = False):
        self.pages = pages
        self.fail = fail
        self.process_calls: list[Any] = []

    def process_document(self, request: Any) -> MockProcessResponse:
        self.process_calls.append(request)
        if self.fail:
            raise ValueError("Document AI error test")
        return MockProcessResponse("Markdown text content from Document Intelligence", self.pages)


@pytest.mark.asyncio
async def test_rag_service_ingest_binary_document_logic() -> None:
    vector_store = MockVectorStore()
    storage = MockStorage()
    doc_client = MockDocumentAiClient(pages=5)
    
    service = RagService(
        vector_store=vector_store,  # type: ignore[arg-type]
        chunk_size=100,
        chunk_overlap=10,
        storage=storage,
        doc_intelligence_client=doc_client,
        processor_name="projects/test-proj/locations/us/processors/test-proc",
        max_pages=25,
        max_chunks=200,
    )
    
    result = await service.ingest_binary_document(
        filename="report.pdf",
        data=b"pdf binary data",
        mime_type="application/pdf",
        user_id="user-123"
    )
    
    assert result.chunks_ingested == 1
    assert len(storage.uploaded) == 1
    assert storage.uploaded[0]["data"] == b"pdf binary data"
    assert storage.uploaded[0]["mime_type"] == "application/pdf"
    
    # Assert cleanup was called
    assert len(storage.deleted) == 1
    assert storage.deleted[0] == storage.uploaded[0]["key"]
    
    # Assert Document AI was triggered
    assert len(doc_client.process_calls) == 1
    assert doc_client.process_calls[0].name == "projects/test-proj/locations/us/processors/test-proc"
    assert doc_client.process_calls[0].raw_document.content == b"pdf binary data"
    assert doc_client.process_calls[0].raw_document.mime_type == "application/pdf"
    
    # Assert upsert calls
    assert len(vector_store.upserts) == 1
    assert "Markdown text content from Document Intelligence" in vector_store.upserts[0]["texts"][0]


@pytest.mark.asyncio
async def test_rag_service_ingest_binary_document_limit_exceeded() -> None:
    vector_store = MockVectorStore()
    storage = MockStorage()
    doc_client = MockDocumentAiClient(pages=30)
    
    service = RagService(
        vector_store=vector_store,  # type: ignore[arg-type]
        chunk_size=100,
        chunk_overlap=10,
        storage=storage,
        doc_intelligence_client=doc_client,
        processor_name="projects/test-proj/locations/us/processors/test-proc",
        max_pages=25,
        max_chunks=200,
    )
    
    with pytest.raises(ValueError) as excinfo:
        await service.ingest_binary_document(
            filename="massive.pdf",
            data=b"pdf binary data",
            mime_type="application/pdf",
            user_id="user-123"
        )
        
    assert "Document exceeds 25 page limit" in str(excinfo.value)
    # Cleanup should still have run even on failure
    assert len(storage.deleted) == 1


@pytest.mark.asyncio
async def test_rag_service_ingest_text_document_locally() -> None:
    vector_store = MockVectorStore()
    storage = MockStorage()
    doc_client = MockDocumentAiClient()
    
    service = RagService(
        vector_store=vector_store,  # type: ignore[arg-type]
        chunk_size=100,
        chunk_overlap=10,
        storage=storage,
        doc_intelligence_client=doc_client,
        processor_name=None,
    )
    
    result = await service.ingest_binary_document(
        filename="notes.txt",
        data=b"This is plain text document parsing locally.",
        mime_type="text/plain",
        user_id="user-123"
    )
    
    assert result.chunks_ingested == 1
    assert len(doc_client.process_calls) == 0
    assert len(storage.uploaded) == 0
    assert len(vector_store.upserts) == 1
    assert "This is plain text document parsing locally." in vector_store.upserts[0]["texts"][0]



# Function app tests removed as Azure Functions are replaced by GCP Cloud Run workers in the target architecture.


