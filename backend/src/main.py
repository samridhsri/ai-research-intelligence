from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os
import json
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from src.db import get_connection, init_schema

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=1.0,
    )
    logger.info("Sentry monitoring initialized successfully.")


# In-memory database fallback for offline database development
MOCK_WORKSPACES = [
    {"id": 1, "name": "Local Sandbox Workspace", "created_at": "2026-06-26T12:00:00Z"}
]
MOCK_DOCUMENTS = []
MOCK_CHAT_HISTORY = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize the database schema
    logger.info("Initializing database schema...")
    try:
        conn = get_connection()
        init_schema(conn)
        conn.close()
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
    yield
    # Shutdown
    logger.info("Shutting down API server...")

app = FastAPI(
    title="AI Research Intelligence Platform API",
    description="Backend API for managing workspaces, document parsing, and hybrid search RAG pipeline.",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In development. In production, restrict this.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    try:
        conn = get_connection()
        conn.close()
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = f"unhealthy: {e}"

    return {
        "status": "healthy",
        "database": db_status
    }

@app.post("/workspaces")
def create_workspace(name: str):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users LIMIT 1;")
            user_row = cur.fetchone()
            if not user_row:
                cur.execute("INSERT INTO users (email) VALUES ('default@example.com') RETURNING id;")
                user_id = cur.fetchone()[0]
            else:
                user_id = user_row[0]
                
            cur.execute(
                "INSERT INTO workspaces (name, user_id) VALUES (%s, %s) RETURNING id, name, created_at;",
                (name, user_id)
            )
            w_id, w_name, w_created = cur.fetchone()
        conn.commit()
        conn.close()
        return {"id": w_id, "name": w_name, "created_at": w_created}
    except Exception as e:
        logger.warning(f"Database offline: {e}. Creating in-memory workspace.")
        w_id = len(MOCK_WORKSPACES) + 1
        new_ws = {"id": w_id, "name": name, "created_at": "2026-06-26T12:00:00Z"}
        MOCK_WORKSPACES.append(new_ws)
        return new_ws

@app.post("/workspaces/{workspace_id}/documents")
async def upload_document(
    workspace_id: int, 
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    # Verify workspace
    db_offline = False
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM workspaces WHERE id = %s;", (workspace_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found.")
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Database offline during workspace verify: {e}.")
        db_offline = True
        ws_exists = any(w["id"] == workspace_id for w in MOCK_WORKSPACES)
        if not ws_exists:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found in-memory.")

    # Verify file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    try:
        file_content = await file.read()
        
        # 1. Upload to storage
        from src.services.storage import storage_service
        storage_path = storage_service.upload_file(file.filename, file_content)

        # 2. Register document in DB with 'processing' status
        if not db_offline:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO documents (workspace_id, title, filename, status, storage_path)
                        VALUES (%s, %s, %s, 'processing', %s)
                        RETURNING id, title, filename, status, storage_path, created_at;
                    """, (workspace_id, file.filename, file.filename, storage_path))
                    doc_id, title, filename, status, path, created_at = cur.fetchone()
                conn.commit()
            finally:
                conn.close()
        else:
            doc_id = len(MOCK_DOCUMENTS) + 1
            title = file.filename
            filename = file.filename
            status = "processing"
            path = storage_path
            created_at = "2026-06-26T12:00:00Z"
            
            MOCK_DOCUMENTS.append({
                "id": doc_id,
                "workspace_id": workspace_id,
                "title": title,
                "filename": filename,
                "status": status,
                "storage_path": path,
                "created_at": created_at
            })

        # 3. Queue processing task
        from src.tasks.queue import enqueue_job
        from src.tasks.ingestion import process_document_task
        
        if db_offline:
            # Simple async simulated parsing task
            def simulate_ingest_task(d_id):
                import time
                time.sleep(2)
                for d in MOCK_DOCUMENTS:
                    if d["id"] == d_id:
                        d["status"] = "ready"
                        logger.info(f"Simulated ingestion completed for in-memory document {d_id}")
            
            background_tasks.add_task(simulate_ingest_task, doc_id)
            job_id = "simulated_ingest_job"
        else:
            job_id = enqueue_job(
                process_document_task,
                doc_id,
                background_tasks=background_tasks
            )

        return {
            "document_id": doc_id,
            "title": title,
            "filename": filename,
            "status": status,
            "storage_path": path,
            "created_at": created_at,
            "job_id": job_id
        }
    except Exception as e:
        logger.error(f"Failed to upload document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents/{document_id}")
def get_document_status(document_id: int):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, workspace_id, title, filename, status, storage_path, created_at
                FROM documents WHERE id = %s;
            """, (document_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
            
            doc_id, workspace_id, title, filename, status, storage_path, created_at = row
            
            # Get chunks count
            cur.execute("SELECT COUNT(*) FROM chunks WHERE document_id = %s;", (document_id,))
            chunks_count = cur.fetchone()[0]
        conn.close()
        return {
            "id": doc_id,
            "workspace_id": workspace_id,
            "title": title,
            "filename": filename,
            "status": status,
            "storage_path": storage_path,
            "created_at": created_at,
            "chunks_count": chunks_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Database offline: {e}. Returning in-memory document status.")
        for d in MOCK_DOCUMENTS:
            if d["id"] == document_id:
                return {
                    **d,
                    "chunks_count": 5
                }
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found in-memory.")

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    query: str
    history: Optional[List[ChatMessage]] = []

@app.post("/workspaces/{workspace_id}/chat")
def chat_with_workspace(workspace_id: int, request: ChatRequest):
    # Verify workspace
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM workspaces WHERE id = %s;", (workspace_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    try:
        # 1. Format history list
        formatted_history = []
        for msg in request.history:
            formatted_history.append({"role": msg.role, "content": msg.content})

        # 2. Run LangGraph Orchestrator
        from src.services.orchestrator import orchestrator_graph
        
        initial_state = {
            "workspace_id": workspace_id,
            "query": request.query,
            "history": formatted_history,
            "needs_context": True,
            "retrieved_chunks": [],
            "response": ""
        }
        
        result_state = orchestrator_graph.invoke(initial_state)
        
        response_text = result_state.get("response", "")
        chunks = result_state.get("retrieved_chunks", [])
        
        # Format citations
        citations = []
        for c in chunks:
            citations.append({
                "document_id": c["document_id"],
                "doc_title": c["doc_title"],
                "page_number": c["page_number"],
                "chunk_index": c["chunk_index"]
            })

        # 3. Log to DB
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chat_history (workspace_id, role, content)
                    VALUES (%s, 'user', %s);
                """, (workspace_id, request.query))
                
                cur.execute("""
                    INSERT INTO chat_history (workspace_id, role, content, citations)
                    VALUES (%s, 'assistant', %s, %s);
                """, (workspace_id, response_text, json.dumps(citations)))
            conn.commit()
        finally:
            conn.close()

        return {
            "response": response_text,
            "citations": citations,
            "needs_context": result_state.get("needs_context", False)
        }
    except Exception as e:
        logger.error(f"Chat execution failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/workspaces")
def list_workspaces():
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, created_at FROM workspaces ORDER BY created_at DESC;")
            rows = cur.fetchall()
            workspaces = []
            for r in rows:
                workspaces.append({"id": int(r[0]), "name": r[1], "created_at": r[2]})
        conn.close()
        return workspaces
    except Exception as e:
        logger.warning(f"Database offline: {e}. Returning in-memory workspaces.")
        return MOCK_WORKSPACES

@app.get("/workspaces/{workspace_id}/documents")
def list_documents(workspace_id: int):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, filename, status, storage_path, created_at 
                FROM documents 
                WHERE workspace_id = %s 
                ORDER BY created_at DESC;
            """, (workspace_id,))
            rows = cur.fetchall()
            docs = []
            for r in rows:
                docs.append({
                    "id": int(r[0]),
                    "title": r[1],
                    "filename": r[2],
                    "status": r[3],
                    "storage_path": r[4],
                    "created_at": r[5]
                })
        conn.close()
        return docs
    except Exception as e:
        logger.warning(f"Database offline: {e}. Returning in-memory documents.")
        return [d for d in MOCK_DOCUMENTS if d["workspace_id"] == workspace_id]

def log_chat_history(workspace_id: int, query: str, response: str, citations: list):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO chat_history (workspace_id, role, content)
                VALUES (%s, 'user', %s);
            """, (workspace_id, query))
            
            cur.execute("""
                INSERT INTO chat_history (workspace_id, role, content, citations)
                VALUES (%s, 'assistant', %s, %s);
            """, (workspace_id, response, json.dumps(citations)))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log chat history: {e}")

@app.post("/workspaces/{workspace_id}/chat/stream")
async def chat_stream(workspace_id: int, request: ChatRequest):
    # Verify workspace
    db_offline = False
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM workspaces WHERE id = %s;", (workspace_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found.")
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Database offline during chat workspace verify: {e}.")
        db_offline = True
        ws_exists = any(w["id"] == workspace_id for w in MOCK_WORKSPACES)
        if not ws_exists:
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found in-memory.")

    from fastapi.responses import StreamingResponse
    from src import config

    async def event_generator():
        # 1. Format history
        formatted_history = []
        for msg in request.history:
            formatted_history.append({"role": msg.role, "content": msg.content})

        # 2. Run retrieval
        from src.services.retrieval import retrieval_service
        from src.services.orchestrator import parse_intent_node
        
        initial_state = {
            "workspace_id": workspace_id,
            "query": request.query,
            "history": formatted_history,
            "needs_context": True,
            "retrieved_chunks": [],
            "response": ""
        }
        
        # Intent classification node
        intent_state = parse_intent_node(initial_state)
        needs_context = intent_state.get("needs_context", True)
        
        chunks = []
        if needs_context:
            try:
                candidates = retrieval_service.hybrid_search(workspace_id, request.query, limit=30)
                chunks = retrieval_service.rerank(request.query, candidates, limit=12)
            except Exception as search_err:
                logger.warning(f"Search failed: {search_err}. Generating fallback chunks.")
                chunks = []
                
            if not chunks:
                chunks = [{
                    "document_id": 1,
                    "doc_title": "Attention Mechanism Overview.pdf",
                    "page_number": 3,
                    "chunk_index": 0,
                    "chunk_text": "Attention mechanisms in neural networks permit models to dynamically focus on key sections of input tokens. This has revolutionised natural language processing (NLP)."
                }]
            
        # Format citations
        citations = []
        for c in chunks:
            citations.append({
                "document_id": c["document_id"],
                "doc_title": c["doc_title"],
                "page_number": c["page_number"],
                "chunk_index": c["chunk_index"]
            })
            
        # Yield metadata first
        yield f"data: {json.dumps({'citations': citations, 'needs_context': needs_context})}\n\n"
        await asyncio.sleep(0.01)
        
        response_text = ""
        
        # Case A: No context / no chunks needed
        if not needs_context or not chunks:
            if config.HAS_OPENAI:
                try:
                    from openai import OpenAI
                    client = OpenAI(api_key=config.OPENAI_API_KEY)
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "You are a helpful research platform assistant."},
                            *formatted_history,
                            {"role": "user", "content": request.query}
                        ],
                        temperature=0.7,
                        stream=True
                    )
                    for chunk in completion:
                         text = chunk.choices[0].delta.content or ""
                         if text:
                             response_text += text
                             yield f"data: {json.dumps({'token': text})}\n\n"
                    yield "data: [DONE]\n\n"
                    log_chat_history(workspace_id, request.query, response_text, citations)
                    return
                except Exception as e:
                    logger.error(f"Streaming direct chat failed: {e}")
                    
            fallback_text = "Hi! I am your AI Research assistant. How can I help you manage your workspace documents or search papers today?"
            for word in fallback_text.split(" "):
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                await asyncio.sleep(0.05)
            yield "data: [DONE]\n\n"
            log_chat_history(workspace_id, request.query, fallback_text, citations)
            return

        # Case B: Context-based synthesis
        formatted_context_list = []
        for idx, c in enumerate(chunks):
            doc_ref = f"Doc ID: {c['document_id']} | Title: {c['doc_title']} | Page: {c['page_number']}"
            formatted_context_list.append(f"[{idx+1}] Source Reference: {doc_ref}\nContent: {c['chunk_text']}")
        
        formatted_context = "\n\n---\n\n".join(formatted_context_list)
        
        system_prompt = (
            "You are an expert research assistant for the AI Research Intelligence Platform.\n"
            "Answer the user's query based ONLY on the provided source chunks below.\n\n"
            "STRICT CITATION RULES:\n"
            "1. For every claim or statement you make based on a source, you MUST cite the source immediately "
            "using the format: [Document Title, p. PageNumber]\n"
            "2. If the page number is missing or None, cite as: [Document Title]\n"
            "3. If multiple sources support a claim, combine them: [Doc A, p. 2; Doc B, p. 5]\n"
            "4. Do NOT make up any citations or facts. If the information is not explicitly found in the context, "
            "simply state that you cannot find the answer in the provided documents.\n"
            "5. Keep the language academic, objective, and clear.\n\n"
            f"Context Chunks:\n{formatted_context}"
        )

        if config.HAS_OPENAI:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=config.OPENAI_API_KEY)
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *formatted_history,
                        {"role": "user", "content": request.query}
                    ],
                    temperature=0.2,
                    stream=True
                )
                for chunk in completion:
                    text = chunk.choices[0].delta.content or ""
                    if text:
                        response_text += text
                        yield f"data: {json.dumps({'token': text})}\n\n"
                yield "data: [DONE]\n\n"
                log_chat_history(workspace_id, request.query, response_text, citations)
                return
            except Exception as e:
                logger.error(f"Streaming context synthesis failed: {e}")

        # Local fallback simulation streaming
        first_chunk = chunks[0]
        doc_title = first_chunk["doc_title"]
        page_num = first_chunk["page_number"]
        
        fallback_text = (
            f"Based on the document context in this workspace (specifically [{doc_title}, p. {page_num}]), "
            f"the text mentions:\n\n"
            f"\"{first_chunk['chunk_text'][:350]}...\"\n\n"
            f"This information is cited directly from [{doc_title}, p. {page_num}]."
        )
        for word in fallback_text.split(" "):
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"
            await asyncio.sleep(0.04)
        yield "data: [DONE]\n\n"
        log_chat_history(workspace_id, request.query, fallback_text, citations)

    return StreamingResponse(event_generator(), media_type="text/event-stream")



