/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */
"use client";

import { useState, useEffect, useRef } from "react";
import MathMarkdownRenderer from "./MathMarkdownRenderer";
import "katex/dist/katex.min.css";

export default function Dashboard() {
  // App States
  const [workspaces, setWorkspaces] = useState([]);
  const [activeWorkspace, setActiveWorkspace] = useState(null);
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [documents, setDocuments] = useState([]);
  const [chatHistory, setChatHistory] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [streamCitations, setStreamCitations] = useState([]);
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [showHelpModal, setShowHelpModal] = useState(false);

  // Refs for UI
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  const API_BASE = "http://localhost:8000";

  // API Call: List Workspaces
  const fetchWorkspaces = async () => {
    try {
      const res = await fetch(`${API_BASE}/workspaces`);
      if (res.ok) {
        const data = await res.json();
        setWorkspaces(data);
        if (data.length > 0 && !activeWorkspace) {
          setActiveWorkspace(data[0]); // Auto-select first workspace
        }
      }
    } catch (err) {
      console.error("Failed to fetch workspaces:", err);
    }
  };

  // API Call: List Documents
  const fetchDocuments = async (workspaceId) => {
    try {
      const res = await fetch(`${API_BASE}/workspaces/${workspaceId}/documents`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data);
      }
    } catch (err) {
      console.error("Failed to fetch documents:", err);
    }
  };

  // 1. Fetch all workspaces on mount
  useEffect(() => {
    fetchWorkspaces();
  }, []);

  // 2. Fetch documents when active workspace changes
  useEffect(() => {
    if (activeWorkspace) {
      fetchDocuments(activeWorkspace.id);
      setChatHistory([]); // Clear chat history for new workspace
      setStreamText("");
      setStreamCitations([]);
    } else {
      setDocuments([]);
    }
  }, [activeWorkspace]);

  // 3. Document status polling loop
  useEffect(() => {
    if (!activeWorkspace) return;

    // Check if any document is in 'processing' status
    const hasProcessing = documents.some((doc) => doc.status === "processing");
    if (!hasProcessing) return;

    // Poll every 3 seconds
    const interval = setInterval(() => {
      fetchDocuments(activeWorkspace.id);
    }, 3000);

    return () => clearInterval(interval);
  }, [documents, activeWorkspace]);

  // 4. Scroll to bottom of chat logs
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, streamText]);

  // API Call: Create Workspace
  const handleCreateWorkspace = async (e) => {
    e.preventDefault();
    if (!newWorkspaceName.trim()) return;

    try {
      const res = await fetch(`${API_BASE}/workspaces?name=${encodeURIComponent(newWorkspaceName)}`, {
        method: "POST",
      });
      if (res.ok) {
        const newWs = await res.json();
        setWorkspaces([newWs, ...workspaces]);
        setActiveWorkspace(newWs);
        setNewWorkspaceName("");
      }
    } catch (err) {
      console.error("Failed to create workspace:", err);
    }
  };

  // API Call: Upload PDF File
  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !activeWorkspace) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      alert("Only PDF files are supported.");
      return;
    }

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/workspaces/${activeWorkspace.id}/documents`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        // Refresh document list
        fetchDocuments(activeWorkspace.id);
      } else {
        const errorData = await res.json();
        alert(`Upload failed: ${errorData.detail || "Unknown error"}`);
      }
    } catch (err) {
      console.error("Upload failed:", err);
      alert("An error occurred during file upload.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = ""; // Reset file input
    }
  };

  // API Call: Chat Stream Submission
  const handleChatSubmit = async (e) => {
    e.preventDefault();
    if (!inputValue.trim() || !activeWorkspace || isStreaming) return;

    const userQuery = inputValue;
    setInputValue("");
    setIsStreaming(true);
    setStreamText("");
    setStreamCitations([]);

    // 1. Optimistically add user query to history
    const userMessage = { role: "user", content: userQuery };
    setChatHistory((prev) => [...prev, userMessage]);

    try {
      // 2. Open Stream Connection
      const res = await fetch(`${API_BASE}/workspaces/${activeWorkspace.id}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: userQuery,
          history: chatHistory.slice(-6), // Keep history payload light
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned error status: ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let accumulatedText = "";
      let citations = [];

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          const chunk = decoder.decode(value, { stream: !done });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const dataStr = line.slice(6).trim();
              if (dataStr === "[DONE]") {
                break;
              }
              try {
                const parsed = JSON.parse(dataStr);
                if (parsed.citations !== undefined) {
                  citations = parsed.citations;
                  setStreamCitations(parsed.citations);
                } else if (parsed.token !== undefined) {
                  accumulatedText += parsed.token;
                  setStreamText(accumulatedText);
                }
              } catch (parseErr) {
                // Ignore incomplete JSONs resulting from chunk division
              }
            }
          }
        }
      }

      // 3. Commit streamed assistant response to chat logs
      setChatHistory((prev) => [
        ...prev,
        { role: "assistant", content: accumulatedText, citations: citations },
      ]);
      setStreamText("");
      setStreamCitations([]);

    } catch (err) {
      console.error("Chat streaming failed:", err);
      setChatHistory((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, I encountered an error while processing your request.",
          citations: [],
        },
      ]);
    } finally {
      setIsStreaming(false);
    }
  };

  return (
    <div className="flex h-screen w-screen bg-[#0e1013] text-zinc-150 font-sans overflow-hidden">
      
      {/* 1. SIDEBAR: Workspaces & Workspace Creation */}
      <aside className="w-80 border-r border-zinc-800/80 bg-zinc-900/30 flex flex-col h-full shrink-0">
        {/* App Logo */}
        <div className="p-6 border-b border-zinc-800/80 flex flex-col items-start gap-1">
          <div className="flex items-center gap-2">
            <span className="text-xl font-serif font-medium text-white tracking-wide">
              ResearchAI
            </span>
            <span className="text-[9px] uppercase font-mono tracking-widest text-emerald-500 px-1.5 py-0.5 border border-emerald-500/20 bg-emerald-500/5 rounded">
              Platform
            </span>
          </div>
          <span className="text-[10px] text-zinc-500">Scientific Paper Hybrid RAG</span>
        </div>

        {/* Create Workspace Form */}
        <form onSubmit={handleCreateWorkspace} className="p-4 border-b border-zinc-800/80">
          <label className="block text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            New Workspace
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={newWorkspaceName}
              onChange={(e) => setNewWorkspaceName(e.target.value)}
              placeholder="Workspace name..."
              className="flex-1 bg-zinc-950 border border-zinc-850 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-emerald-600/60 transition-colors"
            />
            <button
              type="submit"
              className="bg-emerald-750 hover:bg-emerald-700 text-white rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors flex items-center justify-center cursor-pointer"
            >
              +
            </button>
          </div>
        </form>

        {/* Workspaces List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          <span className="block text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider mb-3">
            Workspaces
          </span>
          {workspaces.length === 0 ? (
            <div className="text-xs text-zinc-600 italic p-2">No workspaces. Create one above to get started.</div>
          ) : (
            workspaces.map((ws) => (
              <button
                key={ws.id}
                onClick={() => setActiveWorkspace(ws)}
                className={`w-full text-left p-3 rounded-xl transition-all duration-200 flex items-center justify-between border ${
                  activeWorkspace?.id === ws.id
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400 font-medium"
                    : "bg-zinc-950/40 border-transparent text-zinc-400 hover:bg-zinc-850/40 hover:text-zinc-200"
                }`}
              >
                <div className="flex items-center gap-3 truncate">
                  <div className={`h-2.5 w-2.5 rounded-full ${
                    activeWorkspace?.id === ws.id ? "bg-emerald-400" : "bg-zinc-700"
                  }`} />
                  <span className="truncate">{ws.name}</span>
                </div>
                <span className="text-[10px] text-zinc-600 font-mono">ID: {ws.id}</span>
              </button>
            ))
          )}
        </div>

        {/* Drag & Drop File Upload */}
        {activeWorkspace && (
          <div className="p-4 border-t border-zinc-800/80 bg-zinc-950/20">
            <div
              onClick={() => fileInputRef.current?.click()}
              className={`border border-dashed rounded-xl p-4 text-center cursor-pointer transition-colors ${
                isUploading
                  ? "border-yellow-500/50 bg-yellow-500/5 text-yellow-500"
                  : "border-zinc-850 hover:border-emerald-500/30 hover:bg-emerald-500/5 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".pdf"
                className="hidden"
                disabled={isUploading}
              />
              <div className="text-2xl mb-1">{isUploading ? "⚡" : "📤"}</div>
              <div className="text-xs font-semibold">
                {isUploading ? "Uploading & Ingesting..." : "Upload Research PDF"}
              </div>
              <div className="text-[10px] text-zinc-600 mt-1">PDF documents only</div>
            </div>
          </div>
        )}
      </aside>

      {/* 2. CHAT PANEL (Main Panel) */}
      <main className="flex-1 flex flex-col h-full bg-[#0e1013] relative">
        {/* Workspace Active Header */}
        <header className="h-20 border-b border-zinc-800/80 px-8 flex items-center justify-between bg-zinc-950/20">
          <div>
            <h2 className="text-base font-serif font-medium text-white">
              {activeWorkspace ? activeWorkspace.name : "Select a Workspace"}
            </h2>
            <p className="text-[11px] text-zinc-500">
              {activeWorkspace ? `Connected to workspace node ID: ${activeWorkspace.id}` : "Choose a workspace from the sidebar"}
            </p>
          </div>
          <div className="flex items-center gap-4">
            {activeWorkspace && (
              <button
                onClick={() => setShowHelpModal(true)}
                className="text-[11px] font-mono px-3 py-1.5 border border-zinc-850 hover:border-emerald-500/30 text-zinc-400 hover:text-emerald-400 rounded-lg bg-zinc-950/40 hover:bg-emerald-950/5 transition-all cursor-pointer"
              >
                ℹ️ Platform Documentation
              </button>
            )}
            {isStreaming && (
              <div className="flex items-center gap-2 px-3 py-1 bg-emerald-500/5 border border-emerald-500/20 rounded-full text-[11px] text-emerald-400 font-medium">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
                Processing
              </div>
            )}
          </div>
        </header>

        {/* Message Logs */}
        <section className="flex-1 overflow-y-auto p-8 space-y-6 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
          {chatHistory.length === 0 && !streamText && (
            <div className="h-full flex flex-col justify-center max-w-2xl mx-auto py-12 px-4 overflow-y-auto">
              <div className="mb-8">
                <span className="text-[10px] uppercase font-mono tracking-widest text-emerald-400 font-semibold block mb-2">Workspace Assistant</span>
                <h1 className="text-3xl font-serif font-medium text-white mb-3">
                  ResearchAI Paper Synthesis
                </h1>
                <p className="text-sm text-zinc-400 leading-relaxed max-w-xl">
                  This workspace uses hybrid vector search, Reciprocal Rank Fusion (RRF), and Cohere rerankers to perform deep comparative synthesis of uploaded PDFs.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
                <div className="p-5 border border-zinc-800/80 bg-zinc-900/20 rounded-xl hover:border-zinc-700/50 transition-colors">
                  <div className="text-sm text-white font-medium mb-1.5 flex items-center gap-2">
                    <span>⚡</span> <span>Hybrid Retrieval</span>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Combines dense pgvector semantic similarity with sparse keyword indexing, merging results via Reciprocal Rank Fusion (RRF).
                  </p>
                </div>
                
                <div className="p-5 border border-zinc-800/80 bg-zinc-900/20 rounded-xl hover:border-zinc-700/50 transition-colors">
                  <div className="text-sm text-white font-medium mb-1.5 flex items-center gap-2">
                    <span>⚖️</span> <span>Document Diversification</span>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Applies a round-robin diversification filter to guarantee that all papers in the workspace are represented, avoiding single-paper crowding.
                  </p>
                </div>

                <div className="p-5 border border-zinc-800/80 bg-zinc-900/20 rounded-xl hover:border-zinc-700/50 transition-colors">
                  <div className="text-sm text-white font-medium mb-1.5 flex items-center gap-2">
                    <span>🎯</span> <span>Cohere Reranking</span>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Candidates are passed through {"Cohere's"} deep rerank-english-v3.0 model to score relevance and exclude irrelevant noise.
                  </p>
                </div>

                <div className="p-5 border border-zinc-800/80 bg-zinc-900/20 rounded-xl hover:border-zinc-700/50 transition-colors">
                  <div className="text-sm text-white font-medium mb-1.5 flex items-center gap-2">
                    <span>📝</span> <span>Verifiable Citations</span>
                  </div>
                  <p className="text-xs text-zinc-500 leading-relaxed">
                    Generates responses with strict citation mappings `[Title, p. Page]`. Click citation chips below messages to view context details.
                  </p>
                </div>
              </div>

              <div className="border-t border-zinc-800/60 pt-6">
                <span className="text-xs font-mono text-zinc-400 block mb-3">To get started:</span>
                <ol className="list-decimal pl-5 text-xs text-zinc-500 space-y-2 leading-relaxed">
                  <li>Select or create a workspace using the sidebar.</li>
                  <li>Upload scientific PDF files in the sidebar upload zone.</li>
                  <li>Ask comparative questions in the chat box (e.g. *Compare architecture parameters across the papers*).</li>
                </ol>
              </div>
            </div>
          )}

          {/* Render Chats */}
          {chatHistory.map((msg, index) => (
            <div
              key={index}
              className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
            >
              <div
                className={`max-w-xl rounded-2xl p-4 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-emerald-950/60 border border-emerald-800/50 text-zinc-100 rounded-tr-none shadow-md shadow-emerald-950/10 font-medium"
                    : "bg-zinc-900/50 border border-zinc-850 text-zinc-100 rounded-tl-none"
                }`}
              >
                {msg.role === "user" ? (
                  msg.content
                ) : (
                  <MathMarkdownRenderer content={msg.content} />
                )}
                
                {/* Render Citations under Assistant Message */}
                {msg.role === "assistant" && msg.citations && msg.citations.length > 0 && (
                  <div className="mt-3.5 pt-3.5 border-t border-zinc-850 flex flex-wrap gap-2">
                    <span className="text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider block w-full mb-1">
                      Verified Sources:
                    </span>
                    {msg.citations.map((cite, cIdx) => (
                      <button
                        key={cIdx}
                        onClick={() => setSelectedCitation(cite)}
                        className="bg-zinc-950 hover:bg-zinc-900 border border-zinc-800/80 hover:border-emerald-500/30 text-zinc-400 hover:text-emerald-450 text-[11px] px-2.5 py-1 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer"
                      >
                        📄 {cite.doc_title} (p. {cite.page_number})
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Render Active Stream Output */}
          {streamText && (
            <div className="flex flex-col items-start">
              <div className="max-w-xl rounded-2xl rounded-tl-none p-4 text-sm leading-relaxed bg-zinc-900/50 border border-zinc-850 text-zinc-100">
                <MathMarkdownRenderer content={streamText} />
                <span className="inline-block h-3 w-1.5 ml-1 bg-emerald-500 animate-pulse" />
                
                {/* Render active citations (first chunk) */}
                {streamCitations.length > 0 && (
                  <div className="mt-3.5 pt-3.5 border-t border-zinc-850 flex flex-wrap gap-2">
                    <span className="text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider block w-full mb-1">
                      Context Loaded:
                    </span>
                    {streamCitations.map((cite, cIdx) => (
                      <div
                        key={cIdx}
                        className="bg-zinc-950 border border-zinc-800/80 text-zinc-500 text-[11px] px-2.5 py-1 rounded-lg flex items-center gap-1.5"
                      >
                        📄 {cite.doc_title} (p. {cite.page_number})
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </section>

        {/* Chat Query Form */}
        {activeWorkspace && (
          <form onSubmit={handleChatSubmit} className="p-6 border-t border-zinc-800/80 bg-zinc-950/20">
            <div className="relative flex items-center">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="Ask about workspace research papers..."
                disabled={isStreaming}
                className="w-full bg-zinc-900/40 border border-zinc-800/80 rounded-xl pl-5 pr-14 py-4 text-sm text-zinc-100 placeholder-zinc-655 focus:outline-none focus:border-emerald-600/60 transition-colors disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={isStreaming || !inputValue.trim()}
                className="absolute right-3 bg-emerald-750 hover:bg-emerald-700 disabled:bg-zinc-850 text-white p-2.5 rounded-lg text-sm font-semibold transition-colors flex items-center justify-center disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
              >
                ➔
              </button>
            </div>
          </form>
        )}
      </main>

      {/* 3. DOCUMENT PANEL (Right Panel) */}
      <aside className="w-80 border-l border-zinc-800/80 bg-zinc-900/30 flex flex-col h-full shrink-0">
        <div className="p-6 border-b border-zinc-800/80">
          <h3 className="text-xs font-mono font-bold text-white uppercase tracking-wider">Document Library</h3>
          <p className="text-[11px] text-zinc-500">Indexed workspace research papers</p>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
          {documents.length === 0 ? (
            <div className="text-xs text-zinc-600 italic p-2 text-center mt-10">
              No documents in this workspace. Upload PDFs via the sidebar.
            </div>
          ) : (
            documents.map((doc) => (
              <div
                key={doc.id}
                className="p-3.5 bg-zinc-950/40 border border-zinc-850 rounded-xl flex flex-col gap-2"
              >
                <div className="font-semibold text-xs text-white truncate" title={doc.title}>
                  {doc.title}
                </div>
                <div className="flex items-center justify-between text-[10px] text-zinc-500">
                  <span>ID: {doc.id}</span>
                  <span>{new Date(doc.created_at).toLocaleDateString()}</span>
                </div>
                
                {/* Status Badges */}
                <div className="flex items-center justify-between pt-1 border-t border-zinc-850 mt-1">
                  <span className="text-[10px] text-zinc-650">Status</span>
                  {doc.status === "processing" && (
                    <span className="flex items-center gap-1.5 text-[10px] text-yellow-400 bg-yellow-400/5 px-2 py-0.5 rounded-full border border-yellow-400/25 animate-pulse font-medium">
                      <span className="h-1.5 w-1.5 rounded-full bg-yellow-400 animate-ping" />
                      Processing
                    </span>
                  )}
                  {doc.status === "ready" && (
                    <span className="flex items-center gap-1.5 text-[10px] text-teal-400 bg-teal-400/5 px-2 py-0.5 rounded-full border border-teal-400/20 font-medium">
                      ✓ Ready
                    </span>
                  )}
                  {doc.status === "failed" && (
                    <span className="flex items-center gap-1.5 text-[10px] text-red-400 bg-red-400/5 px-2 py-0.5 rounded-full border border-red-400/20 font-medium">
                      ✕ Failed
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Citation Details Modal (Tooltip overlay) */}
      {selectedCitation && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-900 border border-zinc-850 rounded-2xl w-full max-w-md p-6 relative shadow-2xl">
            <button
              onClick={() => setSelectedCitation(null)}
              className="absolute top-4 right-4 text-zinc-500 hover:text-zinc-300 text-lg cursor-pointer"
            >
              ✕
            </button>
            <h4 className="text-sm font-serif font-bold text-emerald-400 tracking-wider mb-2">
              Source Citation Inspector
            </h4>
            <div className="space-y-4 mt-4">
              <div>
                <label className="text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider block">Document Title</label>
                <div className="text-sm text-white font-medium mt-1">{selectedCitation.doc_title}</div>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider block">Doc ID</label>
                  <div className="text-sm text-white font-semibold mt-0.5">{selectedCitation.document_id}</div>
                </div>
                <div>
                  <label className="text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider block">Page Number</label>
                  <div className="text-sm text-white font-semibold mt-0.5">{selectedCitation.page_number}</div>
                </div>
                <div>
                  <label className="text-[10px] font-mono font-semibold text-zinc-500 uppercase tracking-wider block">Chunk index</label>
                  <div className="text-sm text-white font-semibold mt-0.5">{selectedCitation.chunk_index}</div>
                </div>
              </div>
            </div>
            <button
              onClick={() => setSelectedCitation(null)}
              className="mt-6 w-full bg-zinc-950 hover:bg-zinc-850 border border-zinc-800 text-zinc-300 py-2.5 rounded-xl text-sm font-semibold transition-colors cursor-pointer"
            >
              Close Inspector
            </button>
          </div>
        </div>
      )}

      {/* Platform Architecture & Help Modal */}
      {showHelpModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-900 border border-zinc-850 rounded-2xl w-full max-w-xl p-6 relative shadow-2xl overflow-y-auto max-h-[85vh]">
            <button
              onClick={() => setShowHelpModal(false)}
              className="absolute top-4 right-4 text-zinc-500 hover:text-zinc-300 text-lg cursor-pointer"
            >
              ✕
            </button>
            
            <span className="text-[10px] uppercase font-mono tracking-widest text-emerald-400 font-semibold block mb-1">
              Technical Documentation
            </span>
            <h3 className="text-xl font-serif font-medium text-white mb-4">
              ResearchAI System Architecture
            </h3>
            
            <div className="space-y-6 mt-4 text-sm text-zinc-300">
              <div className="p-4 rounded-xl bg-zinc-950/40 border border-zinc-850">
                <h4 className="font-semibold text-white text-xs uppercase tracking-wider mb-2 text-emerald-450">
                  1. Local PDF Ingestion & In-Memory Parsing
                </h4>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  When a PDF is uploaded, the FastAPI backend delegates the parsing task to an asynchronous RQ worker. The worker uses PyMuPDF (fitz) to extract text and layout page details. Text is chunked with page numbers and stored in PostgreSQL.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-zinc-950/40 border border-zinc-850">
                <h4 className="font-semibold text-white text-xs uppercase tracking-wider mb-2 text-emerald-450">
                  2. Hybrid RRF Retrieval
                </h4>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  To find information, the system performs a dual-search:
                  <br />
                  • <strong>Dense Search:</strong> Vector embeddings (OpenAI `text-embedding-3-small` or local fallback) are matched using pgvector cosine similarity.
                  <br />
                  • <strong>Sparse Search:</strong> PostgreSQL Full-Text Search (plainto_tsquery).
                  <br />
                  Both results are fused using <strong>Reciprocal Rank Fusion (RRF)</strong> to balance semantic and exact keyword signals.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-zinc-950/40 border border-zinc-850">
                <h4 className="font-semibold text-white text-xs uppercase tracking-wider mb-2 text-emerald-450">
                  3. Reranking & Diversity Filter
                </h4>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  The top 30 candidate chunks are passed to the <strong>Cohere Reranker</strong>. Chunks are filtered by a query-relative relevance threshold. We then apply a <strong>round-robin document diversity filter</strong> so that no single document dominates the prompt context, allowing accurate comparative synthesis.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-zinc-950/40 border border-zinc-850">
                <h4 className="font-semibold text-white text-xs uppercase tracking-wider mb-2 text-emerald-450">
                  4. Citation-Backed LLM Synthesis
                </h4>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  The top 12 diversified relevant chunks are formatted into the system context. The LLM (gpt-4o-mini) is instructed under a strict citation protocol to verify all assertions against the source blocks and append citations in `[Title, p. Page]` format.
                </p>
              </div>
            </div>

            <button
              onClick={() => setShowHelpModal(false)}
              className="mt-6 w-full bg-emerald-750 hover:bg-emerald-700 border border-emerald-800 text-white py-2.5 rounded-xl text-sm font-semibold transition-all cursor-pointer"
            >
              Close Documentation
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
