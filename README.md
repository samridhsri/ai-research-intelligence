# AI Research Intelligence Platform

A modular, production-grade hybrid search RAG (Retrieval-Augmented Generation) pipeline for managing scientific research papers and documents. The platform provides localized document ingestion, vector similarity search combined with full-text search, reranking, and agentic response synthesis.

---

## Key Features

- **Hybrid Search RAG**: Integrates dense vector embeddings (OpenAI `text-embedding-3-small` or local `sentence-transformers`) with sparse PostgreSQL full-text search, combined via **Reciprocal Rank Fusion (RRF)**.
- **Reranking**: Utilizes the Cohere Rerank API to select top candidate chunks.
- **Agentic Orchestration**: Uses **LangGraph** state graphs to determine query intent, retrieve context, format strict source citations, and synthesize responses.
- **Background Ingestion Workers**: Offloads heavy PDF parsing (PyMuPDF) and embedding calculations to an asynchronous RQ task queue backed by Redis.
- **Full Offline Capability**: Automatically falls back to free, local alternatives (Postgres pgvector, keyword heuristics, local rule-based answers) when external API keys are missing.
- **Production Observability**: Configured with Sentry error monitoring and LangSmith execution tracing.

---

## Architecture

![Architecture Diagram](architecureDiagramAIResearchIntelligence.png)

### Component Architecture (Mermaid)
```mermaid
graph TD
    %% Styling
    classDef client fill:#dcf8c6,stroke:#333,stroke-width:2px;
    classDef app fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef worker fill:#ede7f6,stroke:#5e35b1,stroke-width:2px;
    classDef db fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;
    classDef external fill:#ffe0b2,stroke:#f57c00,stroke-width:2px;

    %% Nodes
    NextJS["Next.js Frontend"]:::client
    FastAPI["FastAPI Backend (API)"]:::app
    Redis["Redis Queue (RQ)"]:::app
    Worker["RQ Background Worker"]:::worker
    
    Postgres[("PostgreSQL\n(pgvector + FTS)")]:::db
    Supabase[("Supabase Storage\n(or Local Storage)")]:::db
    Pinecone[("Pinecone Index\n(Vector DB Option)")]:::db
    
    OpenAIEmbed["OpenAI Embedding API\n(text-embedding-3-small)"]:::external
    OpenAILLM["OpenAI Chat API\n(gpt-4o-mini)"]:::external
    CohereRerank["Cohere Rerank API\n(rerank-english-v3.0)"]:::external
    LocalTransformers["Local Embeddings\n(SentenceTransformers)"]:::external

    %% Relations
    NextJS -- HTTP REST --> FastAPI
    FastAPI -- Enqueue Job --> Redis
    Redis -- Polls Jobs --> Worker
    
    %% API Interactions
    FastAPI -- Reads Meta / Chat History --> Postgres
    FastAPI -- LangGraph RAG --> OpenAILLM
    FastAPI -- Hybrid Search --> Postgres
    FastAPI -- Hybrid Search --> Pinecone
    FastAPI -- Reranks Chunks --> CohereRerank
    
    %% Worker Ingestion Interactions
    Worker -- Uploads/Downloads raw PDFs --> Supabase
    Worker -- Extract & Chunk PDFs --> Worker
    Worker -- Generate Embeddings --> OpenAIEmbed
    Worker -- Generate Embeddings (Fallback) --> LocalTransformers
    Worker -- Index Vectors & Text --> Postgres
    Worker -- Index Vectors (Optional) --> Pinecone
```

### Document Ingestion Sequence
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Front as Next.js Frontend
    participant API as FastAPI Backend
    participant Redis as Redis Queue
    participant Worker as Background Worker
    participant DB as PostgreSQL
    participant Storage as Storage Service
    participant Embed as Embedding API

    User->>Front: Upload PDF Document
    Front->>API: POST /workspaces/{id}/documents (with file)
    API->>Storage: upload_file(filename, bytes)
    Storage-->>API: return storage_path
    API->>DB: INSERT INTO documents (status='processing')
    DB-->>API: return document_id
    API->>Redis: enqueue_job(process_document_task, document_id)
    API-->>Front: Return 200 OK (status='processing')
    
    Note over Worker, Redis: Worker processes job asynchronously
    Worker->>Redis: Fetch job (process_document_task)
    Worker->>DB: UPDATE documents SET status='processing'
    Worker->>Storage: download_file(storage_path)
    Storage-->>Worker: return file_bytes
    Worker->>Worker: Parse PDF (PyMuPDF) & Chunk (RecursiveCharacterTextSplitter)
    Worker->>Embed: get_embeddings(chunk_texts)
    Embed-->>Worker: return list of vector embeddings
    Worker->>DB: INSERT INTO chunks (document_id, chunk_text, page_number, embedding)
    Worker->>DB: UPDATE documents SET status='ready'
```

### LangGraph RAG State Flow
```mermaid
stateDiagram-v2
    [*] --> IntentClassifier : User Query Received
    
    state IntentClassifier {
        [*] --> ClassifyIntent
    }
    
    IntentClassifier --> HybridSearchRetriever : True (Needs Context)
    IntentClassifier --> ResponseSynthesizer : False (General Query)

    state HybridSearchRetriever {
        [*] --> ParallelSearch
        ParallelSearch --> DenseVectorSearch
        ParallelSearch --> SparseFTSearch
        DenseVectorSearch --> RRF_Fusion
        SparseFTSearch --> RRF_Fusion
        RRF_Fusion --> CohereReranker
        CohereReranker --> DiversificationFilter
    }
    
    HybridSearchRetriever --> ResponseSynthesizer : Context Chunks Loaded
    
    state ResponseSynthesizer {
        [*] --> SynthesisPrompt
        SynthesisPrompt --> SynthesizeResponse
    }

    ResponseSynthesizer --> [*] : Return Answer & Citations
```

---

## Project Structure

The codebase is divided into two primary workspaces:

* **[backend](file:///home/sam/projects/ai/ai-research-intelligence-platform/backend)**: FastAPI API service and background workers.
  - **[src/main.py](file:///home/sam/projects/ai/ai-research-intelligence-platform/backend/src/main.py)**: API routes (workspaces, documents, chat/streaming endpoints).
  - **[src/services/orchestrator.py](file:///home/sam/projects/ai/ai-research-intelligence-platform/backend/src/services/orchestrator.py)**: LangGraph state machine orchestrating RAG pipeline stages.
  - **[src/services/retrieval.py](file:///home/sam/projects/ai/ai-research-intelligence-platform/backend/src/services/retrieval.py)**: Dense pgvector search, FTS, RRF, and Cohere reranker.
  - **[src/tasks/ingestion.py](file:///home/sam/projects/ai/ai-research-intelligence-platform/backend/src/tasks/ingestion.py)**: Asynchronous task pipeline for downloading, parsing, chunking, and indexing document uploads.
  - **[tests/](file:///home/sam/projects/ai/ai-research-intelligence-platform/backend/tests)**: Unit tests and edge boundary test suites.
* **[frontend](file:///home/sam/projects/ai/ai-research-intelligence-platform/frontend)**: Next.js user interface utilizing TailwindCSS and Sentry logging.

---

## Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL (with `pgvector` extension)
- Redis

---

## Setup & Execution

### 1. Configure Environment Variables
Copy the backend configuration template and populate your API credentials:
```bash
cp backend/.env.example backend/.env
```

To configure external paid services (OpenAI, Pinecone, Cohere, Supabase, Sentry, LangSmith), uncomment and populate their respective slots in the `.env` file. If left commented, the platform runs using local fallback services.

### 2. Containerized Deployment (Recommended)
You can start the entire stack (PostgreSQL with pgvector, Redis, FastAPI, and RQ Worker) with Docker:
```bash
cd backend
docker compose build
docker compose up -d
```

### 3. Manual Local Installation

#### Backend
Activate the python virtual environment, install dependencies, and start the FastAPI uvicorn server:
```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

In a separate terminal, start the background ingestion worker:
```bash
cd backend
source venv/bin/activate
python src/worker.py
```

#### Frontend
Install dependencies and run the Next.js development server:
```bash
cd frontend
npm install
npm run dev
```

---

## Testing

Run the automated test suite using `pytest`:
```bash
cd backend
PYTHONPATH=. pytest
```
