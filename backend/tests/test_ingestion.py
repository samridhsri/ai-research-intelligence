import unittest
from unittest.mock import patch, MagicMock
from src.tasks.ingestion import process_document_task

class TestIngestionPipeline(unittest.TestCase):
    @patch("src.tasks.ingestion.get_connection")
    @patch("src.tasks.ingestion.storage_service")
    @patch("src.tasks.ingestion.PDFParser")
    @patch("src.tasks.ingestion.embedding_service")
    @patch("src.tasks.ingestion.vector_db_service")
    def test_process_document_task_success(
        self,
        mock_vector_db,
        mock_embedding,
        mock_parser,
        mock_storage,
        mock_get_connection
    ):
        # 1. Setup DB Mock
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_connection.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Mock database fetch of document
        # returns (workspace_id, filename, storage_path, status)
        mock_cursor.fetchone.side_effect = [
            (1, "test.pdf", "local://test.pdf", "processing"), # Select query
            (0,) # chunks count (if main.py uses it elsewhere)
        ]

        # 2. Setup Storage Mock
        mock_storage.download_file.return_value = b"mock pdf bytes"

        # 3. Setup Parser Mock
        mock_parser.parse_pdf.return_value = [
            {"page_number": 1, "text": "This is page one text of our scientific research paper.", "metadata": {}},
            {"page_number": 2, "text": "This is page two talking about hybrid search results.", "metadata": {}}
        ]

        # 4. Setup Embedding Mock
        mock_embedding.provider = "openai"
        mock_embedding.get_embeddings.return_value = [
            [0.1] * 1536, # chunk 1
            [0.2] * 1536  # chunk 2
        ]

        # 5. Run task
        process_document_task(123)

        # 6. Verifications
        # Verify storage downloaded the file
        mock_storage.download_file.assert_called_once_with("local://test.pdf")
        
        # Verify parser parsed the bytes
        mock_parser.parse_pdf.assert_called_once_with(b"mock pdf bytes")
        
        # Verify embedding service was called with chunk text
        mock_embedding.get_embeddings.assert_called_once()
        
        # Verify vector db upsert was triggered
        mock_vector_db.upsert_chunks.assert_called_once()
        
        # Verify status updated to 'ready' in the database
        # Checking SQL calls
        update_calls = [
            call for call in mock_cursor.execute.call_args_list 
            if "UPDATE documents" in call[0][0] and "status = 'ready'" in call[0][0]
        ]
        self.assertEqual(len(update_calls), 1)

if __name__ == "__main__":
    unittest.main()
