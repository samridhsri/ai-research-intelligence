import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Postgres
PGHOST = os.environ.get("PGHOST", "localhost")
PGPORT = os.environ.get("PGPORT", "5432")
PGDATABASE = os.environ.get("PGDATABASE", "arxiv_rag")
PGUSER = os.environ.get("PGUSER", "arxiv")
PGPASSWORD = os.environ.get("PGPASSWORD", "arxiv")

# Embeddings
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "local")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

# API Keys
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "arxiv-research")
COHERE_API_KEY = os.environ.get("COHERE_API_KEY")

# Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET_NAME = os.environ.get("SUPABASE_BUCKET_NAME", "research-docs")

# Local Storage Path
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Redis
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

def is_redis_available() -> bool:
    try:
        import redis
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            socket_connect_timeout=2
        )
        r.ping()
        return True
    except Exception as e:
        logger.warning(f"Redis is not available: {e}. Falling back to FastAPI BackgroundTasks.")
        return False

# Capabilities Checks
HAS_OPENAI = bool(OPENAI_API_KEY)
HAS_PINECONE = bool(PINECONE_API_KEY)
HAS_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
HAS_COHERE = bool(COHERE_API_KEY)
USE_REDIS = is_redis_available()
