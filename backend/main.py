# main.py
from fastapi import FastAPI, UploadFile, File, Depends
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import google.generativeai as genai
import pdfplumber
import os
import time

# --- Re-ranking Library ---
from flashrank import Ranker, RerankRequest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from database import SessionLocal, Document, Chunk, init_db

# ---------- init ----------
load_dotenv()
init_db()

# ---------- Re-ranker Setup ----------
ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

# ---------- Gemini setup ----------
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("❌ ERROR: No API Key found in environment variables!")
else:
    print(f"✅ Loaded API Key starting with: {api_key[:10]}...")
# Using 1.5 Flash for stability
llm = genai.GenerativeModel("gemini-3-flash")

# ---------- FastAPI app ----------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- DATABASE DEPENDENCY (THE FIX) ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() # <--- This guarantees the connection closes!

# ---------- SMART CHUNKING ----------
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
    length_function=len,
    separators=["\n\n", "\n", ". ", " ", ""]
)

# ---------- BATCH EMBEDDING ----------
def get_batch_embeddings(texts: list[str]) -> list[list[float]]:
    embeddings = []
    batch_size = 10 
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(3):
            try:
                result = genai.embed_content(
                    model="models/text-embedding-004",
                    content=batch,
                    task_type="retrieval_document"
                )
                embeddings.extend(result['embedding'])
                break
            except Exception as e:
                print(f"⚠️ Error/Rate Limit: {e}. Retrying...")
                time.sleep(5)
                if attempt == 2: 
                    embeddings.extend([[0.0]*768] * len(batch))
        time.sleep(1) 
    return embeddings

def clean_text(text: str) -> str:
    if not text: return ""
    return text.replace("\x00", " ").strip()

@app.get("/")
def home():
    return {"message": "Backend running (Database Fix Applied)!"}

@app.get("/list_documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).all()
    return {
        "count": len(docs),
        "documents": [{"id": d.id, "filename": d.filename} for d in docs]
    }

@app.post("/summarize_document/{doc_id}")
async def summarize_document(doc_id: int, db: Session = Depends(get_db)):
    chunks = db.query(Chunk).filter(Chunk.document_id == doc_id).order_by(Chunk.page_number).all()
    if not chunks:
        return {"summary": "No content found to summarize."}

    pages = {}
    for chunk in chunks:
        if chunk.page_number not in pages:
            pages[chunk.page_number] = []
        pages[chunk.page_number].append(chunk.text)
    
    sorted_pages = sorted(pages.keys())
    
    batch_size = 5
    mini_summaries = []
    
    for i in range(0, len(sorted_pages), batch_size):
        batch_page_nums = sorted_pages[i : i + batch_size]
        batch_text = ""
        for p in batch_page_nums:
            batch_text += f"\n--- Page {p} ---\n" + " ".join(pages[p])
        
        prompt = f"""
        Summarize the following {len(batch_page_nums)} pages of a document.
        Focus on key facts, dates, and definitions.
        Text: {batch_text[:30000]}
        Summary:
        """
        response = llm.generate_content(prompt)
        mini_summaries.append(response.text)
        time.sleep(1) 

    combined_summaries = "\n\n".join(mini_summaries)
    final_prompt = f"""
    Combine these section summaries into one Master Summary.
    Sections: {combined_summaries}
    Master Summary:
    """
    final_response = llm.generate_content(final_prompt)
    final_summary = final_response.text

    doc = db.query(Document).filter(Document.id == doc_id).first()
    doc.summary = final_summary
    db.commit()

    return {"summary": final_summary}

@app.delete("/delete_document/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"message": "Document not found"}
    
    db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
    db.delete(doc)
    db.commit()
    return {"message": f"Deleted {doc.filename}"}

@app.post("/upload_pdfs")
async def upload_pdfs(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    total_chunks = 0
    total_docs = 0

    for file in files:
        doc = Document(filename=file.filename)
        db.add(doc)
        db.commit()
        db.refresh(doc)

        all_chunks_text = []
        all_chunks_metadata = [] 

        with pdfplumber.open(file.file) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = clean_text(page.extract_text() or "")
                if not page_text: continue
                
                chunks = text_splitter.split_text(page_text)
                for chunk in chunks:
                    all_chunks_text.append(chunk)
                    all_chunks_metadata.append(i + 1)

        if not all_chunks_text:
            continue

        embeddings = get_batch_embeddings(all_chunks_text)

        chunk_objects = []
        for i, text_chunk in enumerate(all_chunks_text):
            if i < len(embeddings):
                chunk_objects.append(
                    Chunk(
                        document_id=doc.id,
                        text=text_chunk,
                        embedding=embeddings[i],
                        fts=text_chunk,
                        page_number=all_chunks_metadata[i]
                    )
                )
        
        db.add_all(chunk_objects)
        db.commit()
        
        total_chunks += len(all_chunks_text)
        total_docs += 1

    return {"message": f"Processed {total_docs} PDFs into {total_chunks} chunks."}

# ---------- Q&A ----------
class Question(BaseModel):
    question: str
    history: list[dict] = []

@app.post("/ask")
async def ask(q: Question, db: Session = Depends(get_db)):
    
    # 1. Embed Question
    q_result = genai.embed_content(
        model="models/text-embedding-004",
        content=q.question,
        task_type="retrieval_query"
    )
    vec_str = "[" + ",".join(str(x) for x in q_result['embedding']) + "]"

    # 2. Broad Retrieval
    sem_sql = text("""
        SELECT id, text, page_number, document_id,
               1 - (embedding <=> CAST(:qvec AS vector)) AS score
        FROM chunks
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 20;
    """)
    sem_results = db.execute(sem_sql, {"qvec": vec_str}).fetchall()

    bm_sql = text("""
        SELECT id, text, page_number, document_id,
               ts_rank_cd(to_tsvector('english', text), plainto_tsquery(:qtext)) AS score
        FROM chunks
        WHERE to_tsvector('english', text) @@ plainto_tsquery(:qtext)
        ORDER BY score DESC
        LIMIT 20;
    """)
    bm_results = db.execute(bm_sql, {"qtext": q.question}).fetchall()

    # 3. Deduplicate
    candidates = {}
    for r in sem_results:
        candidates[r.id] = {"id": r.id, "text": r.text, "meta": {"page": r.page_number, "doc_id": r.document_id}}
        
    for r in bm_results:
        if r.id not in candidates:
            candidates[r.id] = {"id": r.id, "text": r.text, "meta": {"page": r.page_number, "doc_id": r.document_id}}

    if not candidates:
        return {"answer": "I couldn't find any relevant information."}

    # 4. Re-rank
    passages = list(candidates.values()) 
    rerank_request = RerankRequest(query=q.question, passages=passages)
    ranked_results = ranker.rerank(rerank_request)

    # 5. Filter (Confidence Threshold)
    good_results = [r for r in ranked_results if r['score'] > 0.75]
    
    if not good_results:
        top_results = [] 
    else:
        top_results = good_results[:7]

    context_parts = []
    sources = []
    seen_pages = set()

    for r in top_results:
        context_parts.append(f"{r['text']} (Page {r['meta']['page']})")
        doc_id = r['meta']['doc_id']
        page_num = r['meta']['page']
        doc = db.query(Document).filter(Document.id == doc_id).first()
        doc_name = doc.filename if doc else "Unknown PDF"
        
        identifier = (doc_name, page_num)
        if identifier not in seen_pages:
            sources.append({"doc": doc_name, "page": page_num})
            seen_pages.add(identifier)

    context = "\n\n".join(context_parts)
    sources.sort(key=lambda x: (x['doc'], x['page']))

    # 6. Format History
    history_text = ""
    if q.history:
        history_text = "Chat History:\n"
        for msg in q.history[-6:]:
            role = "User" if msg['role'] == "user" else "Assistant"
            clean_msg = msg['text'].replace("\n", " ")
            history_text += f"{role}: {clean_msg}\n"

    # 7. Generate Answer
    prompt = f"""
    You are a helpful AI assistant.
    
    If the provided Context below is relevant, answer the user's question based strictly on it.
    If the Context is empty or irrelevant (like for "ok", "hello", "thanks"), just answer politely based on the chat history or general knowledge.
    {history_text}
    DOCUMENT CONTEXT:
    {context}
    USER QUESTION: {q.question}
    ANSWER:
    """
    
    response = llm.generate_content(prompt)
    answer_text = getattr(response, "text", None) or "LLM did not return text."

    return {
        "answer": answer_text,
        "sources": sources
    }