# main.py
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from dotenv import load_dotenv
import google.generativeai as genai
import pdfplumber
import os
import time

# --- Smart Splitting Library ---
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Import the updated Chunk model (Make sure you updated database.py!)
from database import SessionLocal, Document, Chunk, init_db

# ---------- init ----------
load_dotenv()
init_db()

# ---------- Gemini setup ----------
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# Using 1.5 Flash for stability and high rate limits
llm = genai.GenerativeModel("gemini-2.5-flash")

# ---------- FastAPI app ----------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- SMART CHUNKING ----------
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
    length_function=len,
    separators=["\n\n", "\n", ". ", " ", ""]
)

# ---------- BATCH EMBEDDING (Safe & Fast) ----------
def get_batch_embeddings(texts: list[str]) -> list[list[float]]:
    """Generates embeddings with Rate Limit handling."""
    embeddings = []
    batch_size = 10  # Reduced to 10 to be safer
    
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
                time.sleep(5) # Wait before retry
                if attempt == 2: # If fail 3 times, fill zeros
                    embeddings.extend([[0.0]*768] * len(batch))
        
        time.sleep(1) # Polite pause
            
    return embeddings

def clean_text(text: str) -> str:
    if not text: return ""
    return text.replace("\x00", " ").strip()

@app.get("/")
def home():
    return {"message": "Backend running with Citations!"}

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

# ---------- UPDATED: Upload with Page Numbers ----------
@app.post("/upload_pdfs")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    db = SessionLocal()
    total_chunks = 0
    total_docs = 0

    for file in files:
        doc = Document(filename=file.filename)
        db.add(doc)
        db.commit()
        db.refresh(doc)

        all_chunks_text = []
        all_chunks_metadata = [] # To store page numbers

        # 1. Process Page by Page
        with pdfplumber.open(file.file) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = clean_text(page.extract_text() or "")
                if not page_text: continue
                
                # Split this page's text
                chunks = text_splitter.split_text(page_text)
                
                for chunk in chunks:
                    all_chunks_text.append(chunk)
                    all_chunks_metadata.append(i + 1) # Store Page Number (Index+1)

        if not all_chunks_text:
            continue

        # 2. Embed All Chunks
        embeddings = get_batch_embeddings(all_chunks_text)

        # 3. Save to DB with Page Numbers
        chunk_objects = []
        for i, text_chunk in enumerate(all_chunks_text):
            if i < len(embeddings):
                chunk_objects.append(
                    Chunk(
                        document_id=doc.id,
                        text=text_chunk,
                        embedding=embeddings[i],
                        fts=text_chunk,
                        page_number=all_chunks_metadata[i] # <--- SAVING PAGE NUM
                    )
                )
        
        db.add_all(chunk_objects)
        db.commit()
        
        total_chunks += len(all_chunks_text)
        total_docs += 1

    return {"message": f"Processed {total_docs} PDFs into {total_chunks} chunks with citations."}


# ---------- UPDATED: Q&A with Citations ----------
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

    # Fetch Top 15 (Semantic)
    sem_sql = text("""
        SELECT id, text, page_number,
               1 - (embedding <=> CAST(:qvec AS vector)) AS score
        FROM chunks
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 15;
    """)
    sem_results = db.execute(sem_sql, {"qvec": vec_str}).fetchall()

    # Fetch Top 15 (Keyword)
    bm_sql = text("""
        SELECT id, text, page_number,
               ts_rank_cd(to_tsvector('english', text), plainto_tsquery(:qtext)) AS score
        FROM chunks
        WHERE to_tsvector('english', text) @@ plainto_tsquery(:qtext)
        ORDER BY score DESC
        LIMIT 15;
    """)
    bm_results = db.execute(bm_sql, {"qtext": q.question}).fetchall()

    # Hybrid Fusion
    combined = {}
    # Store page numbers in a separate dict for quick lookup
    chunk_pages = {} 

    for r in sem_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score) * 0.7
        chunk_pages[r.id] = r.page_number
        
    for r in bm_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score) * 0.3
        chunk_pages[r.id] = r.page_number

    if not combined:
        return {"answer": "I couldn't find any relevant information in the uploaded PDFs."}

    # Top 15 Chunks
    top_ids = sorted(combined.keys(), key=lambda cid: combined[cid], reverse=True)[:15]
    top_chunks = db.query(Chunk).filter(Chunk.id.in_(top_ids)).all()

    # Construct Context with Page Numbers
    # Format: "Text... [Page 5]"
    context_parts = []
    for ch in top_chunks:
        context_parts.append(f"{ch.text}\n[Source: Page {ch.page_number}]")
    
    context = "\n\n---\n\n".join(context_parts)

    # Citation Prompt
    prompt = f"""
You are an expert research assistant. Answer the question based ONLY on the provided context.

IMPORTANT CITATION RULES:
1. Every time you state a fact, you MUST include the [Source: Page X] tag at the end of the sentence.
2. If the context has multiple pages, mention all relevant pages.
3. If the answer is not in the context, say "I don't have enough information."

Context:
{context}

Question:
{q.question}

Answer with citations:
"""
    response = llm.generate_content(prompt)
    answer_text = getattr(response, "text", None) or "LLM did not return text."

    return {"answer": answer_text}