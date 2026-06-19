import logging
from src.db import get_connection
from src.services.storage import storage_service
from src.services.parser import PDFParser
from src.services.embeddings import embedding_service
from src.services.vector_db import vector_db_service

logger = logging.getLogger(__name__)

def process_document_task(document_id: int):
    """
    Decoupled task running in background to parse PDF, chunk text,
    generate embeddings, and upsert to vector DB and PostgreSQL.
    """
    logger.info(f"Starting ingestion task for document {document_id}")
    
    # 1. Fetch document from database
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT workspace_id, filename, storage_path, status
                FROM documents WHERE id = %s;
            """, (document_id,))
            row = cur.fetchone()
            
        if not row:
            logger.error(f"Document {document_id} not found in database.")
            return

        workspace_id, filename, storage_path, status = row
        logger.info(f"Loaded document {filename} (workspace {workspace_id}) from database. Storage path: {storage_path}")

        # Update status to processing
        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET status = 'processing' WHERE id = %s;", (document_id,))
        conn.commit()

        # 2. Download file from storage
        file_bytes = storage_service.download_file(storage_path)
        logger.info(f"Downloaded PDF {filename} ({len(file_bytes)} bytes)")

        # 3. Parse PDF with PyMuPDF
        pages = PDFParser.parse_pdf(file_bytes)
        if not pages:
            raise ValueError("No pages parsed from the PDF document.")

        # 4. Chunk text with RecursiveCharacterTextSplitter
        # Lazy import of langchain_text_splitters to avoid overhead on boot
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )

        all_chunks = []
        global_chunk_idx = 0
        
        for page in pages:
            page_num = page["page_number"]
            page_text = page["text"]
            if not page_text.strip():
                continue
            
            splits = text_splitter.split_text(page_text)
            for split in splits:
                all_chunks.append({
                    "chunk_index": global_chunk_idx,
                    "text": split,
                    "page_number": page_num
                })
                global_chunk_idx += 1

        logger.info(f"Segmented document into {len(all_chunks)} chunks.")

        if not all_chunks:
            raise ValueError("Document has no text content to index.")

        # 5. Generate embeddings for chunks
        chunk_texts = [c["text"] for c in all_chunks]
        embeddings = embedding_service.get_embeddings(chunk_texts)
        logger.info(f"Generated {len(embeddings)} embeddings using provider '{embedding_service.provider}'.")

        # 6. Upsert chunks and embeddings to Pinecone and PostgreSQL chunks table
        vector_db_service.upsert_chunks(
            document_id=document_id,
            workspace_id=workspace_id,
            chunks=all_chunks,
            embeddings=embeddings
        )

        # 7. Update document status to ready
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE documents 
                SET status = 'ready' 
                WHERE id = %s;
            """, (document_id,))
        conn.commit()
        logger.info(f"Document {document_id} ingestion completed successfully.")

    except Exception as e:
        logger.error(f"Failed to ingest document {document_id}: {e}", exc_info=True)
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE documents SET status = 'failed' WHERE id = %s;", (document_id,))
                conn.commit()
            except Exception as inner_e:
                logger.error(f"Failed to update document status to failed: {inner_e}")
    finally:
        if conn:
            conn.close()
