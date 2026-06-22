import unittest
from unittest.mock import patch, MagicMock
from src.services.retrieval import reciprocal_rank_fusion
from src.services.orchestrator import (
    parse_intent_node, 
    retrieve_node, 
    synthesize_node,
    route_after_intent
)

class TestRetrievalOrchestration(unittest.TestCase):
    def test_reciprocal_rank_fusion(self):
        # Sample chunks
        vec_chunks = [
            {"document_id": 1, "chunk_index": 0, "chunk_text": "Chunk A"},
            {"document_id": 1, "chunk_index": 1, "chunk_text": "Chunk B"}
        ]
        fts_chunks = [
            {"document_id": 1, "chunk_index": 1, "chunk_text": "Chunk B"},
            {"document_id": 2, "chunk_index": 0, "chunk_text": "Chunk C"}
        ]
        
        # Fusion with constant k=60
        # Chunk B: rank 1 (index 1) in vec and rank 0 (index 0) in fts -> score = 1/(60+2) + 1/(60+1)
        # Chunk A: rank 0 in vec -> score = 1/(60+1)
        # Chunk C: rank 1 in fts -> score = 1/(60+2)
        
        fused = reciprocal_rank_fusion(vec_chunks, fts_chunks, k=60)
        
        # Chunk B should rank first because it's in both lists
        self.assertEqual(fused[0]["document_id"], 1)
        self.assertEqual(fused[0]["chunk_index"], 1)
        self.assertEqual(fused[1]["document_id"], 1)
        self.assertEqual(fused[1]["chunk_index"], 0)
        self.assertEqual(fused[2]["document_id"], 2)
        self.assertEqual(fused[2]["chunk_index"], 0)

    @patch("src.services.orchestrator.config")
    def test_parse_intent_heuristics_need_context(self, mock_config):
        mock_config.HAS_OPENAI = False
        state = {"query": "What is the attention mechanism in transformers?", "workspace_id": 1, "history": []}
        result = parse_intent_node(state)
        self.assertTrue(result["needs_context"])

    @patch("src.services.orchestrator.config")
    def test_parse_intent_heuristics_no_context(self, mock_config):
        mock_config.HAS_OPENAI = False
        state = {"query": "Hello", "workspace_id": 1, "history": []}
        result = parse_intent_node(state)
        self.assertFalse(result["needs_context"])

    def test_route_after_intent(self):
        state_need = {"needs_context": True}
        state_no_need = {"needs_context": False}
        self.assertEqual(route_after_intent(state_need), "retrieve")
        self.assertEqual(route_after_intent(state_no_need), "synthesize")

    @patch("src.services.orchestrator.retrieval_service")
    def test_retrieve_node(self, mock_retrieval):
        state = {"workspace_id": 1, "query": "test query", "history": []}
        
        mock_retrieval.hybrid_search.return_value = [{"document_id": 1, "chunk_index": 0, "chunk_text": "text"}]
        mock_retrieval.rerank.return_value = [{"document_id": 1, "chunk_index": 0, "chunk_text": "text", "rerank_score": 0.99}]
        
        res = retrieve_node(state)
        self.assertEqual(len(res["retrieved_chunks"]), 1)
        self.assertEqual(res["retrieved_chunks"][0]["rerank_score"], 0.99)

    @patch("src.services.orchestrator.config")
    def test_synthesize_node_fallback_citation(self, mock_config):
        mock_config.HAS_OPENAI = False
        state = {
            "workspace_id": 1,
            "query": "query",
            "history": [],
            "needs_context": True,
            "retrieved_chunks": [
                {"document_id": 10, "chunk_index": 2, "chunk_text": "Attention works by mapping queries to key-value pairs.", "page_number": 4, "doc_title": "Attention Paper"}
            ]
        }
        res = synthesize_node(state)
        self.assertIn("Attention Paper, p. 4", res["response"])
        self.assertIn("Attention works by mapping", res["response"])

if __name__ == "__main__":
    unittest.main()
