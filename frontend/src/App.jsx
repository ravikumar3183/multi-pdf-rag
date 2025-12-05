import { useEffect, useRef, useState } from "react";
import axios from "axios";
import "./App.css";

const API_BASE = "https://multi-pdf-rag.onrender.com";

function App() {
  const [files, setFiles] = useState([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Stores objects: [{id: 1, filename: "abc.pdf"}, ...]
  const [dbDocs, setDbDocs] = useState([]); 

  const chatEndRef = useRef(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const fetchDocuments = async () => {
    try {
      const res = await axios.get(`${API_BASE}/list_documents`);
      // Backend now returns a list of objects {id, filename}
      setDbDocs(res.data.documents || []);
    } catch (err) {
      console.error("Error fetching documents:", err);
    }
  };

  // --- NEW: Handle Delete ---
  const handleDelete = async (docId, docName) => {
    if (!window.confirm(`Are you sure you want to delete "${docName}"?`)) return;

    try {
      await axios.delete(`${API_BASE}/delete_document/${docId}`);
      // Remove from UI immediately
      setDbDocs((prev) => prev.filter((d) => d.id !== docId));
    } catch (err) {
      console.error("Delete failed:", err);
      alert("Failed to delete document.");
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  useEffect(() => {
    fetchDocuments();
  }, []);

  const handleFileChange = (e) => {
    setFiles(Array.from(e.target.files));
    setUploadStatus("");
  };

  const handleUpload = async () => {
    if (!files.length) {
      alert("Please choose at least one PDF");
      return;
    }
    try {
      setUploading(true);
      setUploadStatus("Uploading & indexing PDFs...");
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));

      const res = await axios.post(`${API_BASE}/upload_pdfs`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setUploadStatus(res.data.message || "Upload complete!");
      setFiles([]); 
      fetchDocuments();

    } catch (err) {
      console.error("Upload error:", err.response?.data || err.message);
      setUploadStatus("Error uploading PDFs");
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);

    const newMessages = [...messages, { role: "user", text: question }];
    setMessages(newMessages);

    try {
      const res = await axios.post(`${API_BASE}/ask`, { question });
      const answer = res.data.answer || "(No answer)";
      setMessages([
        ...newMessages,
        { role: "assistant", text: answer },
      ]);
      setQuestion("");
    } catch (err) {
      console.error(err);
      setMessages([
        ...newMessages,
        {
          role: "assistant",
          text: "Error retrieving answer from backend.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAsk();
    }
  };

  return (
    <div className="app-root">
      <div className="app-shell">
        <header className="app-header">
          <div className="logo-pill">
            <span className="logo-icon">📚</span>
          </div>
          <div>
            <h1>Multi-PDF RAG Chatbot</h1>
            <p className="subtitle">
              Ask questions across all your PDFs using hybrid search + Gemini.
            </p>
          </div>
        </header>

        <main className="app-main">
          <section className="panel upload-panel">
            <h2>1. Upload PDFs</h2>
            <p className="panel-subtitle">
              Select one or more PDF files and index them into the knowledge base.
            </p>

            <div className="upload-row">
              <label className="file-input-label">
                Choose Files
                <input
                  type="file"
                  accept="application/pdf"
                  multiple
                  onChange={handleFileChange}
                />
              </label>

              <button
                className="primary-btn"
                onClick={handleUpload}
                disabled={uploading || !files.length}
              >
                {uploading ? "Indexing..." : "Upload & Index"}
              </button>
            </div>

            {files.length > 0 && (
              <div className="file-list">
                <p style={{fontSize: "0.8rem", color: "#666"}}>Selected to upload:</p>
                {files.map((f) => (
                  <span key={f.name} className="file-pill">
                    {f.name}
                  </span>
                ))}
              </div>
            )}

            {uploadStatus && (
              <p
                className={
                  uploadStatus.startsWith("Error")
                    ? "status status-error"
                    : "status status-ok"
                }
              >
                {uploadStatus}
              </p>
            )}

            <hr className="divider" />
            
            {/* UPDATED KNOWLEDGE BASE SECTION */}
            <h3>📚 Knowledge Base ({dbDocs.length})</h3>
            <div className="file-list-db">
                {dbDocs.length === 0 ? (
                    <p style={{color: "#888", fontSize: "0.9rem"}}>No documents indexed yet.</p>
                ) : (
                    dbDocs.map((doc) => (
                        <div key={doc.id} className="db-file-row">
                            <div style={{display:"flex", alignItems:"center", gap:"8px"}}>
                              <span className="file-icon">📄</span>
                              <span className="file-name">{doc.filename}</span>
                            </div>
                            {/* Delete Button */}
                            <button 
                              onClick={() => handleDelete(doc.id, doc.filename)}
                              className="delete-btn"
                              title="Delete this document"
                            >
                              🗑️
                            </button>
                        </div>
                    ))
                )}
            </div>

          </section>

          <section className="panel chat-panel">
            <h2>2. Ask Questions</h2>
            <p className="panel-subtitle">
              Your questions will be answered using only the uploaded PDFs.
            </p>

            <div className="chat-window">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <p>💡 Try asking:</p>
                  <ul>
                    <li>“Summarise the main ideas from these notes.”</li>
                    <li>“What is Lyapunov-Floquet theory?”</li>
                    <li>“Explain eigenvalues in simple terms.”</li>
                  </ul>
                </div>
              )}

              {messages.map((m, idx) => (
                <div
                  key={idx}
                  className={`message-row ${
                    m.role === "user" ? "align-right" : "align-left"
                  }`}
                >
                  <div
                    className={`message-bubble ${
                      m.role === "user" ? "user" : "assistant"
                    }`}
                  >
                    <div className="message-meta">
                      {m.role === "user" ? "You" : "AI"}
                    </div>
                    <div className="message-text">{m.text}</div>
                  </div>
                </div>
              ))}

              {loading && (
                <div className="message-row align-left">
                  <div className="message-bubble assistant">
                    <div className="message-meta">AI</div>
                    <div className="typing-indicator">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                </div>
              )}

              <div ref={chatEndRef} />
            </div>

            <div className="chat-input-row">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask something about your uploaded PDFs..."
                rows={3}
              />
              <button
                className="primary-btn"
                onClick={handleAsk}
                disabled={loading || !question.trim()}
              >
                {loading ? "Asking..." : "Ask"}
              </button>
            </div>
          </section>
        </main>

        <footer className="app-footer">
          <span>Built with FastAPI · PostgreSQL + pgvector · React · Gemini</span>
        </footer>
      </div>
    </div>
  );
}

export default App;