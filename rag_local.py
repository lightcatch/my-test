from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

DEFAULT_PERSIST_DIR = Path("data/chroma_rag")
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_TOP_K = 4
DEFAULT_COLLECTION_NAME = "local_rag"
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 100


def _resolve_path(path_value: str | Path) -> Path:
    return Path(path_value).expanduser().resolve()


def _build_embeddings(embedding_model: str) -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _collect_source_files(doc_dir: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.txt", "*.md", "*.pdf"):
        files.extend(doc_dir.rglob(pattern))
    return sorted({path.resolve() for path in files})


def _load_documents(doc_dir: Path) -> tuple[list[Path], list[Document]]:
    source_files = _collect_source_files(doc_dir)
    documents: list[Document] = []

    for path in source_files:
        if path.suffix.lower() == ".pdf":
            pdf_docs = PyPDFLoader(str(path)).load()
            for doc in pdf_docs:
                doc.metadata["source"] = str(path)
            documents.extend(pdf_docs)
            continue

        text = path.read_text(encoding="utf-8").strip()
        if text:
            documents.append(Document(page_content=text, metadata={"source": str(path)}))

    return source_files, documents


def upload_docs(
    doc_dir: str | Path,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> dict[str, Any]:
    doc_dir_path = _resolve_path(doc_dir)
    persist_dir_path = _resolve_path(persist_dir)

    source_files, documents = _load_documents(doc_dir_path)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    if persist_dir_path.exists():
        shutil.rmtree(persist_dir_path)
    persist_dir_path.mkdir(parents=True, exist_ok=True)

    embeddings = _build_embeddings(embedding_model)
    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(persist_dir_path),
        collection_name=DEFAULT_COLLECTION_NAME,
    )
    if hasattr(vector_store, "persist"):
        vector_store.persist()

    return {
        "doc_dir": str(doc_dir_path),
        "persist_dir": str(persist_dir_path),
        "source_file_count": len(source_files),
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "embedding_model": embedding_model,
    }


def search_docs(
    query: str,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    top_k: int = DEFAULT_TOP_K,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> list[dict[str, str]]:
    persist_dir_path = _resolve_path(persist_dir)
    embeddings = _build_embeddings(embedding_model)
    vector_store = Chroma(
        persist_directory=str(persist_dir_path),
        embedding_function=embeddings,
        collection_name=DEFAULT_COLLECTION_NAME,
    )
    docs = vector_store.similarity_search(query, k=top_k)

    results: list[dict[str, str]] = []
    for doc in docs:
        results.append(
            {
                "source": str(doc.metadata.get("source", "")),
                "content": (doc.page_content or "").strip(),
            }
        )
    return results
