from sqlalchemy import create_engine, Column, Integer, Text, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from pgvector.sqlalchemy import Vector

DATABASE_URL = "postgresql+psycopg2://raguser:ragpassword@localhost:5432/ragdb"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    filename = Column(String)
    chunks = relationship("Chunk", back_populates="document")

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    text = Column(Text)
    embedding = Column(Vector(384))  # embedding dimension for MiniLM
    fts = Column(Text)               # full text (tsvector generated later)

    document = relationship("Document", back_populates="chunks")

def init_db():
    Base.metadata.create_all(bind=engine)
