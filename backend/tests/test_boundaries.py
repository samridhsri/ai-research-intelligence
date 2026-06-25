import pytest
from unittest.mock import patch, MagicMock
from src.tasks.ingestion import process_document_task
from src.services.retrieval import retrieval_service

@patch("src.tasks.ingestion.get_connection")
@patch("src.tasks.ingestion.storage_service")
@patch("src.tasks.ingestion.PDFParser")
def test_ingestion_failure_empty_pdf(mock_parser, mock_storage, mock_get_connection):
    """
    Checks that document ingestion fails gracefully when document has no text content.
    """
    # 1. Setup DB Mock
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_connection.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    mock_cursor.fetchone.return_value = (1, "empty.pdf", "local://empty.pdf", "processing")
    
    # 2. Setup mock empty pages
    mock_storage.download_file.return_value = b""
    mock_parser.parse_pdf.return_value = [] # Empty pages
    
    # 3. Run task
    process_document_task(123)
    
    # 4. Verify document status set to 'failed' in DB
    failed_calls = [
        call for call in mock_cursor.execute.call_args_list 
        if "UPDATE documents SET status = 'failed'" in call[0][0]
    ]
    assert len(failed_calls) == 1

@patch("src.services.retrieval.embedding_service")
@patch("src.services.retrieval.get_connection")
def test_empty_workspace_hybrid_search(mock_get_connection, mock_embedding_service):
    """
    Checks that hybrid search returns safely when workspace has no documents or chunks indexed.
    """
    # Mock embedding query
    mock_embedding_service.get_embeddings.return_value = [[0.1] * 1536]

    # Setup DB Mock return empty results
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_connection.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []
    
    # Run search
    results = retrieval_service.hybrid_search(workspace_id=999, query="test query", limit=5)
    
    # Assert returns empty array
    assert isinstance(results, list)
    assert len(results) == 0


def test_under_limit_cohere_reranking():
    """
    Checks that reranker functions successfully and preserves candidates order
    when candidates count is less than the cohere top_n limit.
    """
    # 1. Disable Cohere client mock or mock it returning less results
    retrieval_service.has_cohere = True
    retrieval_service.cohere_client = MagicMock()
    
    # Mock Cohere response
    mock_response = MagicMock()
    mock_result_1 = MagicMock(index=0, relevance_score=0.95)
    mock_result_2 = MagicMock(index=1, relevance_score=0.88)
    mock_response.results = [mock_result_1, mock_result_2]
    retrieval_service.cohere_client.rerank.return_value = mock_response
    
    # Input candidates (length 2)
    candidates = [
        {"document_id": 1, "chunk_index": 0, "chunk_text": "Chunk 1", "page_number": 1, "doc_title": "Doc"},
        {"document_id": 1, "chunk_index": 1, "chunk_text": "Chunk 2", "page_number": 2, "doc_title": "Doc"}
    ]
    
    # Rerank with limit 5 (which is greater than candidates count 2)
    reranked = retrieval_service.rerank(query="query", chunks=candidates, limit=5)
    
    # Verify it runs successfully and returns the elements
    assert len(reranked) == 2
    assert reranked[0]["rerank_score"] == 0.95
    assert reranked[1]["rerank_score"] == 0.88
