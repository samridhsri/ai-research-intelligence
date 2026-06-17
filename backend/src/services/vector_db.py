import logging
import json
from src import config
from src.db import get_connection

logger = logging.getLogger(__name__)

class VectorDBService:
    def __init__(self):
        self.has_pinecone = config.HAS_PINECONE
        self.pinecone_index = None

        if self.has_pinecone:
            try:
                from pinecone import Pinecone
                self.pc = Pinecone(api_key=config.PINECONE_API_KEY)
                logger.info("Pinecone client initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Pinecone: {e}. Skipping Pinecone upserts.")
                self.has_pinecone = False

    def init_pinecone_index(self, dimension: int):
        """
        Ensures Pinecone index exists and hooks to it.
        """
        if not self.has_pinecone:
            return
        
        try:
            from pinecone import ServerlessSpec
            existing_indexes = [idx.name for idx in self.pc.list_indexes()]
            if config.PINECONE_INDEX_NAME not in existing_indexes:
                logger.info(f"Creating Pinecone index '{config.PINECONE_INDEX_NAME}' with dimension {dimension}...")
                self.pc.create_index(
                    name=config.PINECONE_INDEX_NAME,
                    dimension=dimension,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1")
                )
            self.pinecone_index = self.pc.Index(config.PINECONE_INDEX_NAME)
            logger.info(f"Connected to Pinecone index: {config.PINECONE_INDEX_NAME}")
        except Exception as e:
            logger.error(f"Failed to connect/create Pinecone index: {e}. Disabling Pinecone upserts.")
            self.has_pinecone = False

    def upsert_chunks(self, document_id: int, workspace_id: int, chunks: list[dict], embeddings: list[list[float]]):
        """
        Upserts chunks with embeddings to Pinecone and inserts them to Postgres chunks table.
        chunks schema: [{"chunk_index": int, "text": str, "page_number": int}]
        """
        if not chunks or not embeddings:
            return

        dimension = len(embeddings[0])
        
        # Ensure Pinecone index is initialized
        if self.has_pinecone and not self.pinecone_index:
            self.init_pinecone_index(dimension)

        # 1. Upsert to Pinecone
        if self.has_pinecone and self.pinecone_index:
            try:
                vectors = []
                for i, chunk in enumerate(chunks):
                    vector_id = f"doc_{document_id}_chunk_{chunk['chunk_index']}"
                    metadata = {
                        "document_id": int(document_id),
                        "workspace_id": int(workspace_id),
                        "page_number": int(chunk["page_number"]),
                        "chunk_index": int(chunk["chunk_index"]),
                        "text": chunk["text"]
                    }
                    vectors.append({
                        "id": vector_id,
                        "values": embeddings[i],
                        "metadata": metadata
                    })
                
                # Batch upsert to Pinecone
                batch_size = 100
                for start_idx in range(0, len(vectors), batch_size):
                    batch = vectors[start_idx:start_idx + batch_size]
                    self.pinecone_index.upsert(vectors=batch)
                
                logger.info(f"Successfully upserted {len(chunks)} chunks to Pinecone.")
            except Exception as e:
                logger.error(f"Failed to upsert vectors to Pinecone: {e}")

        # 2. Insert to PostgreSQL pgvector chunks table
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                for i, chunk in enumerate(chunks):
                    # We can store extra metadata as JSONB
                    chunk_metadata = {
                        "workspace_id": workspace_id,
                        "char_count": len(chunk["text"])
                    }
                    cur.execute("""
                        INSERT INTO chunks (document_id, chunk_index, chunk_text, page_number, embedding, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """, (
                        document_id,
                        chunk["chunk_index"],
                        chunk["text"],
                        chunk["page_number"],
                        embeddings[i],
                        json.dumps(chunk_metadata)
                    ))
            conn.commit()
            conn.close()
            logger.info(f"Successfully inserted {len(chunks)} chunks to PostgreSQL chunks table.")
        except Exception as e:
            logger.error(f"Failed to insert chunks to PostgreSQL pgvector: {e}")
            raise e

vector_db_service = VectorDBService()
