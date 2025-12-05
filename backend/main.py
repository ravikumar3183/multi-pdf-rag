from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from dotenv import load_dotenv
import google.generativeai as genai
from sentence_transformers import SentenceTransformer
import pdfplumber
import os

from database import SessionLocal, Document, Chunk, init_db

# ---------- init ----------
load_dotenv()
init_db()

# ---------- Gemini setup ----------
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
llm = genai.GenerativeModel("gemini-2.0-flash")

# ---------- FastAPI app ----------
app = FastAPI()

# CORS: allow any origin (safe enough for this demo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # or list specific origins if you prefer
    allow_credentials=False,  # must be False when using "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Embedding model (lighter) ----------
# L3-v2 is smaller than all-MiniLM-L6-v2 and better for Render free tier
MODEL_NAME = "sentence-transformers/paraphrase-MiniLM-L3-v2"
model = SentenceTransformer(MODEL_NAME)


def embed(text: str) -> list[float]:
    """Return embedding as Python list[float] for pgvector."""
    return model.encode(text).tolist()


def split_text(text: str, chunk_size: int = 800) -> list[str]:
    """Simple fixed-size chunking."""
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def clean_text(text: str) -> str:
    """Remove NULs etc. to avoid DB errors."""
    return text.replace("\x00", " ").strip()


@app.get("/")
def home():
    return {"message": "Backend is running!"}


# ---------- PDF upload & indexing ----------
@app.post("/upload_pdfs")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    db = SessionLocal()
    total_chunks = 0

    for file in files:
        # 1) read PDF text
        with pdfplumber.open(file.file) as pdf:
            pages_text = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages_text.append(clean_text(t))
            full_text = "\n".join(pages_text)

        # 2) create Document row
        doc = Document(filename=file.filename)
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # 3) chunk + embed
        for chunk in split_text(full_text):
            chunk = clean_text(chunk)
            if not chunk:
                continue

            emb = embed(chunk)

            db.add(
                Chunk(
                    document_id=doc.id,
                    text=chunk,
                    embedding=emb,
                    fts=chunk,
                )
            )
            total_chunks += 1

        db.commit()

    return {"message": "PDFs processed", "chunks": total_chunks}


# ---------- Q&A ----------
class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask(q: Question):
    db = SessionLocal()
    q_emb = embed(q.question)
    vec_str = "[" + ",".join(str(x) for x in q_emb) + "]"

    # 1) semantic search (pgvector)
    sem_sql = text("""
        SELECT id, text,
               1 - (embedding <=> CAST(:qvec AS vector)) AS score
        FROM chunks
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 5;
    """)
    sem_results = db.execute(sem_sql, {"qvec": vec_str}).fetchall()

    # 2) keyword / BM25-style search
    bm_sql = text("""
        SELECT id, text,
               ts_rank_cd(to_tsvector('english', text),
                          plainto_tsquery(:qtext)) AS score
        FROM chunks
        WHERE to_tsvector('english', text) @@ plainto_tsquery(:qtext)
        ORDER BY score DESC
        LIMIT 5;
    """)
    bm_results = db.execute(bm_sql, {"qtext": q.question}).fetchall()

    # 3) Combine scores
    combined: dict[int, float] = {}

    for r in sem_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score)

    for r in bm_results:
        combined[r.id] = combined.get(r.id, 0.0) + float(r.score)

    if not combined:
        return {"answer": "I couldn't find any relevant information in the uploaded PDFs."}

    # 4) Take top-k chunks as context
    top_k = 5
    top_ids = sorted(combined.keys(), key=lambda cid: combined[cid], reverse=True)[:top_k]
    top_chunks = db.query(Chunk).filter(Chunk.id.in_(top_ids)).all()

    context = "\n\n---\n\n".join(ch.text for ch in top_chunks)

    # 5) Ask Gemini
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
