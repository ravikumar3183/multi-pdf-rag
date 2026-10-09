import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from database import SessionLocal, Document, Chunk


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError(
        "GEMINI_API_KEY is not configured."
    )

client = genai.Client(
    api_key=api_key
)

EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSIONS = 768


# ============================================================
# HELPERS
# ============================================================

def prepare_document_for_embedding(
    text_content: str,
    title: str | None = None
):

    if not title:
        title = "none"

    return (
        f"title: {title} | "
        f"text: {text_content}"
    )


def get_embedding(
    text_content: str,
    title: str
):

    content = types.Content(
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

    for attempt in range(3):

        try:

            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=content,
                config=types.EmbedContentConfig(
                    output_dimensionality=EMBEDDING_DIMENSIONS
                ),
            )

            if not response.embeddings:
                raise RuntimeError(
                    "No embedding returned."
                )

            embedding = response.embeddings[0].values

            if len(embedding) != EMBEDDING_DIMENSIONS:
                raise RuntimeError(
                    f"Expected {EMBEDDING_DIMENSIONS} dimensions, "
                    f"got {len(embedding)}."
                )

            return embedding

        except Exception as e:

            print(
                f"Embedding error "
                f"(attempt {attempt + 1}/3): {e}"
            )

            if attempt == 2:
                raise

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

def main():

    db = SessionLocal()

    try:

        chunks = (
            db.query(Chunk)
            .order_by(Chunk.id)
            .all()
        )

        total = len(chunks)

        print(
            f"Found {total} chunks to re-embed."
        )

        if total == 0:
            print("No chunks found.")
            return

        for index, chunk in enumerate(
            chunks,
            start=1
        ):

            document = (
                db.query(Document)
                .filter(
                    Document.id == chunk.document_id
                )
                .first()
            )

            title = (
                document.filename
                if document
                else "none"
            )

            print(
                f"[{index}/{total}] "
                f"Embedding chunk {chunk.id} "
                f"from {title}"
            )

            new_embedding = get_embedding(
                chunk.text,
                title
            )

            chunk.embedding = new_embedding

            db.commit()

            print(
                f"    ✓ Updated chunk {chunk.id}"
            )

            time.sleep(1)

        print()
        print(
            "========================================"
        )
        print(
            "Re-embedding completed successfully."
        )
        print(
            "========================================"
        )

    except Exception:

        db.rollback()
        raise

    finally:

        db.close()


if __name__ == "__main__":
    main()