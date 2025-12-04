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

# GEMINI setup
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
llm = genai.GenerativeModel("gemini-2.0-flash")   # 🔥 lightweight, cheaper memory

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # allow all origins for front-end deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 Lazy Model Loading (prevents Render 512MB OOM)
model = None

def get_model():
    global model
    if model is None:
        model = SentenceTransformer("all-MiniLM-L6-v2")   # loads only when needed
    return model


def embed(text: str):
    return get_model().encode(text).tolist()


def split_text(text, chunk_size=800):
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def clean_text(text: str) -> str:
    return text.replace("\x00", " ").strip()


@app.get("/")
def home():
    return {"message": "Backend is running!"}


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
            chunk = clean_text(chunk)
            if not chunk:
                continue
            emb = embed(chunk)
            db.add(Chunk(
                document_id=doc.id,
                text=chunk,
                embedding=emb,
                fts=chunk
            ))

        db.commit()
    return {"message": "PDFs stored in DB"}


class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask(q: Question):
    db = SessionLocal()
    q_emb = embed(q.question)
    vec_str = "[" + ",".join(str(x) for x in q_emb) + "]"

    sem_sql = text("""
        SELECT id, text,
               1 - (embedding <=> CAST(:qvec AS vector)) AS score
        FROM chunks
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 5;
    """)
    sem_results = db.execute(sem_sql, {"qvec": vec_str}).fetchall()

    bm_sql = text("""
        SELECT id, text,
               ts_rank_cd(to_tsvector('english', text), plainto_tsquery(:qtext)) AS score
        FROM chunks
        WHERE to_tsvector('english', text) @@ plainto_tsquery(:qtext)
        ORDER BY score DESC
        LIMIT 5;
    """)
    bm_results = db.execute(bm_sql, {"qtext": q.question}).fetchall()

    combined = {}
    for r in sem_results:
        combined[r.id] = combined.get(r.id, 0) + float(r.score)
    for r in bm_results:
        combined[r.id] = combined.get(r.id, 0) + float(r.score)

    if not combined:
        return {"answer": "I couldn't find relevant information from PDFs."}

    top_ids = sorted(combined.keys(), key=lambda cid: combined[cid], reverse=True)[:5]
    top_chunks = db.query(Chunk).filter(Chunk.id.in_(top_ids)).all()
    context = "\n\n---\n\n".join(ch.text for ch in top_chunks)

    prompt = f"""
Answer ONLY based on the context below.
If answer is not present, say:
"I don't have enough information from the documents."

Context:
{context}

Question:
{q.question}
"""

    response = llm.generate_content(prompt)
    answer_text = response.text if hasattr(response, "text") else "No answer returned."

    return {"answer": answer_text}
