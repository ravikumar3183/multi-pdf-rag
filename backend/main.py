from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import pdfplumber
import logging
import os
import time

from flashrank import Ranker, RerankRequest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from database import SessionLocal, Document, Chunk, init_db


# ============================================================
# INITIALIZATION
# ============================================================

load_dotenv()

init_db()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY is not configured.")

client = genai.Client(api_key=api_key)
logger = logging.getLogger(__name__)

GENERATION_MODEL = "gemini-3.8-flash"
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSIONS = 768


# ============================================================
# RE-RANKER
# ============================================================

ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# ============================================================
# CHUNKING
# ============================================================

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
    length_function=len,
    separators=["\n\n", "\n", ". ", " ", ""]
)


# ============================================================
# EMBEDDINGS
# ============================================================

def prepare_document_for_embedding(text_content: str, title: str | None = None):
    if not title:
        title = "none"

    return f"title: {title} | text: {text_content}"


def prepare_query_for_embedding(query: str):
    return f"task: question answering | query: {query}"


def get_batch_embeddings(
    texts: list[str],
    titles: list[str] | None = None
) -> list[list[float]]:

    if not texts:
        return []

    if titles is None:
        titles = ["none"] * len(texts)

    if len(texts) != len(titles):
        raise ValueError("texts and titles must have the same length.")

    embeddings = []

    batch_size = 10

    for i in range(0, len(texts), batch_size):

        batch_texts = texts[i:i + batch_size]
        batch_titles = titles[i:i + batch_size]

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=prepare_document_for_embedding(
                            text_content,
                            title
                        )
                    )
                ],
            )
            for text_content, title in zip(batch_texts, batch_titles)
        ]

        for attempt in range(3):

            try:

                response = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=contents,
                    config=types.EmbedContentConfig(
                        output_dimensionality=EMBEDDING_DIMENSIONS
                    ),
                )

                batch_embeddings = [
                    embedding.values
                    for embedding in response.embeddings
                ]

                if len(batch_embeddings) != len(batch_texts):
                    raise RuntimeError(
                        "Embedding API returned an unexpected number of embeddings."
                    )

                for embedding in batch_embeddings:

                    if len(embedding) != EMBEDDING_DIMENSIONS:
                        raise RuntimeError(
                            f"Expected {EMBEDDING_DIMENSIONS}-dimensional "
                            f"embedding, got {len(embedding)}."
                        )

                embeddings.extend(batch_embeddings)

                break

            except Exception as e:

                print(
                    f"Embedding error (attempt {attempt + 1}/3): {e}"
                )

                if attempt == 2:
                    raise

                time.sleep(5)

        time.sleep(1)

    return embeddings


def get_query_embedding(query: str) -> list[float]:

    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=prepare_query_for_embedding(query),
        config=types.EmbedContentConfig(
            output_dimensionality=EMBEDDING_DIMENSIONS
        ),
    )

    if not response.embeddings:
        raise RuntimeError("No embedding returned for query.")

    embedding = response.embeddings[0].values

    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"Expected {EMBEDDING_DIMENSIONS}-dimensional embedding, "
            f"got {len(embedding)}."
        )

    return embedding


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text_content: str) -> str:

    if not text_content:
        return ""

    return text_content.replace("\x00", " ").strip()


# ============================================================
# LLM GENERATION
# ============================================================

def generate_answer(prompt: str) -> str:
    retryable_status_codes = {429, 500, 502, 503, 504}
    max_attempts = 2

    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=GENERATION_MODEL,
                contents=prompt,
            )
            break
        except genai_errors.APIError as error:
            if error.code not in retryable_status_codes:
                logger.error(
                    "Gemini %s request failed with HTTP %s.",
                    GENERATION_MODEL,
                    error.code,
                )
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Gemini {GENERATION_MODEL} request failed "
                        f"(HTTP {error.code}). Check the backend logs."
                    ),
                ) from error

            if attempt == max_attempts - 1:
                logger.error(
                    "Gemini %s remained unavailable after %s attempts "
                    "(HTTP %s).",
                    GENERATION_MODEL,
                    max_attempts,
                    error.code,
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"Gemini {GENERATION_MODEL} is temporarily busy. "
                        "Please try the summary again shortly."
                    ),
                ) from error

            delay = 2 ** attempt
            logger.warning(
                "Gemini %s returned HTTP %s; retrying in %s seconds "
                "(attempt %s/%s).",
                GENERATION_MODEL,
                error.code,
                delay,
                attempt + 1,
                max_attempts,
            )
            time.sleep(delay)

    answer = getattr(response, "text", None)

    if not answer:
        return "LLM did not return a response."

    return answer


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return {
        "message": "Multi-PDF RAG backend is running."
    }


# ============================================================
# LIST DOCUMENTS
# ============================================================

@app.get("/list_documents")
def list_documents(db: Session = Depends(get_db)):

    docs = db.query(Document).all()

    return {
        "count": len(docs),
        "documents": [
            {
                "id": d.id,
                "filename": d.filename
            }
            for d in docs
        ]
    }


# ============================================================
# SUMMARIZE DOCUMENT
# ============================================================

@app.post("/summarize_document/{doc_id}")
async def summarize_document(
    doc_id: int,
    db: Session = Depends(get_db)
):

    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc_id)
        .order_by(Chunk.page_number)
        .all()
    )

    if not chunks:
        return {
            "summary": "No content found to summarize."
        }

    pages = {}

    for chunk in chunks:

        if chunk.page_number not in pages:
            pages[chunk.page_number] = []

        pages[chunk.page_number].append(chunk.text)

    sorted_pages = sorted(pages.keys())

    batch_size = 5
    mini_summaries = []

    for i in range(0, len(sorted_pages), batch_size):

        batch_page_nums = sorted_pages[
            i:i + batch_size
        ]

        batch_text = ""

        for page_number in batch_page_nums:

            batch_text += (
                f"\n--- Page {page_number} ---\n"
                + " ".join(pages[page_number])
            )

        prompt = f"""
Summarize the following {len(batch_page_nums)} pages of a document.

Focus on:
- key facts
- important concepts
- dates
- definitions
- important conclusions

Do not invent information.

Text:
{batch_text[:30000]}

Summary:
"""

        summary = generate_answer(prompt)

        mini_summaries.append(summary)

        time.sleep(1)

    combined_summaries = "\n\n".join(mini_summaries)

    final_prompt = f"""
Combine the following section summaries into one clear master summary.

Preserve important facts and concepts.
Do not add information that is not present in the summaries.

Section summaries:

{combined_summaries}

Master Summary:
"""

    final_summary = generate_answer(final_prompt)

    doc = (
        db.query(Document)
        .filter(Document.id == doc_id)
        .first()
    )

    if doc:
        doc.summary = final_summary
        db.commit()

    return {
        "summary": final_summary
    }


# ============================================================
# DELETE DOCUMENT
# ============================================================

@app.delete("/delete_document/{doc_id}")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db)
):

    doc = (
        db.query(Document)
        .filter(Document.id == doc_id)
        .first()
    )

    if not doc:
        return {
            "message": "Document not found"
        }

    db.query(Chunk).filter(
        Chunk.document_id == doc_id
    ).delete()

    filename = doc.filename

    db.delete(doc)
    db.commit()

    return {
        "message": f"Deleted {filename}"
    }


# ============================================================
# UPLOAD PDFs
# ============================================================

@app.post("/upload_pdfs")
async def upload_pdfs(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db)
):

    total_chunks = 0
    total_docs = 0

    for file in files:

        doc = Document(
            filename=file.filename
        )

        db.add(doc)
        db.commit()
        db.refresh(doc)

        all_chunks_text = []
        all_chunks_metadata = []

        with pdfplumber.open(file.file) as pdf:

            for page_number, page in enumerate(pdf.pages, start=1):

                page_text = clean_text(
                    page.extract_text() or ""
                )

                if not page_text:
                    continue

                chunks = text_splitter.split_text(
                    page_text
                )

                for chunk in chunks:

                    all_chunks_text.append(chunk)
                    all_chunks_metadata.append(page_number)

        if not all_chunks_text:
            continue

        titles = [file.filename] * len(all_chunks_text)

        embeddings = get_batch_embeddings(
            all_chunks_text,
            titles
        )

        chunk_objects = []

        for i, text_chunk in enumerate(all_chunks_text):

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

    return {
        "message": (
            f"Processed {total_docs} PDFs "
            f"into {total_chunks} chunks."
        )
    }


# ============================================================
# QUESTION MODEL
# ============================================================

class Question(BaseModel):

    question: str

    history: list[dict] = Field(
        default_factory=list
    )


# ============================================================
# Q&A
# ============================================================

@app.post("/ask")
async def ask(
    q: Question,
    db: Session = Depends(get_db)
):

    # --------------------------------------------------------
    # 1. Embed Question
    # --------------------------------------------------------

    query_embedding = get_query_embedding(
        q.question
    )

    vec_str = (
        "["
        + ",".join(
            str(x)
            for x in query_embedding
        )
        + "]"
    )


    # --------------------------------------------------------
    # 2. Semantic Retrieval
    # --------------------------------------------------------

    sem_sql = text("""
        SELECT
            id,
            text,
            page_number,
            document_id,
            1 - (
                embedding <=> CAST(:qvec AS vector)
            ) AS score
        FROM chunks
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 20;
    """)

    sem_results = db.execute(
        sem_sql,
        {"qvec": vec_str}
    ).fetchall()


    # --------------------------------------------------------
    # 3. BM25 / Full Text Retrieval
    # --------------------------------------------------------

    bm_sql = text("""
        SELECT
            id,
            text,
            page_number,
            document_id,
            ts_rank_cd(
                to_tsvector('english', text),
                plainto_tsquery(:qtext)
            ) AS score
        FROM chunks
        WHERE to_tsvector('english', text)
              @@ plainto_tsquery(:qtext)
        ORDER BY score DESC
        LIMIT 20;
    """)

    bm_results = db.execute(
        bm_sql,
        {"qtext": q.question}
    ).fetchall()


    # --------------------------------------------------------
    # 4. Deduplicate
    # --------------------------------------------------------

    candidates = {}

    for r in sem_results:

        candidates[r.id] = {
            "id": r.id,
            "text": r.text,
            "meta": {
                "page": r.page_number,
                "doc_id": r.document_id
            }
        }

    for r in bm_results:

        if r.id not in candidates:

            candidates[r.id] = {
                "id": r.id,
                "text": r.text,
                "meta": {
                    "page": r.page_number,
                    "doc_id": r.document_id
                }
            }


    if not candidates:

        return {
            "answer": (
                "I couldn't find any relevant "
                "information."
            )
        }


    # --------------------------------------------------------
    # 5. Re-rank
    # --------------------------------------------------------

    passages = list(
        candidates.values()
    )

    rerank_request = RerankRequest(
        query=q.question,
        passages=passages
    )

    ranked_results = ranker.rerank(
        rerank_request
    )


    # --------------------------------------------------------
    # 6. Confidence Filtering
    # --------------------------------------------------------

    good_results = [
        r
        for r in ranked_results
        if r["score"] > 0.75
    ]

    top_results = (
        good_results[:7]
        if good_results
        else []
    )


    # --------------------------------------------------------
    # 7. Build Context + Sources
    # --------------------------------------------------------

    context_parts = []
    sources = []
    seen_pages = set()

    for r in top_results:

        page_number = r["meta"]["page"]
        doc_id = r["meta"]["doc_id"]

        context_parts.append(
            f"{r['text']} (Page {page_number})"
        )

        doc = (
            db.query(Document)
            .filter(Document.id == doc_id)
            .first()
        )

        doc_name = (
            doc.filename
            if doc
            else "Unknown PDF"
        )

        identifier = (
            doc_name,
            page_number
        )

        if identifier not in seen_pages:

            sources.append({
                "doc": doc_name,
                "page": page_number
            })

            seen_pages.add(identifier)

    context = "\n\n".join(
        context_parts
    )

    sources.sort(
        key=lambda x: (
            x["doc"],
            x["page"]
        )
    )


    # --------------------------------------------------------
    # 8. Chat History
    # --------------------------------------------------------

    history_text = ""

    if q.history:

        history_text = "Chat History:\n"

        for msg in q.history[-6:]:

            role = (
                "User"
                if msg.get("role") == "user"
                else "Assistant"
            )

            clean_msg = (
                msg.get("text", "")
                .replace("\n", " ")
            )

            history_text += (
                f"{role}: {clean_msg}\n"
            )


    # --------------------------------------------------------
    # 9. Generate Answer
    # --------------------------------------------------------

    prompt = f"""
You are a helpful AI assistant for a multi-document
question-answering system.

If the provided document context is relevant,
answer the user's question using the context.

Do not invent facts that contradict the documents.

If the context is empty or irrelevant for a casual
message such as "hello", "thanks", or "ok", respond
naturally using the conversation history.

{history_text}

DOCUMENT CONTEXT:
{context}

USER QUESTION:
{q.question}

ANSWER:
"""

    answer_text = generate_answer(prompt)


    return {
        "answer": answer_text,
        "sources": sources
    }