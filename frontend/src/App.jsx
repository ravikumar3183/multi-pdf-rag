import { useEffect, useRef, useState } from "react";
import axios from "axios";
import "./App.css";

// Ensure this matches your live Render backend URL
const API_BASE = "https://multi-pdf-rag.onrender.com"; 

function App() {
  const [files, setFiles] = useState([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dbDocs, setDbDocs] = useState([]); 

  const chatEndRef = useRef(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const fetchDocuments = async () => {
    try {
      const res = await axios.get(`${API_BASE}/list_documents`);
      setDbDocs(res.data.documents || []);
    } catch (err) {
      console.error("Error fetching documents:", err);
    }
  };

  const handleDelete = async (docId, docName) => {
    if (!window.confirm(`Delete "${docName}"?`)) return;
    try {
      await axios.delete(`${API_BASE}/delete_document/${docId}`);
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
      alert("Please select a PDF first.");
      return;
    }
    try {
      setUploading(true);
      setUploadStatus("Uploading...");
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));

      const res = await axios.post(`${API_BASE}/upload_pdfs`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setUploadStatus("Done!");
      setFiles([]); 
      fetchDocuments();
      setTimeout(() => setUploadStatus(""), 2000); // Clear status after 2s

    } catch (err) {
      console.error("Upload error:", err.response?.data || err.message);
      setUploadStatus("Failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);

    const newMessages = [...messages, { role: "user", text: question }];
    setMessages(newMessages);
    setQuestion(""); // Clear input immediately

    try {
      const res = await axios.post(`${API_BASE}/ask`, { question });
      const answer = res.data.answer || "No answer returned.";
      setMessages((prev) => [...prev, { role: "assistant", text: answer }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "Error connecting to server." },
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
        
        {/* HEADER */}
        <header className="app-header">
          <div className="brand">
            <span className="logo-icon">⚡</span>
            <h1>RAG Chatbot</h1>
          </div>
          <span className="model-badge">Gemini 2.0 Flash</span>
        </header>

        <main className="app-main">
          
          {/* LEFT SIDEBAR */}
          <section className="panel upload-panel">
            <div>
              <h2>Knowledge Base</h2>
              <p style={{fontSize: "0.8rem", color: "#a1a1aa", marginBottom: "15px"}}>
                Upload PDFs to chat with them.
              </p>

              <div style={{display: "flex", gap: "10px", marginBottom: "10px"}}>
                <label className="file-input-label">
                  {files.length > 0 ? `${files.length} files` : "+ Select PDF"}
                  <input type="file" accept="application/pdf" multiple onChange={handleFileChange} />
                </label>
                <button className="primary-btn" onClick={handleUpload} disabled={uploading || !files.length} style={{width: "auto"}}>
                  {uploading ? "..." : "↑"}
                </button>
              </div>
              
              {uploadStatus && <div style={{fontSize: "0.8rem", color: "#6366f1"}}>{uploadStatus}</div>}
            </div>

            <div className="file-list-db">
              {dbDocs.length === 0 ? (
                <div style={{textAlign: "center", color: "#3f3f46", fontSize: "0.85rem", marginTop: "20px"}}>
                  No documents found.
                </div>
              ) : (
                dbDocs.map((doc) => (
                  <div key={doc.id} className="db-file-row">
                    <div className="file-info">
                      <span>📄</span>
                      <span className="file-name" title={doc.filename}>{doc.filename}</span>
                    </div>
                    <button onClick={() => handleDelete(doc.id, doc.filename)} className="delete-btn">×</button>
                  </div>
                ))
              )}
            </div>
          </section>

          {/* RIGHT MAIN CHAT */}
          <section className="panel chat-panel">
            <div className="chat-window">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <h1>What can I help you find?</h1>
                  <p>Ask questions about your {dbDocs.length} uploaded documents.</p>
                </div>
              )}

              {messages.map((m, idx) => (
                <div key={idx} className={`message-row role-${m.role}`}>
                  <div className="message-avatar">
                    {m.role === "user" ? "👤" : "✨"}
                  </div>
                  <div className="message-content">{m.text}</div>
                </div>
              ))}

              {loading && (
                <div className="message-row role-assistant">
                  <div className="message-avatar">✨</div>
                  <div className="message-content">Thinking...</div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className="chat-input-container">
              <div className="chat-input-wrapper">
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask a question..."
                  rows={1}
                />
                <button className="send-btn" onClick={handleAsk} disabled={loading || !question.trim()}>
                  ➜
                </button>
              </div>
            </div>
          </section>

        </main>
      </div>
    </div>
  );
}

export default App;