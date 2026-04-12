import os
from typing import TypedDict, List

from langchain_core.documents import Document

from src.core.db import get_vector_store


# ── State ──────────────────────────────────────────────────────────────────────
# The state is the shared data that flows through the entire graph.
# Each node reads from state and returns updated state.

class RAGState(TypedDict):
    query: str
    retrieved_docs: List[Document]   # Output of Node 1 — wide retrieval (k=10)
    reranked_docs: List[Document]    # Output of Node 2 — narrowed by reranker (top_n=3)
    response: dict                   # Output of Node 3 — final structured answer


# ── Node 1: Vector Search ──────────────────────────────────────────────────────
# Uses a bi-encoder (Google Gemini embeddings) to find semantically similar chunks.
# We retrieve k=20 to cast a wide net — the reranker will narrow this down.

def vector_search_node(state: RAGState) -> RAGState:
    vector_store = get_vector_store()
    docs = vector_store.similarity_search(state["query"], k=20)
    print(f"[vector_search_node] Retrieved {len(docs)} chunks from PGVector")
    return {**state, "retrieved_docs": docs}
