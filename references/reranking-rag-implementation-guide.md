# Reranking RAG — Implementation Guide

> **Course Project 3** — Builds on Projects 1 & 2 (Naive RAG with Vector/FTS/RRF, Multimodal RAG with Docling).
> This project introduces **reranking** as a post-retrieval step to improve answer quality.

---

## Why Reranking?

In Naive RAG (Project 1), you used a **bi-encoder** for retrieval:

- The query is embedded into a vector → `query_vector`
- Each document chunk is embedded into a vector → `doc_vector`
- Relevance = cosine similarity between `query_vector` and `doc_vector`

**Problem:** The query and document are embedded _independently_. The model never sees them together, so it can miss subtle relevance cues.

A **cross-encoder reranker** fixes this:

- It receives the (query, document) pair _together_ as a single input
- It scores them jointly → far more accurate relevance judgment
- Trade-off: slower than a bi-encoder, so we only run it on the top-k candidates

**Pattern: Retrieve Wide → Rerank Narrow**

```
Bi-encoder retrieval (fast, k=10)  →  Cross-encoder reranker (accurate, top_n=3)
```

---

## Architecture

```
POST /api/v1/query
       │
       ▼
query_service.py
  └── run_vector_search_agent(query)
              │
              ▼
       ┌──────────────────────────────────────────────────────┐
       │               LangGraph RAG Pipeline                 │
       │                                                      │
       │  ┌─────────────────────┐                            │
       │  │  Node 1             │                            │
       │  │  vector_search_node │  PGVector similarity_search│
       │  │  (Gemini bi-encoder)│  k = 10 chunks             │
       │  └──────────┬──────────┘                            │
       │             │ retrieved_docs (10)                    │
       │             ▼                                        │
       │  ┌─────────────────────┐                            │
       │  │  Node 2             │                            │
       │  │  rerank_node        │  Cohere rerank-english-v3.0│
       │  │  (Cohere cross-enc) │  top_n = 3                 │
       │  └──────────┬──────────┘                            │
       │             │ reranked_docs (3)                      │
       │             ▼                                        │
       │  ┌─────────────────────┐                            │
       │  │  Node 3             │                            │
       │  │  generate_answer    │  Gemini LLM                │
       │  │  _node              │  Structured output         │
       │  └──────────┬──────────┘                            │
       │             │ response (AIResponse)                  │
       └─────────────┼────────────────────────────────────────┘
                     ▼
              FastAPI Response
```

---

## LangGraph Concepts Used

| LangGraph Concept | Where Used                                             |
| ----------------- | ------------------------------------------------------ |
| `TypedDict` State | `RAGState` — shared data bag flowing through all nodes |
| `StateGraph`      | The graph that wires nodes together                    |
| `add_node`        | Registers each processing step                         |
| `set_entry_point` | Marks `vector_search` as the start                     |
| `add_edge`        | Linear flow: search → rerank → generate                |
| `graph.compile()` | Produces the runnable graph                            |
| `graph.invoke()`  | Runs the full pipeline with initial state              |

---

## State Definition

```python
class RAGState(TypedDict):
    query: str                       # Input: user question
    retrieved_docs: List[Document]   # After Node 1: 10 candidate chunks
    reranked_docs: List[Document]    # After Node 2: top 3 chunks
    response: dict                   # After Node 3: final answer
```

Key idea: **each node only adds to the state — it never destroys previous data**. This lets trainees inspect `retrieved_docs` vs `reranked_docs` to see what the reranker changed.

---

## Tool — `vector_search` (`tools.py`)

The actual PGVector call lives in `src/api/v1/tools/tools.py`, keeping the node thin:

```python
def vector_search(query: str, k: int = 10) -> List[Document]:
    """Perform vector similarity search against PGVector and return top-k chunks."""
    vector_store = get_vector_store()
    return vector_store.similarity_search(query, k=k)
```

- Owns the `get_vector_store()` call — `agents.py` doesn't touch `db.py` directly
- `k` is a parameter — easy to change for experimentation

---

## Node 1 — Vector Search

```python
def vector_search_node(state: RAGState) -> RAGState:
    docs = vector_search(state["query"], k=10)
    return {**state, "retrieved_docs": docs}
```

- Delegates to the `vector_search` tool — the node only updates state
- `k=10`: retrieve more than you need so the reranker has candidates to choose from
- Embedding model: `gemini-embedding-2-preview` (1536 dimensions, configured in `db.py`)

---

## Node 2 — Rerank (the new step)

```python
def rerank_node(state: RAGState) -> RAGState:
    co = cohere.ClientV2(api_key=os.getenv("COHERE_API_KEY"))
    docs = state["retrieved_docs"]

    rerank_response = co.rerank(
        model="rerank-english-v3.0",
        query=state["query"],
        documents=[doc.page_content for doc in docs],
        top_n=3
    )

    reranked_docs = [docs[r.index] for r in rerank_response.results]
    return {**state, "reranked_docs": reranked_docs}
```

**What Cohere returns:**

- `r.index` — original position in the input list (maps back to the LangChain `Document`)
- `r.relevance_score` — cross-encoder confidence score (0 to 1, higher = more relevant)

**Teaching moment:** Print the scores in the classroom to show rank order changes:

```python
for i, r in enumerate(rerank_response.results):
    print(f"Rank {i+1} | score: {r.relevance_score:.4f} | original index: {r.index}")
```

You will often see the #1 vector similarity result NOT be the #1 reranker result.

---

## Node 3 — Generate Answer

```python
def generate_answer_node(state: RAGState) -> RAGState:
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GOOGLE_LLM_MODEL"),
        google_api_key=os.getenv("GOOGLE_API_KEY")
    )
    structured_llm = llm.with_structured_output(AIResponse)

    context = "\n\n".join([
        f"[Source: {doc.metadata.get('document_name', doc.metadata.get('source', 'unknown'))} | Page: {doc.metadata.get('page_label', doc.metadata.get('page', '?'))}]\n{doc.page_content}"
        for doc in state["reranked_docs"]
    ])

    prompt = ChatPromptTemplate.from_messages([
        ("system", "Answer using only the provided context. Cite source and page."),
        ("human", "Context:\n{context}\n\nQuestion: {query}")
    ])

    result = (prompt | structured_llm).invoke({"context": context, "query": state["query"]})
    return {**state, "response": result.model_dump()}
```

- Passes only the **3 reranked chunks** to the LLM (not all 10)
- Uses `with_structured_output(AIResponse)` to enforce schema (Pydantic model from `query_schema.py`)
- Source + page metadata is injected into the context so the LLM can cite properly

---

## Graph Wiring

```python
def build_rag_graph():
    graph = StateGraph(RAGState)

    graph.add_node("vector_search", vector_search_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("generate_answer", generate_answer_node)

    graph.set_entry_point("vector_search")
    graph.add_edge("vector_search", "rerank")
    graph.add_edge("rerank", "generate_answer")
    graph.add_edge("generate_answer", END)

    return graph.compile()
```

---

## Environment Variables Required

From `.env.example`:

| Variable                  | Used In              | Purpose                                 |
| ------------------------- | -------------------- | --------------------------------------- |
| `GOOGLE_API_KEY`          | `db.py`, `agents.py` | Gemini embeddings + LLM                 |
| `GOOGLE_EMBEDDING_MODEL`  | `db.py`              | e.g. `gemini-embedding-2-preview`       |
| `GOOGLE_LLM_MODEL`        | `agents.py`          | e.g. `gemini-2.0-flash`                 |
| `COHERE_API_KEY`          | `agents.py`          | Cohere Rerank API                       |
| `SQLALCHEMY_DATABASE_URL` | `db.py`              | PostgreSQL + pgvector connection string |

---

## Installation

```bash
uv add cohere
# or
uv sync   # picks up the cohere>=5.0.0 entry added to pyproject.toml
```

---

## File Change Summary

| File                                   | Change                                                      |
| -------------------------------------- | ----------------------------------------------------------- |
| `src/api/v1/agents/agents.py`          | **New** — full LangGraph pipeline (State + 3 nodes + graph) |
| `src/api/v1/tools/tools.py`            | **New** — `vector_search()` tool used by Node 1             |
| `src/api/v1/services/query_service.py` | Wired `run_vector_search_agent()` return value to response  |
| `src/ingestion/ingestion.py`           | Added `document_name` (clean basename) to chunk metadata    |
| `pyproject.toml`                       | Added `cohere>=5.0.0` dependency                            |

---

## Key Takeaway for Trainees

| Stage                | Model Type              | Speed  | Accuracy                  |
| -------------------- | ----------------------- | ------ | ------------------------- |
| Vector search (k=10) | Bi-encoder (embeddings) | Fast   | Good                      |
| Rerank (top_n=3)     | Cross-encoder (Cohere)  | Slower | Better                    |
| Answer generation    | Gemini LLM              | —      | Grounded in best 3 chunks |

The reranker doesn't replace vector search — it **refines** its results. You always need the fast bi-encoder first to create a candidate set, then the accurate cross-encoder to sort it.
