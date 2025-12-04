from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
import pdfplumber
from sentence_transformers import SentenceTransformer
import numpy as np
from database import SessionLocal, Document, Chunk, init_db
from sqlalchemy import text
import google.generativeai as genai
from dotenv import load_dotenv
import os
from fastapi.middleware.cors import CORSMiddleware



init_db()


load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
llm = genai.GenerativeModel("gemini-2.5-flash")

# print("Available models for this key:")
# for m in genai.list_models():
#     print(m.name)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# load model once
model = SentenceTransformer("all-MiniLM-L6-v2")

# in-memory store (Stage-1)
documents = []
embeddings = []

def embed(text: str):
    # return list, not numpy array
    return model.encode(text).tolist()


def split_text(text, chunk_size=800):
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

def clean_text(text: str) -> str:
    # remove NUL characters and strip extra whitespace
    return text.replace("\x00", " ").strip()


@app.get("/")
def home():
    return {"message": "Multi-PDF RAG Backend is running!"}


@app.post("/upload_pdfs")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    db = SessionLocal()
    for file in files:
        with pdfplumber.open(file.file) as pdf:
            pages_text = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                t = clean_text(t)
                pages_text.append(t)
            full_text = "\n".join(pages_text)

        doc = Document(filename=file.filename)
        db.add(doc)
        db.commit()
        db.refresh(doc)

        chunks = split_text(full_text)
        for chunk in chunks:
            chunk = clean_text(chunk)          # extra safety
            if not chunk:                      # skip empty chunks
                continue
            emb = embed(chunk)                 # list, not ndarray
            c = Chunk(
                document_id=doc.id,
                text=chunk,
                embedding=emb,
                fts=chunk
            )
            db.add(c)

        db.commit()
    return {"message": "PDFs stored in DB"}




class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask(q: Question):
    db = SessionLocal()
    q_emb = embed(q.question)  # list[float]

    # Convert to pgvector literal string: "[0.1,0.2,0.3,...]"
    vec_str = "[" + ",".join(str(x) for x in q_emb) + "]"

    # 1) Semantic search (vector similarity)
    sem_sql = text("""
        SELECT id, text,
               1 - (embedding <=> CAST(:qvec AS vector)) AS score
        FROM chunks
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 5;
    """)
    sem_results = db.execute(sem_sql, {"qvec": vec_str}).fetchall()

    # 2) Full-text search (BM25-style)
    bm_sql = text("""
        SELECT id, text,
               ts_rank_cd(to_tsvector('english', text), plainto_tsquery(:qtext)) AS score
        FROM chunks
        WHERE to_tsvector('english', text) @@ plainto_tsquery(:qtext)
        ORDER BY score DESC
        LIMIT 5;
    """)
    bm_results = db.execute(bm_sql, {"qtext": q.question}).fetchall()

    # 3) Combine semantic + keyword scores
    combined: dict[int, float] = {}

    for r in sem_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score)

    for r in bm_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score)

    if not combined:
        return {"answer": "I couldn't find any relevant information in the uploaded PDFs."}

    # Take top-k chunks as context for the LLM
    top_k = 5
    top_ids = sorted(combined.keys(), key=lambda cid: combined[cid], reverse=True)[:top_k]
    top_chunks = db.query(Chunk).filter(Chunk.id.in_(top_ids)).all()

    # Build context string
    context = "\n\n---\n\n".join(ch.text for ch in top_chunks)

    # 4) Ask Gemini to generate a final answer
    prompt = f"""
You are a helpful assistant answering questions based ONLY on the provided context.
If the answer is not clearly contained in the context, say "I don't have enough information from the documents."

Context:
{context}

Question:
{q.question}

Answer in a clear and concise paragraph:
"""

    response = llm.generate_content(prompt)
    answer_text = response.text if hasattr(response, "text") else "LLM did not return text."

    return {"answer": answer_text}




