// import { useEffect, useRef, useState } from "react";
// import axios from "axios";
// import "./App.css";

// // Ensure this matches your live Render backend URL
// const API_BASE = "https://multi-pdf-rag.onrender.com"; 

// function App() {
//   const [files, setFiles] = useState([]);
//   const [uploadStatus, setUploadStatus] = useState("");
//   const [question, setQuestion] = useState("");
//   const [messages, setMessages] = useState([]);
//   const [loading, setLoading] = useState(false);
//   const [uploading, setUploading] = useState(false);
//   const [dbDocs, setDbDocs] = useState([]); 

//   const chatEndRef = useRef(null);

//   const scrollToBottom = () => {
//     chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
//   };

//   const fetchDocuments = async () => {
//     try {
//       const res = await axios.get(`${API_BASE}/list_documents`);
//       setDbDocs(res.data.documents || []);
//     } catch (err) {
//       console.error("Error fetching documents:", err);
//     }
//   };

//   const handleDelete = async (docId, docName) => {
//     if (!window.confirm(`Delete "${docName}"?`)) return;
//     try {
//       await axios.delete(`${API_BASE}/delete_document/${docId}`);
//       setDbDocs((prev) => prev.filter((d) => d.id !== docId));
//     } catch (err) {
//       console.error("Delete failed:", err);
//       alert("Failed to delete document.");
//     }
//   };

//   useEffect(() => {
//     scrollToBottom();
//   }, [messages, loading]);

//   useEffect(() => {
//     fetchDocuments();
//   }, []);

//   const handleFileChange = (e) => {
//     setFiles(Array.from(e.target.files));
//     setUploadStatus("");
//   };

//   const handleUpload = async () => {
//     if (!files.length) {
//       alert("Please select a PDF first.");
//       return;
//     }
//     try {
//       setUploading(true);
//       setUploadStatus("Uploading...");
//       const formData = new FormData();
//       files.forEach((file) => formData.append("files", file));

//       const res = await axios.post(`${API_BASE}/upload_pdfs`, formData, {
//         headers: { "Content-Type": "multipart/form-data" },
//       });

//       setUploadStatus("Done!");
//       setFiles([]); 
//       fetchDocuments();
//       setTimeout(() => setUploadStatus(""), 2000); // Clear status after 2s

//     } catch (err) {
//       console.error("Upload error:", err.response?.data || err.message);
//       setUploadStatus("Failed.");
//     } finally {
//       setUploading(false);
//     }
//   };

//   const handleAsk = async () => {
//     if (!question.trim()) return;
//     setLoading(true);

//     const newMessages = [...messages, { role: "user", text: question }];
//     setMessages(newMessages);
//     setQuestion("");

//     try {
//       const res = await axios.post(`${API_BASE}/ask`, { question });
      
//       // We now receive "answer" AND "sources"
//       const answer = res.data.answer || "No answer returned.";
//       const sources = res.data.sources || []; // Capture sources

//       setMessages((prev) => [
//         ...prev,
//         { role: "assistant", text: answer, sources: sources }, // Save sources in message
//       ]);
//     } catch (err) {
//       setMessages((prev) => [
//         ...prev,
//         { role: "assistant", text: "Error connecting to server." },
//       ]);
//     } finally {
//       setLoading(false);
//     }
//   };

//   const handleKeyDown = (e) => {
//     if (e.key === "Enter" && !e.shiftKey) {
//       e.preventDefault();
//       handleAsk();
//     }
//   };

//   return (
//     <div className="app-root">
//       <div className="app-shell">
        
//         {/* HEADER */}
//         <header className="app-header">
//           <div className="brand">
//             <span className="logo-icon">⚡</span>
//             <h1>RAG Chatbot</h1>
//           </div>
//           <span className="model-badge">Gemini 2.0 Flash</span>
//         </header>

//         <main className="app-main">
          
//           {/* LEFT SIDEBAR */}
//           <section className="panel upload-panel">
//             <div>
//               <h2>Knowledge Base</h2>
//               <p style={{fontSize: "0.8rem", color: "#a1a1aa", marginBottom: "15px"}}>
//                 Upload PDFs to chat with them.
//               </p>

//               <div style={{display: "flex", gap: "10px", marginBottom: "10px"}}>
//                 <label className="file-input-label">
//                   {files.length > 0 ? `${files.length} files` : "+ Select PDF"}
//                   <input type="file" accept="application/pdf" multiple onChange={handleFileChange} />
//                 </label>
//                 <button className="primary-btn" onClick={handleUpload} disabled={uploading || !files.length} style={{width: "auto"}}>
//                   {uploading ? "..." : "↑"}
//                 </button>
//               </div>
              
//               {uploadStatus && <div style={{fontSize: "0.8rem", color: "#6366f1"}}>{uploadStatus}</div>}
//             </div>

//             <div className="file-list-db">
//               {dbDocs.length === 0 ? (
//                 <div style={{textAlign: "center", color: "#3f3f46", fontSize: "0.85rem", marginTop: "20px"}}>
//                   No documents found.
//                 </div>
//               ) : (
//                 dbDocs.map((doc) => (
//                   <div key={doc.id} className="db-file-row">
//                     <div className="file-info">
//                       <span>📄</span>
//                       <span className="file-name" title={doc.filename}>{doc.filename}</span>
//                     </div>
//                     <button onClick={() => handleDelete(doc.id, doc.filename)} className="delete-btn">×</button>
//                   </div>
//                 ))
//               )}
//             </div>
//           </section>

//           {/* RIGHT MAIN CHAT */}
//           <section className="panel chat-panel">
//             <div className="chat-window">
//               {messages.length === 0 && (
//                 <div className="chat-empty">
//                   <h1>What can I help you find?</h1>
//                   <p>Ask questions about your {dbDocs.length} uploaded documents.</p>
//                 </div>
//               )}

//               {messages.map((m, idx) => (
//                 <div key={idx} className={`message-row role-${m.role}`}>
//                   <div className="message-avatar">
//                     {m.role === "user" ? "👤" : "✨"}
//                   </div>
//                   <div className="message-content">{m.text}</div>
//                 </div>
//               ))}

//               {loading && (
//                 <div className="message-row role-assistant">
//                   <div className="message-avatar">✨</div>
//                   <div className="message-content">Thinking...</div>
//                 </div>
//               )}
//               <div ref={chatEndRef} />
//             </div>

//             <div className="chat-input-container">
//               <div className="chat-input-wrapper">
//                 <textarea
//                   value={question}
//                   onChange={(e) => setQuestion(e.target.value)}
//                   onKeyDown={handleKeyDown}
//                   placeholder="Ask a question..."
//                   rows={1}
//                 />
//                 <button className="send-btn" onClick={handleAsk} disabled={loading || !question.trim()}>
//                   ➜
//                 </button>
//               </div>
//             </div>
//           </section>

//         </main>
//       </div>
//     </div>
//   );
// }

// export default App;

import { useEffect, useRef, useState } from "react";
import axios from "axios";
import "./App.css";

const API_BASE = "https://multi-pdf-rag.onrender.com";

function App() {
  const [files, setFiles] = useState([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [question, setQuestion] = useState("");
  
  // 1. Chat Persistence: Load from Local Storage on boot
  const [messages, setMessages] = useState(() => {
    const saved = localStorage.getItem("chat_history");
    return saved ? JSON.parse(saved) : [];
  });
  
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

  // --- NEW: Handle Summarize ---
  const handleSummarize = async (docId) => {
    setLoading(true);
    // Add a temp message
    setMessages(prev => [...prev, { role: "assistant", text: "Generating summary... ⏳" }]);
    
    try {
      const res = await axios.post(`${API_BASE}/summarize_document/${docId}`);
      
      // Update the last message with the real summary
      setMessages(prev => {
        const newMsgs = [...prev];
        newMsgs[newMsgs.length - 1] = { 
          role: "assistant", 
          text: `📝 **Summary:**\n\n${res.data.summary}` 
        };
        return newMsgs;
      });
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { role: "assistant", text: "Failed to generate summary." }]);
    } finally {
      setLoading(false);
    }
  };

  // --- NEW: Clear Chat ---
  const clearChat = () => {
    if (window.confirm("Start a new chat? This will clear current history.")) {
      setMessages([]);
      localStorage.removeItem("chat_history");
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  useEffect(() => {
    fetchDocuments();
  }, []);

  // 2. Chat Persistence: Save to Local Storage on change
  useEffect(() => {
    localStorage.setItem("chat_history", JSON.stringify(messages));
  }, [messages]);

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

      const timeTaken = res.data.time_taken ? ` (${res.data.time_taken}s)` : "";
      setUploadStatus(`Done!${timeTaken}`);
      
      setFiles([]); 
      fetchDocuments();
      setTimeout(() => setUploadStatus(""), 5000); 

    } catch (err) {
      console.error("Upload error:", err.response?.data || err.message);
      setUploadStatus("Failed to upload.");
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);

    const newMessages = [...messages, { role: "user", text: question }];
    setMessages(newMessages);
    setQuestion("");

    try {
      const res = await axios.post(`${API_BASE}/ask`, { question });
      const answer = res.data.answer || "No answer returned.";
      const sources = res.data.sources || [];

      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: answer, sources: sources },
      ]);
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
        
        <header className="app-header">
          <div className="brand">
            <span className="logo-icon">⚡</span>
            <h1>RAG Chatbot</h1>
          </div>
          <div style={{display: "flex", gap: "10px", alignItems: "center"}}>
            <span className="model-badge">Gemini 1.5 Flash</span>
            {/* --- NEW CHAT BUTTON --- */}
            <button onClick={clearChat} className="new-chat-btn">
              + New Chat
            </button>
          </div>
        </header>

        <main className="app-main">
          
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
                <button 
                  className="primary-btn" 
                  onClick={handleUpload} 
                  disabled={uploading || !files.length} 
                  style={{width: "auto"}}
                >
                  {uploading ? "..." : "↑"}
                </button>
              </div>
              
              {uploadStatus && <div style={{fontSize: "0.8rem", color: "#6366f1", marginBottom: "10px"}}>{uploadStatus}</div>}
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
                    {/* --- UPDATED ACTIONS: Summarize + Delete --- */}
                    <div style={{display: "flex", gap: "5px"}}>
                      <button 
                        onClick={() => handleSummarize(doc.id)} 
                        className="action-btn summarize-btn"
                        title="Summarize Document"
                      >
                        📑
                      </button>
                      <button 
                        onClick={() => handleDelete(doc.id, doc.filename)} 
                        className="action-btn delete-btn"
                        title="Delete document"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

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
                  <div className="message-content">
                    <div className="message-text" style={{whiteSpace: "pre-wrap"}}>{m.text}</div>
                    
                    {m.sources && m.sources.length > 0 && (
                      <div className="message-sources">
                        <p className="sources-label">📚 Sources used:</p>
                        <div className="sources-list">
                          {m.sources.map((src, i) => (
                            <span key={i} className="source-pill">
                              {src.doc} (Pg. {src.page})
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
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