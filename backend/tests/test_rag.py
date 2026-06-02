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


class MockDocumentPage:
    pass


class MockDocumentResult:
    def __init__(self, pages=5):
        self.content = "Markdown text content from Document Intelligence"
        self.pages = [MockDocumentPage() for _ in range(pages)]


class MockPoller:
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class MockDocumentIntelligenceClient:
    def __init__(self, pages=5, fail=False):
        self.pages = pages
        self.fail = fail
        self.analyze_calls = []

    def begin_analyze_document(self, model_id, body, content_type, output_content_format):
        self.analyze_calls.append({
            "model_id": model_id,
            "data": body,
            "content_type": content_type,
            "output_content_format": output_content_format
        })
        if self.fail:
            raise ValueError("Document Intelligence error test")
        return MockPoller(MockDocumentResult(pages=self.pages))


@pytest.mark.asyncio
async def test_rag_service_ingest_binary_document_logic() -> None:
    vector_store = MockVectorStore()
    storage = MockStorage()
    doc_client = MockDocumentIntelligenceClient(pages=5)
    
    service = RagService(
        vector_store=vector_store,  # type: ignore[arg-type]
        chunk_size=100,
        chunk_overlap=10,
        storage=storage,
        doc_intelligence_client=doc_client
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
    
    # Assert Document Intelligence was triggered
    assert len(doc_client.analyze_calls) == 1
    assert doc_client.analyze_calls[0]["model_id"] == "prebuilt-layout"
    
    # Assert upsert calls
    assert len(vector_store.upserts) == 1
    assert "Markdown text content from Document Intelligence" in vector_store.upserts[0]["texts"][0]


@pytest.mark.asyncio
async def test_rag_service_ingest_binary_document_limit_exceeded() -> None:
    vector_store = MockVectorStore()
    storage = MockStorage()
    doc_client = MockDocumentIntelligenceClient(pages=105)
    
    service = RagService(
        vector_store=vector_store,  # type: ignore[arg-type]
        chunk_size=100,
        chunk_overlap=10,
        storage=storage,
        doc_intelligence_client=doc_client
    )
    
    with pytest.raises(ValueError) as excinfo:
        await service.ingest_binary_document(
            filename="massive.pdf",
            data=b"pdf binary data",
            mime_type="application/pdf",
            user_id="user-123"
        )
        
    assert "Document exceeds 100 page limit" in str(excinfo.value)
    # Cleanup should still have run even on failure
    assert len(storage.deleted) == 1


def test_function_app_success() -> None:
    import json
    from unittest.mock import patch, MagicMock, AsyncMock, ANY
    from app.services.rag import RagIngestResult

    mock_repo = MagicMock()
    mock_storage = MagicMock()
    mock_rag = MagicMock()
    
    mock_storage.download_bytes.return_value = (b"some document text content", "text/plain")
    
    mock_rag.ingest_document = AsyncMock(return_value=RagIngestResult(document_id="doc-123", chunks_ingested=5))
    mock_rag.ingest_binary_document = MagicMock()
    
    # Event Grid storage queue event body
    event_body = {
        "subject": "/blobServices/default/containers/staging/blobs/user-456/doc-123/my-file.txt",
        "data": {
            "url": "https://dummy.blob.core.windows.net/staging/user-456/doc-123/my-file.txt"
        }
    }
    
    class FakeQueueMessage:
        def get_body(self):
            return json.dumps(event_body).encode("utf-8")
            
    msg = FakeQueueMessage()
    
    with patch("app.dependencies.get_repository", return_value=mock_repo), \
         patch("app.dependencies.get_staging_storage", return_value=mock_storage), \
         patch("app.dependencies.get_rag_service", return_value=mock_rag):
         
         from function_app import process_ingestion
         process_ingestion(msg)
         
    mock_storage.download_bytes.assert_called_with("user-456/doc-123/my-file.txt")
    
    mock_rag.ingest_document.assert_called_with(
        filename="my-file.txt",
        content="some document text content",
        user_id="user-456",
        document_id="doc-123"
    )
    
    mock_repo.update_rag_document_status.assert_called_with(
        "user-456",
        "doc-123",
        "ready",
        5,
        ANY
    )
    
    mock_storage.delete_blob.assert_called_with("user-456/doc-123/my-file.txt")


def test_function_app_failure_updates_status() -> None:
    import json
    from unittest.mock import patch, MagicMock, AsyncMock, ANY

    mock_repo = MagicMock()
    mock_storage = MagicMock()
    mock_rag = MagicMock()
    
    # Simulate an error during staging download
    mock_storage.download_bytes.side_effect = Exception("Storage Connection Lost")
    
    event_body = {
        "subject": "/blobServices/default/containers/staging/blobs/user-456/doc-123/my-file.txt",
        "data": {
            "url": "https://dummy.blob.core.windows.net/staging/user-456/doc-123/my-file.txt"
        }
    }
    
    class FakeQueueMessage:
        def get_body(self):
            return json.dumps(event_body).encode("utf-8")
            
    msg = FakeQueueMessage()
    
    with patch("app.dependencies.get_repository", return_value=mock_repo), \
         patch("app.dependencies.get_staging_storage", return_value=mock_storage), \
         patch("app.dependencies.get_rag_service", return_value=mock_rag):
         
         from function_app import process_ingestion
         process_ingestion(msg)
         
    # Repository should be notified of failure
    mock_repo.update_rag_document_status.assert_called_with(
        "user-456",
        "doc-123",
        "failed",
        0,
        ANY
    )
    
    # staging file should still be cleaned up in finally block
    mock_storage.delete_blob.assert_called_with("user-456/doc-123/my-file.txt")


