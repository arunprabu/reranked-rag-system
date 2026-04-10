from typing import List

from langchain_core.documents import Document

from src.core.db import get_vector_store


def vector_search(query: str, k: int = 10) -> List[Document]:
    """Perform vector similarity search against PGVector and return top-k chunks."""
    vector_store = get_vector_store()
    return vector_store.similarity_search(query, k=k)
