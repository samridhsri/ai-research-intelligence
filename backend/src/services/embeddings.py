import os
import logging
from src import config

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        self.provider = config.EMBEDDING_PROVIDER
        self.model_name = config.EMBEDDING_MODEL
        self.openai_client = None
        self.local_model = None

        if self.provider == "openai" and config.HAS_OPENAI:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
                logger.info(f"Initialized OpenAI embedding service using {self.model_name}.")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}. Falling back to local embeddings.")
                self.provider = "local"
        else:
            self.provider = "local"

    def _init_local_model(self):
        if self.local_model is None:
            logger.info("Initializing local SentenceTransformer embeddings...")
            try:
                from sentence_transformers import SentenceTransformer
                self.local_model_name = os.environ.get("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
                self.local_model = SentenceTransformer(self.local_model_name)
                logger.info(f"Initialized local SentenceTransformer with model: {self.local_model_name}.")
            except Exception as e:
                logger.error(f"Failed to load SentenceTransformer: {e}")
                raise e

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generates embeddings for a list of texts.
        """
        if not texts:
            return []

        if self.provider == "openai" and self.openai_client:
            try:
                response = self.openai_client.embeddings.create(
                    input=texts,
                    model=self.model_name
                )
                return [data.embedding for data in response.data]
            except Exception as e:
                logger.error(f"OpenAI embedding generation failed: {e}. Attempting local fallback.")
                self._init_local_model()
                embeddings = self.local_model.encode(texts).tolist()
                return embeddings
        
        # Local execution
        self._init_local_model()
        embeddings = self.local_model.encode(texts).tolist()
        return embeddings

    def get_dimension(self) -> int:
        """
        Returns the embedding dimension.
        """
        if self.provider == "openai" and self.openai_client:
            if "large" in self.model_name:
                return 3072
            return 1536
        else:
            # Local model dimensions
            try:
                self._init_local_model()
                if self.local_model:
                    return self.local_model.get_sentence_embedding_dimension()
            except Exception as e:
                logger.warning(f"Failed to determine local embedding dimension, falling back to 384: {e}")
            return 384

embedding_service = EmbeddingService()

