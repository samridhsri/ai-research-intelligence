import logging
import json
from src import config
from src.db import get_connection
from src.services.embeddings import embedding_service
from src.services.vector_db import vector_db_service

logger = logging.getLogger(__name__)

def reciprocal_rank_fusion(vector_results: list, fts_results: list, k: int = 60) -> list:
    """
    RRF combines lists of ranked candidates.
    """
    scores = {}
    chunk_data = {}
    
    def get_key(chunk):
        return f"{chunk['document_id']}_{chunk['chunk_index']}"
    
    for rank, chunk in enumerate(vector_results):
        key = get_key(chunk)
        chunk_data[key] = chunk
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        
    for rank, chunk in enumerate(fts_results):
        key = get_key(chunk)
        chunk_data[key] = chunk
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        
    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    
    fused = []
    for key in sorted_keys:
        c = dict(chunk_data[key])
        c["rrf_score"] = scores[key]
        fused.append(c)
        
    return fused

def diversify_chunks(chunks: list, limit: int) -> list:
    """
    Selects up to `limit` chunks from the list, ensuring that chunks from different
    documents are selected in a round-robin fashion.
    Filters out chunks with low relevance relative to the top match to prevent
    pulling unrelated documents.
    """
    if not chunks:
        return []
        
    # Apply relative/absolute relevance filtering to avoid pulling unrelated documents
    first_chunk = chunks[0]
    filtered_chunks = []
    
    if "rerank_score" in first_chunk:
        # Cohere rerank score
        top_score = first_chunk["rerank_score"]
        min_score = max(0.05, top_score * 0.15)
        filtered_chunks = [c for c in chunks if c.get("rerank_score", 0) >= min_score]
    elif "rrf_score" in first_chunk:
        # RRF score
        top_score = first_chunk["rrf_score"]
        min_score = top_score * 0.5
        filtered_chunks = [c for c in chunks if c.get("rrf_score", 0) >= min_score]
    else:
        # Vector / FTS similarity score
        top_score = first_chunk.get("score", 0)
        min_score = max(0.3, top_score * 0.5)
        filtered_chunks = [c for c in chunks if c.get("score", 0) >= min_score]
        
    # Fallback to the top candidates if the filter is too aggressive
    if not filtered_chunks:
        filtered_chunks = chunks[:limit]
        
    # Group chunks by document_id while preserving sorted order within each group
    groups = {}
    for c in filtered_chunks:
        doc_id = c.get("document_id")
        if doc_id not in groups:
            groups[doc_id] = []
        groups[doc_id].append(c)
        
    # Convert groups to a list of lists of chunks
    group_lists = list(groups.values())
    
    # Round-robin selection
    selected = []
    index = 0
    while len(selected) < limit and group_lists:
        active_groups = []
        for g in group_lists:
            if index < len(g):
                selected.append(g[index])
                if len(selected) >= limit:
                    break
                active_groups.append(g)
        group_lists = active_groups
        index += 1
        
    return selected

class RetrievalService:
    def __init__(self):
        self.has_cohere = config.HAS_COHERE
        self.cohere_client = None
        
        if self.has_cohere:
            try:
                import cohere
                self.cohere_client = cohere.Client(api_key=config.COHERE_API_KEY)
                logger.info("Cohere rerank client initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Cohere client: {e}. Falling back to default top-N.")
                self.has_cohere = False

    def get_vector_candidates(self, workspace_id: int, query: str, limit: int = 20) -> list[dict]:
        """
        Retrieves vector similarity candidates from Pinecone (or falls back to PostgreSQL pgvector).
        """
        results = []
        try:
            # 1. Get embedding for user query
            query_embedding = embedding_service.get_embeddings([query])[0]
            
            # 2. Query Pinecone if available
            if vector_db_service.has_pinecone and vector_db_service.pinecone_index:
                try:
                    # Filter by workspace_id
                    pinecone_res = vector_db_service.pinecone_index.query(
                        vector=query_embedding,
                        filter={"workspace_id": int(workspace_id)},
                        top_k=limit,
                        include_metadata=True
                    )
                    
                    # Fetch document names in bulk from DB to append to candidates if needed,
                    # or read them directly from metadata.
                    for match in pinecone_res.matches:
                        metadata = match.metadata
                        results.append({
                            "document_id": int(metadata["document_id"]),
                            "chunk_index": int(metadata["chunk_index"]),
                            "chunk_text": metadata["text"],
                            "page_number": int(metadata["page_number"]),
                            "doc_title": metadata.get("title", f"Doc {metadata['document_id']}"),
                            "score": match.score
                        })
                    
                    logger.info(f"Retrieved {len(results)} vector candidates from Pinecone.")
                    return results
                except Exception as e:
                    logger.error(f"Pinecone query failed: {e}. Falling back to Postgres pgvector.")
            
            # 3. Fallback to local Postgres pgvector similarity
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT c.id, c.document_id, c.chunk_index, c.chunk_text, c.page_number,
                               (1 - (c.embedding <=> %s::vector)) as score,
                               d.title as doc_title
                        FROM chunks c
                        JOIN documents d ON c.document_id = d.id
                        WHERE d.workspace_id = %s
                        ORDER BY score DESC
                        LIMIT %s;
                    """, (query_embedding, workspace_id, limit))
                    
                    for row in cur.fetchall():
                        cid, doc_id, chunk_idx, text, page_num, score, title = row
                        results.append({
                            "document_id": doc_id,
                            "chunk_index": chunk_idx,
                            "chunk_text": text,
                            "page_number": page_num,
                            "doc_title": title or f"Doc {doc_id}",
                            "score": score
                        })
                logger.info(f"Retrieved {len(results)} vector candidates from Postgres pgvector.")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Vector candidates retrieval failed: {e}")
            
        return results

    def get_fts_candidates(self, workspace_id: int, query: str, limit: int = 20) -> list[dict]:
        """
        Retrieves keyword matches using PostgreSQL full-text search.
        """
        results = []
        try:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    # plainto_tsquery compiles the raw query into a logical tsquery
                    cur.execute("""
                        SELECT c.id, c.document_id, c.chunk_index, c.chunk_text, c.page_number,
                               ts_rank(to_tsvector('english', c.chunk_text), plainto_tsquery('english', %s)) as score,
                               d.title as doc_title
                        FROM chunks c
                        JOIN documents d ON c.document_id = d.id
                        WHERE to_tsvector('english', c.chunk_text) @@ plainto_tsquery('english', %s)
                          AND d.workspace_id = %s
                        ORDER BY score DESC
                        LIMIT %s;
                    """, (query, query, workspace_id, limit))
                    
                    for row in cur.fetchall():
                        cid, doc_id, chunk_idx, text, page_num, score, title = row
                        results.append({
                            "document_id": doc_id,
                            "chunk_index": chunk_idx,
                            "chunk_text": text,
                            "page_number": page_num,
                            "doc_title": title or f"Doc {doc_id}",
                            "score": score
                        })
                logger.info(f"Retrieved {len(results)} FTS candidates from Postgres.")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Postgres FTS query failed: {e}")
            
        return results

    def hybrid_search(self, workspace_id: int, query: str, limit: int = 20) -> list[dict]:
        """
        Runs vector and full-text searches simultaneously and fuses them using RRF.
        """
        vector_candidates = self.get_vector_candidates(workspace_id, query, limit=limit)
        fts_candidates = self.get_fts_candidates(workspace_id, query, limit=limit)
        
        fused = reciprocal_rank_fusion(vector_candidates, fts_candidates)
        return fused[:limit]

    def rerank(self, query: str, chunks: list[dict], limit: int = 5) -> list[dict]:
        """
        Reranks top candidate chunks using Cohere Rerank API, then applies
        a round-robin diversification filter to represent multiple documents.
        """
        if not chunks:
            return []
            
        if not self.has_cohere or not self.cohere_client:
            logger.info("Cohere rerank not active. Returning diversified top candidates directly.")
            return diversify_chunks(chunks, limit)
            
        try:
            texts = [c["chunk_text"] for c in chunks]
            
            response = self.cohere_client.rerank(
                model="rerank-english-v3.0",
                query=query,
                documents=texts,
                top_n=len(chunks)
            )
            
            reranked = []
            for result in response.results:
                idx = result.index
                c = dict(chunks[idx])
                c["rerank_score"] = result.relevance_score
                reranked.append(c)
                
            diversified = diversify_chunks(reranked, limit)
            logger.info(f"Successfully reranked and diversified chunks using Cohere. Returned {len(diversified)} results.")
            return diversified
        except Exception as e:
            logger.error(f"Cohere rerank failed: {e}. Falling back to default diversified candidates.")
            return diversify_chunks(chunks, limit)

retrieval_service = RetrievalService()
