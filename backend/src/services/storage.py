import os
import shutil
import logging
from src import config

logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self):
        self.has_supabase = config.HAS_SUPABASE
        if self.has_supabase:
            try:
                from supabase import create_client, Client
                self.supabase: Client = create_client(
                    config.SUPABASE_URL,
                    config.SUPABASE_SERVICE_ROLE_KEY
                )
                logger.info("Supabase storage client initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase storage client: {e}. Falling back to local storage.")
                self.has_supabase = False

    def upload_file(self, filename: str, file_content: bytes) -> str:
        """
        Uploads file to storage. Returns storage path (URI or local path).
        """
        if self.has_supabase:
            try:
                # Supabase requires storage bucket to exist
                # We assume bucket is created. If not, this might raise an error
                response = self.supabase.storage.from_(config.SUPABASE_BUCKET_NAME).upload(
                    path=filename,
                    file=file_content,
                    file_options={"x-upsert": "true"}
                )
                # Supabase upload response contains path/key
                storage_path = f"supabase://{config.SUPABASE_BUCKET_NAME}/{filename}"
                logger.info(f"Uploaded {filename} to Supabase storage. Path: {storage_path}")
                return storage_path
            except Exception as e:
                logger.error(f"Failed to upload {filename} to Supabase storage: {e}. Falling back to local.")
        
        # Local fallback
        local_path = os.path.join(config.UPLOAD_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(file_content)
        logger.info(f"Saved {filename} to local storage at {local_path}")
        return local_path

    def download_file(self, storage_path: str) -> bytes:
        """
        Downloads file from storage path and returns file bytes.
        """
        if storage_path.startswith("supabase://"):
            if not self.has_supabase:
                raise ValueError("Supabase storage is not configured, but requested path is Supabase URI.")
            try:
                bucket_and_file = storage_path.replace("supabase://", "")
                parts = bucket_and_file.split("/", 1)
                bucket_name = parts[0]
                filename = parts[1]
                response = self.supabase.storage.from_(bucket_name).download(filename)
                return response
            except Exception as e:
                logger.error(f"Failed to download {storage_path} from Supabase: {e}")
                raise e

        # Local path
        if not os.path.exists(storage_path):
            raise FileNotFoundError(f"Local file not found: {storage_path}")
        
        with open(storage_path, "rb") as f:
            return f.read()

storage_service = StorageService()
