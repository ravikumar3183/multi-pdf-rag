# Multi-PDF RAG Chatbot

Full-stack Retrieval-Augmented Generation (RAG) system:

- FastAPI backend (Python)
- PostgreSQL + pgvector for hybrid search (BM25 + vector similarity)
- SentenceTransformers for embeddings
- Gemini API for answer generation
- React (Vite) frontend with multi-PDF upload & chat UI

## Structure

- `backend/` – FastAPI app, database models, RAG logic
- `frontend/` – React/Vite UI, calls backend `/upload_pdfs` and `/ask`

## Local development

Backend:

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
