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

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # you will later add your deployed frontend URL here
    ],
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
    return model.encode(text).tolist()


def split_text(text, chunk_size=800):
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def clean_text(text: str) -> str:
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
            chunk = clean_text(chunk)
            if not chunk:
                continue
            emb = embed(chunk)
            c = Chunk(
                document_id=doc.id,
                text=chunk,
                embedding=emb,
                fts=chunk,
            )
            db.add(c)

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

    combined: dict[int, float] = {}
    for r in sem_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score)
    for r in bm_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score)

    if not combined:
        return {"answer": "I couldn't find any relevant information in the uploaded PDFs."}

    top_k = 5
    top_ids = sorted(combined.keys(), key=lambda cid: combined[cid], reverse=True)[:top_k]
    top_chunks = db.query(Chunk).filter(Chunk.id.in_(top_ids)).all()

    context = "\n\n---\n\n".join(ch.text for ch in top_chunks)

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


# 👇 Add this block at the VERY BOTTOM of the file
if __name__ == "__main__":
    # This is only used when you run: python main.py
    # Render uses `uvicorn main:app`, where __name__ != "__main__",
    # so this block won't interfere with Render.
    port = int(os.environ.get("PORT", 8000))
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=port)
