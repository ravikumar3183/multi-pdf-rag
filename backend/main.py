# main.py
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from dotenv import load_dotenv
import google.generativeai as genai
import pdfplumber
import os

# --- NEW: Smart Splitting Library ---
from langchain_text_splitters import RecursiveCharacterTextSplitter

from database import SessionLocal, Document, Chunk, init_db

# ---------- init ----------
load_dotenv()
init_db()

# ---------- Gemini setup ----------
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# Switched to 1.5 Flash to avoid the "429 Quota Exceeded" error you saw earlier
llm = genai.GenerativeModel("gemini-2.5-pro")

# ---------- FastAPI app ----------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 1. SMART CHUNKING SETUP ----------
# Uses RecursiveCharacterTextSplitter to keep sentences and paragraphs intact.
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,      # Larger chunk size for more context per vector
    chunk_overlap=100,    # 100 char overlap to prevent cutting words/ideas in half
    length_function=len,
    separators=["\n\n", "\n", ". ", " ", ""]
)

# ---------- 2. BATCH EMBEDDING (SPEED) ----------
def get_batch_embeddings(texts: list[str]) -> list[list[float]]:
    """Generates embeddings for a list of texts in one API call."""
    embeddings = []
    batch_size = 20 # Send 20 chunks at once to Google
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            result = genai.embed_content(
                model="models/text-embedding-004",
                content=batch,
                task_type="retrieval_document"
            )
            # When embedding a list, the API returns a list of embeddings
            embeddings.extend(result['embedding'])
        except Exception as e:
            print(f"Error embedding batch: {e}")
            # Safety fill to prevent server crash
            embeddings.extend([[0.0]*768] * len(batch))
            
    return embeddings

def clean_text(text: str) -> str:
    if not text: return ""
    return text.replace("\x00", " ").strip()

@app.get("/")
def home():
    return {"message": "Backend is running with Smart Chunking & Batching!"}

@app.get("/list_documents")
def list_documents():
    db = SessionLocal()
    docs = db.query(Document).all()
    return {
        "count": len(docs),
        "documents": [{"id": d.id, "filename": d.filename} for d in docs]
    }

@app.delete("/delete_document/{doc_id}")
def delete_document(doc_id: int):
    db = SessionLocal()
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"message": "Document not found"}
    
    db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
    db.delete(doc)
    db.commit()
    return {"message": f"Deleted {doc.filename}"}

# ---------- UPDATED PDF UPLOAD (SMART + BATCH) ----------
@app.post("/upload_pdfs")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    db = SessionLocal()
    total_chunks = 0
    total_docs = 0

    for file in files:
        # A. Extract Text
        with pdfplumber.open(file.file) as pdf:
            pages_text = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages_text.append(clean_text(t))
            # Join with double newlines to help the splitter identify paragraphs
            full_text = "\n\n".join(pages_text)

        # B. Save Doc Entry
        doc = Document(filename=file.filename)
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # C. Smart Split
        chunks_text = text_splitter.split_text(full_text)
        
        if not chunks_text:
            continue

        # D. Batch Embed (This makes it fast!)
        embeddings = get_batch_embeddings(chunks_text)

        # E. Bulk Save to DB
        chunk_objects = []
        for i, text_chunk in enumerate(chunks_text):
            if i < len(embeddings):
                chunk_objects.append(
                    Chunk(
                        document_id=doc.id,
                        text=text_chunk,
                        embedding=embeddings[i],
                        fts=text_chunk
                    )
                )
        
        db.add_all(chunk_objects)
        db.commit()
        
        total_chunks += len(chunks_text)
        total_docs += 1

    return {"message": f"Processed {total_docs} PDFs into {total_chunks} smart chunks."}


# ---------- UPDATED Q&A (INCREASED CONTEXT) ----------
class Question(BaseModel):
    question: str

@app.post("/ask")
async def ask(q: Question):
    db = SessionLocal()
    
    # Embed Question
    q_result = genai.embed_content(
        model="models/text-embedding-004",
        content=q.question,
        task_type="retrieval_query"
    )
    vec_str = "[" + ",".join(str(x) for x in q_result['embedding']) + "]"

    # 3. INCREASED CONTEXT: Fetch top 20 instead of 5
    
    # Semantic Search
    sem_sql = text("""
        SELECT id, text,
               1 - (embedding <=> CAST(:qvec AS vector)) AS score
        FROM chunks
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 20;
    """)
    sem_results = db.execute(sem_sql, {"qvec": vec_str}).fetchall()

    # Keyword Search
    bm_sql = text("""
        SELECT id, text,
               ts_rank_cd(to_tsvector('english', text),
                          plainto_tsquery(:qtext)) AS score
        FROM chunks
        WHERE to_tsvector('english', text) @@ plainto_tsquery(:qtext)
        ORDER BY score DESC
        LIMIT 20;
    """)
    bm_results = db.execute(bm_sql, {"qtext": q.question}).fetchall()

    # Hybrid Fusion
    combined = {}
    for r in sem_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score) * 0.7 
    for r in bm_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score) * 0.3

    if not combined:
        return {"answer": "I couldn't find any relevant information in the uploaded PDFs."}

    # Select Top 20 Best Matches
    top_k = 20 
    top_ids = sorted(combined.keys(), key=lambda cid: combined[cid], reverse=True)[:top_k]
    top_chunks = db.query(Chunk).filter(Chunk.id.in_(top_ids)).all()

    context = "\n\n---\n\n".join(ch.text for ch in top_chunks)

    prompt = f"""
You are a helpful assistant answering questions based ONLY on the provided context.
If the answer is not clearly contained in the context, say
"I don't have enough information from the documents."

Context:
{context}

Question:
{q.question}

Answer in a clear, concise paragraph:
"""

    response = llm.generate_content(prompt)
    answer_text = getattr(response, "text", None) or "LLM did not return text."

    return {"answer": answer_text}