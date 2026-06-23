import logging
import json
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, START, END
from src import config
from src.services.retrieval import retrieval_service

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    workspace_id: int
    query: str
    history: List[Dict[str, str]]
    needs_context: bool
    retrieved_chunks: List[Dict[str, Any]]
    response: str

def parse_intent_node(state: AgentState) -> dict:
    """
    Node A: Parses intent using LLM (or fallback heuristics) to decide if context search is required.
    """
    query_lower = state["query"].lower()
    logger.info(f"Orchestrator: Parsing intent for query: '{state['query']}'")
    
    # If OpenAI is active, try to classify intent using LLM
    if config.HAS_OPENAI:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=config.OPENAI_API_KEY)
            
            prompt_messages = [
                {
                    "role": "system", 
                    "content": (
                        "You are an intent classifier for a research assistant. "
                        "Determine if the user query is asking about documents, seeking specific paper details, or asking questions "
                        "that require document retrieval from their research platform workspace.\n"
                        "Respond with a JSON object containing a single boolean key 'needs_context'. "
                        "Example:\n{\"needs_context\": true}"
                    )
                },
                {"role": "user", "content": f"Query: {state['query']}"}
            ]
            
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=prompt_messages,
                temperature=0.0
            )
            
            data = json.loads(completion.choices[0].message.content)
            needs_context = bool(data.get("needs_context", True))
            logger.info(f"LLM Classified Intent: needs_context = {needs_context}")
            return {"needs_context": needs_context}
        except Exception as e:
            logger.error(f"LLM intent classification failed: {e}. Falling back to keywords heuristics.")

    # Local fallback heuristics
    keywords = [
        "what", "how", "why", "who", "explain", "describe", "summarize", 
        "search", "find", "paper", "attention", "transformer", "rag", 
        "results", "?", "detail", "cite", "citation", "algorithm", 
        "evaluate", "method", "dataset"
    ]
    needs_context = any(kw in query_lower for kw in keywords) or len(query_lower.split()) > 4
    logger.info(f"Heuristics Classified Intent: needs_context = {needs_context}")
    return {"needs_context": needs_context}

def retrieve_node(state: AgentState) -> dict:
    """
    Node B: Performs hybrid search and Cohere rerank, populating context chunks.
    """
    logger.info("Orchestrator: Retrieving candidate context chunks...")
    workspace_id = state["workspace_id"]
    query = state["query"]
    
    # 1. Fetch top 30 candidates via hybrid search
    candidates = retrieval_service.hybrid_search(workspace_id, query, limit=30)
    
    # 2. Rerank top 12 candidates via Cohere rerank
    reranked = retrieval_service.rerank(query, candidates, limit=12)
    
    logger.info(f"Retrieved {len(reranked)} reranked chunks.")
    return {"retrieved_chunks": reranked}

def synthesize_node(state: AgentState) -> dict:
    """
    Node C: Generates the final answer with strict citation mapping.
    """
    logger.info("Orchestrator: Synthesizing final answer...")
    query = state["query"]
    chunks = state.get("retrieved_chunks", [])
    needs_context = state.get("needs_context", False)
    
    if not needs_context or not chunks:
        # If no context was needed or retrieved, either answer generally or instruct
        if config.HAS_OPENAI:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=config.OPENAI_API_KEY)
                messages = [
                    {"role": "system", "content": "You are a helpful research platform assistant. Answer the user query directly and politely."},
                    *state.get("history", []),
                    {"role": "user", "content": query}
                ]
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.7
                )
                return {"response": completion.choices[0].message.content}
            except Exception as e:
                logger.error(f"Direct OpenAI chat synthesis failed: {e}")
                
        # Heuristic general fallback
        return {"response": f"Hi! I am your AI Research assistant. How can I help you manage your workspace documents or search papers today?"}

    # Format chunks context
    formatted_context_list = []
    for idx, c in enumerate(chunks):
        doc_ref = f"Doc ID: {c['document_id']} | Title: {c['doc_title']} | Page: {c['page_number']}"
        formatted_context_list.append(f"[{idx+1}] Source Reference: {doc_ref}\nContent: {c['chunk_text']}")
    
    formatted_context = "\n\n---\n\n".join(formatted_context_list)
    
    system_prompt = (
        """You are an expert research analyst for the AI Research Intelligence Platform. Your primary task is to perform rigorous cross-document synthesis and comparative analysis based exclusively on the provided context chunks.

---

### COMPARATIVE ANALYSIS PROTOCOL

When evaluating queries that compare multiple concepts, methods, or papers, you must:
1. **Identify the Vectors of Comparison:** Establish explicit dimensions for comparison (e.g., core methodology, architectural differences, performance metrics, latency, or hardware constraints).
2. **Synthesize, Do Not Just List:** Do not merely summarize Document A and then Document B. Frame your sentences to contrast them directly (e.g., "While Document A utilizes [X], Document B relies on [Y]").
3. **Address Conflicting Data:** If the source papers present contradictory findings or claims on the same topic, explicitly highlight this divergence as part of your comparative analysis.

---

### CRITICAL INSTRUCTIONS

1. **Strict Context Adherence:** Rely only on the clear facts directly mentioned in the context. Do not assume, extrapolate, or bring in outside knowledge. Any claim not directly supported by the context is a hallucination.
2. **Insufficient Context Protocol:** If the provided context does not contain enough information to compare the concepts definitively across the requested dimensions, state exactly what is missing: "The provided documents do not contain sufficient comparative data to answer this query completely."
3. **Tone and Style:** Maintain an objective, academic, and precise tone. Start directly with the comparative analysis.

---

### CITATION PROTOCOL

You must append a citation immediately after every claim, comparison, or fact derived from the text, before the sentence punctuation. Every side of a comparison must be cited.

* **Standard Format:** [Document Title, p. PageNumber]
* **Missing Page Number:** [Document Title]
* **Multiple Sources:** [Doc A, p. 2; Doc B, p. 5]

---

### CONTEXT CHUNKS
{formatted_context}""")

    if config.HAS_OPENAI:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=config.OPENAI_API_KEY)
            
            messages = [
                {"role": "system", "content": system_prompt},
                *state.get("history", []),
                {"role": "user", "content": query}
            ]
            
            completion = client.uuid = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.2
            )
            response_text = completion.choices[0].message.content
            return {"response": response_text}
        except Exception as e:
            logger.error(f"Context OpenAI chat synthesis failed: {e}. Falling back to rule-based compiler.")

    # Rule-based fallback synthesis (extremely useful for tests/offline execution)
    first_chunk = chunks[0]
    doc_title = first_chunk["doc_title"]
    page_num = first_chunk["page_number"]
    
    fallback_response = (
        f"Based on the document context in this workspace (specifically [{doc_title}, p. {page_num}]), "
        f"the text mentions:\n\n"
        f"\"{first_chunk['chunk_text'][:350]}...\"\n\n"
        f"This information is cited directly from [{doc_title}, p. {page_num}]."
    )
    return {"response": fallback_response}

def route_after_intent(state: AgentState) -> str:
    """
    LangGraph conditional edge router based on intent classification.
    """
    if state.get("needs_context", True):
        return "retrieve"
    else:
        return "synthesize"

# ----------------- Build and Compile Graph -----------------

workflow = StateGraph(AgentState)

workflow.add_node("intent", parse_intent_node)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("synthesize", synthesize_node)

workflow.add_edge(START, "intent")

workflow.add_conditional_edges(
    "intent",
    route_after_intent,
    {
        "retrieve": "retrieve",
        "synthesize": "synthesize"
    }
)

workflow.add_edge("retrieve", "synthesize")
workflow.add_edge("synthesize", END)

orchestrator_graph = workflow.compile()
