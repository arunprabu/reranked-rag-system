# Agentic RAG System with Reranking & NL2SQL

A LangGraph-powered agentic RAG system that intelligently routes queries between two pipelines:

- **Document route** — hybrid vector + full-text search over PDF documents, reranked with Cohere, answered by Gemini
- **Product route** — NL2SQL over a PostgreSQL e-commerce database using Gemini to generate and execute safe SELECT queries

Built with FastAPI, LangGraph, LangChain, PGVector, and OpenAI API

---

## Architecture

```
User Query
    │
    ▼
router_node  (Gemini structured output)
    │
    ├── "product" ──► nl2sql_node ──────────────────────────► END
    │                  (generate SQL → db.run() → summarise)
    │
    └── "document" ──► vector_search_node ──► rerank_node ──► generate_answer_node ──► END
                        (PGVector hybrid)      (Cohere)         (Gemini)
```

---

## Prerequisites

- Python 3.13+
- PostgreSQL with the `pgvector` extension (for document embeddings)
- A separate PostgreSQL database seeded from `sql/seed.sql` (for product/order data)
- API keys: Gpt 5.4, Cohere

---

## Setup

### 1. Clone and install

```bash
pip install -e .
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable                  | Purpose                              |
| ------------------------- | ------------------------------------ |
| `OPENAI_API_KEY`          | Gemini LLM & embeddings              |
| `OPENAI_CHAT_MODEL`       | OpenAI model name (e.g. `gpt-5.4`)   |
| `OPENAI_EMBEDDING_MODEL`  | Embedding model name                 |
| `COHERE_API_KEY`          | Cohere reranker                      |
| `SQLALCHEMY_DATABASE_URL` | PGVector store (document embeddings) |
| `AGENTIC_RAG_DB_URL`      | E-commerce DB for NL2SQL queries     |

### 3. Seed the e-commerce database

```bash
psql -U postgres -f sql/seed.sql
```

This creates the `agentic_rag_db` database with tables `products`, `categories`, `orders`, and `order_items`, plus a read-only role `rag_readonly`.

### 4. Start the server

```bash
uvicorn main:app --reload --port 8000
```

---

## API Endpoints

### `POST /api/v1/query`

Accepts a natural language query and routes it automatically.

**Request**

```json
{ "query": "What is the refund policy?" }
```

**Response**

```json
{
  "query": "What is the refund policy?",
  "answer": "...",
  "policy_citations": "Section 4.2 — Returns & Refunds",
  "page_no": "12",
  "document_name": "ecommerce-policy.pdf",
  "sql_query_executed": null
}
```

For product/database queries the response includes `sql_query_executed` and `policy_citations` is empty:

```json
{
  "query": "Top 5 most expensive products",
  "answer": "The top 5 most expensive products are ...",
  "policy_citations": "",
  "page_no": "N/A",
  "document_name": "agentic_rag_db",
  "sql_query_executed": "SELECT name, price FROM products ORDER BY price DESC LIMIT 5;"
}
```

### `POST /api/v1/admin/upload`

Upload a PDF to ingest into the PGVector store.

```bash
curl -X POST http://localhost:8000/api/v1/admin/upload \
  -F "file=@your-document.pdf"
```

### `GET /health`

Returns `{"status": "ok"}`.

---

## Project Structure

```
main.py                        # FastAPI app entry point
sql/seed.sql                   # E-commerce DB schema + seed data
data/                          # PDF documents for ingestion
uploaded_pdfs/                 # Runtime upload destination
src/
  api/v1/
    routes/query.py            # /query and /admin/upload endpoints
    services/query_service.py  # Orchestration layer
    agents/agents.py           # LangGraph graph (router + nl2sql + rag nodes)
    tools/tools.py             # RAGState TypedDict + vector_search_node
    schema/query_schema.py     # Pydantic request/response models
  core/db.py                   # PGVector + SQLDatabase connection factories
  ingestion/ingestion.py       # PDF chunking + embedding pipeline
references/
  agentic-rag-system-guide.md  # Step-by-step implementation guide for trainees
  reranking-rag-implementation-guide.md
```

---

## References

See [references/agentic-rag-system-guide.md](references/agentic-rag-system-guide.md) for a full step-by-step implementation walkthrough.
