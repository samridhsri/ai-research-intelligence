import os
import psycopg2
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_DIM = {
    "BAAI/bge-small-en-v1.5": 384,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

def get_connection():
    conn = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )
    register_vector(conn)
    return conn


def init_schema(conn):
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    dim = EMBEDDING_DIM[model]

    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # 1. Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          BIGSERIAL PRIMARY KEY,
                email       TEXT UNIQUE NOT NULL,
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. Workspaces table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id          BIGSERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                user_id     BIGINT REFERENCES users(id) ON DELETE SET NULL,
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 3. Documents table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id           BIGSERIAL PRIMARY KEY,
                workspace_id BIGINT REFERENCES workspaces(id) ON DELETE CASCADE,
                title        TEXT,
                url          TEXT,
                arxiv_id     TEXT,
                filename     TEXT,
                status       TEXT NOT NULL DEFAULT 'processing', -- 'processing' | 'ready' | 'failed'
                storage_path TEXT,
                created_at   TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 4. Chunks table (with pgvector embedding)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id          BIGSERIAL PRIMARY KEY,
                document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER,
                chunk_text  TEXT NOT NULL,
                page_number INTEGER,
                embedding   vector({dim}),
                metadata    JSONB
            );
        """)

        # 5. Chat History table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id           BIGSERIAL PRIMARY KEY,
                workspace_id BIGINT REFERENCES workspaces(id) ON DELETE CASCADE,
                role         TEXT NOT NULL, -- 'user' | 'assistant'
                content      TEXT NOT NULL,
                citations    JSONB,
                created_at   TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create HNSW index on the vector embedding for faster cosine similarity queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS chunks_hnsw_embedding_idx
            ON chunks USING hnsw (embedding vector_cosine_ops);
        """)

        # Create GIN index on to_tsvector for faster full-text keyword searches
        cur.execute("""
            CREATE INDEX IF NOT EXISTS chunks_fts_idx 
            ON chunks USING GIN (to_tsvector('english', chunk_text));
        """)
        
    conn.commit()
