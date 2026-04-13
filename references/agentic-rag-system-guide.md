# Agentic RAG System — Complete Implementation Guide

> **Course Project 4** — Extends Project 3 (Reranking RAG) with:
>
> - A **LangGraph router** that classifies every incoming query
> - A **NL2SQL tool** that answers product/order questions directly from PostgreSQL
> - The existing **Reranking RAG pipeline** that handles document-based questions

---

## Table of Contents

1. [What Is Agentic RAG?](#1-what-is-agentic-rag)
2. [Architecture Overview](#2-architecture-overview)
3. [Database Schema (agentic_rag_db)](#3-database-schema-agentic_rag_db)
4. [Prerequisites and Setup](#4-prerequisites-and-setup)
5. [Step 1 — Seed the PostgreSQL Database](#step-1--seed-the-postgresql-database)
6. [Step 2 — Configure Environment Variables](#step-2--configure-environment-variables)
7. [Step 3 — Install Dependencies](#step-3--install-dependencies)
8. [Step 4 — Add get_sql_database() to db.py](#step-4--add-get_sql_database-to-dbpy)
9. [Step 5 — Extend RAGState in tools.py](#step-5--extend-ragstate-in-toolspy)
10. [Step 6 — Build router_node](#step-6--build-router_node)
11. [Step 7 — Build nl2sql_node](#step-7--build-nl2sql_node)
12. [Step 8 — Wire the LangGraph with Conditional Edges](#step-8--wire-the-langgraph-with-conditional-edges)
13. [How NL2SQL Works (Deep Dive)](#13-how-nl2sql-works-deep-dive)
14. [How the Router Works (Deep Dive)](#14-how-the-router-works-deep-dive)
15. [Security — Why the Read-Only Role Matters](#15-security--why-the-read-only-role-matters)
16. [Testing the System](#16-testing-the-system)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. What Is Agentic RAG?

A **standard RAG** pipeline always does the same thing:

```
User Query → Embed → Vector Search → Rerank → LLM → Answer
```

It works great for document-grounded questions, but it is the wrong tool when
the question is actually answered by structured data sitting in a relational
database. Examples:

| Question                                      | Best Tool                     |
| --------------------------------------------- | ----------------------------- |
| "What are the cheapest Electronics products?" | SQL query on `products` table |
| "How many orders are in 'shipped' status?"    | SQL query on `orders` table   |
| "Explain the company's refund policy"         | RAG (document search)         |
| "What does the manual say about returns?"     | RAG (document search)         |

An **Agentic RAG** system adds a **router** that inspects the query first and
dispatches it to the right tool. The LangGraph framework lets us model this as
a graph with **conditional edges** — branching logic based on the router's decision.

---

## 2. Architecture Overview

```
POST /api/v1/query
       │
       ▼
 query_service.py
   └── run_vector_search_agent(query)
               │
               ▼
     ┌─────────────────────────────────────────────────────────────────────┐
     │                        LangGraph Pipeline                           │
     │                                                                     │
     │  ┌───────────────────┐                                              │
     │  │  Node 0           │  Gemini classifies query intent              │
     │  │  router_node      │  Output: route = "product" | "document"      │
     │  └────────┬──────────┘                                              │
     │           │                                                         │
     │     ┌─────┴──────┐                                                  │
     │     │            │                                                  │
     │  "product"  "document"                                              │
     │     │            │                                                  │
     │     ▼            ▼                                                  │
     │  ┌──────────┐  ┌──────────────────────┐                            │
     │  │nl2sql    │  │vector_search_node     │  Gemini bi-encoder k=20    │
     │  │_node     │  │(PGVector similarity)  │                            │
     │  └────┬─────┘  └──────────┬───────────┘                            │
     │       │                   │  retrieved_docs (20)                    │
     │       │        ┌──────────▼───────────┐                            │
     │       │        │rerank_node            │  Cohere cross-encoder      │
     │       │        │(Cohere rerank-v3)     │  top_n=10                  │
     │       │        └──────────┬────────────┘                           │
     │       │                   │  reranked_docs (10)                     │
     │       │        ┌──────────▼───────────┐                            │
     │       │        │generate_answer_node   │  Gemini LLM → AIResponse   │
     │       │        └──────────┬────────────┘                           │
     │       │                   │                                         │
     │       └──────────────────►│◄── both paths converge                 │
     │                           ▼                                         │
     │                          END                                        │
     └─────────────────────────────────────────────────────────────────────┘
               │
               ▼
         AIResponse (JSON)
           • query
           • answer
           • policy_citations      ← text citation (document route only, empty for product route)
           • page_no              ← page number (document route) / "N/A" (product route)
           • document_name        ← source doc name / "agentic_rag_db" (product route)
           • sql_query_executed   ← the SQL that ran (product route only, null for document route)
```

---

## 3. Database Schema (agentic_rag_db)

The seed script (`sql/seed.sql`) creates a simple e-commerce schema with four
tables and one read-only database user.

### Tables

```
┌─────────────────────────────────────────────────────────────┐
│  categories                                                  │
│  ─────────────────────────────────────────────────────────  │
│  id            SERIAL PK                                     │
│  name          VARCHAR(100)  — e.g. "Electronics", "Books"  │
│  description   TEXT                                         │
│  created_at    TIMESTAMPTZ                                   │
└─────────────────────────────────────────────────────────────┘
         │ 1
         │
         │ N
┌─────────────────────────────────────────────────────────────┐
│  products                                                    │
│  ─────────────────────────────────────────────────────────  │
│  id             SERIAL PK                                    │
│  name           VARCHAR(200)                                 │
│  category_id    INT  FK → categories.id                      │
│  price          NUMERIC(10,2)                                │
│  stock_quantity INT                                          │
│  description    TEXT                                        │
│  is_active      BOOLEAN  — FALSE = discontinued              │
│  created_at     TIMESTAMPTZ                                  │
└─────────────────────────────────────────────────────────────┘
                                    │ N
                                    │       (via order_items)
┌───────────────────────────────────┼─────────────────────────┐
│  orders                           │                         │
│  ──────────────────────────────   │  order_items            │
│  id             SERIAL PK         │  ────────────────────── │
│  customer_name  VARCHAR(200)      │  id          SERIAL PK  │
│  customer_email VARCHAR(200)      │  order_id    FK→orders  │
│  total_amount   NUMERIC(10,2)     │  product_id  FK→products│
│  status         VARCHAR(50)  ─────┘  quantity    INT        │
│    (pending | confirmed |            unit_price  NUMERIC    │
│     shipped | delivered |                                   │
│     cancelled)                                              │
│  created_at     TIMESTAMPTZ                                 │
└─────────────────────────────────────────────────────────────┘
```

### Seed Data Summary

| Table       | Rows                                                                                               |
| ----------- | -------------------------------------------------------------------------------------------------- |
| categories  | 7 (Electronics, Books, Clothing, Home & Kitchen, Sports & Outdoors, Toys & Games, Health & Beauty) |
| products    | 25 (mix of active and discontinued)                                                                |
| orders      | 12 (various statuses)                                                                              |
| order_items | ~30 line items                                                                                     |

### Read-Only User

```
username: rag_readonly
password: rag_readonly_pass
privileges: SELECT only on all tables in agentic_rag_db
```

---

## 4. Prerequisites and Setup

| Requirement       | Version                    |
| ----------------- | -------------------------- |
| Python            | 3.13+                      |
| PostgreSQL        | 14+                        |
| Google AI API key | Gemini models enabled      |
| Cohere API key    | rerank-english-v3.0 access |

---

## Step 1 — Seed the PostgreSQL Database

Connect to PostgreSQL as a superuser and run the seed script.

```bash
# Option A — using the postgres superuser
psql -U postgres -f sql/seed.sql

# Option B — if your system uses a different superuser
psql -U <your_superuser> -f sql/seed.sql
```

What the script does, in order:

1. Drops and recreates `agentic_rag_db` (clean slate — comment this out in production)
2. Creates the `rag_readonly` role with `LOGIN` and an encrypted password
3. Connects (`\c agentic_rag_db`) and creates the four tables
4. Inserts 7 categories, 25 products, 12 orders, and ~30 order items
5. Grants `USAGE` on the `public` schema and `SELECT` on all tables to `rag_readonly`
6. Sets `default_transaction_read_only = on` for `rag_readonly` — even DDL/DML
   attempted programmatically will be rejected at the session level

Verify the setup:

```bash
psql -U rag_readonly -d agentic_rag_db -c "SELECT COUNT(*) FROM products;"
# Expected: 25

psql -U rag_readonly -d agentic_rag_db -c "INSERT INTO products (name, price) VALUES ('hack', 1);"
# Expected: ERROR — read-only transaction
```

---

## Step 2 — Configure Environment Variables

Copy `.env.example` to `.env` and fill in your real values:

```bash
cp .env.example .env
```

Your `.env` should contain:

```dotenv
# LLM and Embeddings
COHERE_API_KEY=<your_cohere_key>
GOOGLE_API_KEY=<your_google_key>
GOOGLE_EMBEDDING_MODEL=gemini-embedding-2-preview
GOOGLE_LLM_MODEL=gemini-2.0-flash

# PGVector store — for document embeddings (RAG path)
SQLALCHEMY_DATABASE_URL=postgresql+psycopg://your_user:your_password@localhost:5432/your_pgvector_db

# Agentic RAG e-commerce DB — for the NL2SQL tool (product path)
AGENTIC_RAG_DB_URL=postgresql+psycopg://rag_readonly:rag_readonly_pass@localhost:5432/agentic_rag_db
```

> **Why two connection strings?**
> `SQLALCHEMY_DATABASE_URL` points to your PGVector store where document embeddings
> live. `AGENTIC_RAG_DB_URL` points to `agentic_rag_db` which holds the e-commerce
> tables. They are intentionally separate databases.

---

## Step 3 — Install Dependencies

```bash
# Activate your virtual environment first
source .venv/bin/activate

# Install all project dependencies (including psycopg2-binary, now in pyproject.toml)
pip install -e .
```

`psycopg2-binary` is required by LangChain's `SQLDatabase` utility for connecting
to PostgreSQL via SQLAlchemy. The `psycopg` (v3) driver is already present for
PGVector — the two coexist without conflict.

---

## Step 4 — Add get_sql_database() to db.py

**File:** `src/core/db.py`

```python
from langchain_community.utilities import SQLDatabase

def get_sql_database() -> SQLDatabase:
    """Return a LangChain SQLDatabase connected to agentic_rag_db (read-only).

    Uses the rag_readonly role from sql/seed.sql — SELECT privileges only.
    Connection string is read from AGENTIC_RAG_DB_URL in the environment.
    """
    db_url = os.getenv("AGENTIC_RAG_DB_URL")
    if not db_url:
        raise ValueError("AGENTIC_RAG_DB_URL is not set. Check your .env file.")
    return SQLDatabase.from_uri(
        db_url,
        include_tables=["products", "categories", "orders", "order_items"],
        sample_rows_in_table_info=2,  # helps the LLM understand column values
    )
```

**What `SQLDatabase.from_uri()` does:**

- Connects to PostgreSQL using SQLAlchemy
- Introspects the schema: column names, types, foreign keys
- Optionally samples a few rows from each table so the LLM has concrete
  examples to reason about (controlled by `sample_rows_in_table_info`)
- Returns a helper object with a `.run(sql)` method for safe execution

**Why `include_tables`?**

Without it, `SQLDatabase` would expose every table including PGVector's internal
`langchain_pg_embedding` table. Explicitly listing only your four e-commerce
tables keeps the LLM's schema context small and accurate.

---

## Step 5 — Extend RAGState in tools.py

**File:** `src/api/v1/tools/tools.py`

LangGraph passes a single `state` dictionary through all nodes. You must declare
every field the graph will ever write up-front in the `TypedDict`.

```python
class RAGState(TypedDict):
    query: str
    retrieved_docs: List[Document]   # RAG path — wide retrieval (k=20)
    reranked_docs: List[Document]    # RAG path — narrowed by reranker
    response: dict                   # Final structured answer (both paths)
    route: str                       # "product" or "document" — set by router_node
    generated_sql: str               # The SQL generated by nl2sql_node
    sql_result: str                  # Raw SQL execution result
```

New fields added for the NL2SQL path:

| Field           | Set By        | Purpose                                |
| --------------- | ------------- | -------------------------------------- |
| `route`         | `router_node` | Conditional edge decision              |
| `generated_sql` | `nl2sql_node` | Traceability / debugging               |
| `sql_result`    | `nl2sql_node` | Raw DB output before LLM summarises it |

---

## Step 6 — Build router_node

**File:** `src/api/v1/agents/agents.py`

The router uses Gemini's **structured output** to classify the query deterministically.

```python
from typing import Literal
from pydantic import BaseModel

class _RouteDecision(BaseModel):
    route: Literal["product", "document"]
    reason: str

def router_node(state: RAGState) -> RAGState:
    llm = _get_llm()
    structured_llm = llm.with_structured_output(_RouteDecision)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """You are a query router for an agentic RAG system.
Classify the user's query into EXACTLY one of two routes:

  "product"  — the query asks about products, product prices, stock/inventory,
               product categories, customer orders, order items, or anything
               answerable from a structured e-commerce database with tables:
               products, categories, orders, order_items.

  "document" — the query asks about policies, procedures, guidelines,
               regulations, or any topic that requires reading text documents.

Reply with the route and a one-sentence reason."""
        ),
        ("human", "Query: {query}")
    ])

    chain = prompt | structured_llm
    decision = chain.invoke({"query": state["query"]})
    print(f"[router_node] Route → '{decision.route}' | Reason: {decision.reason}")
    return {**state, "route": decision.route}
```

**Key concepts:**

- **`Literal["product", "document"]`** — Pydantic restricts the output to exactly
  these two strings. Any other value raises a validation error at runtime, which
  is safer than free-form string matching.
- **`with_structured_output(_RouteDecision)`** — LangChain adds a JSON schema
  constraint to the Gemini API call. The model is forced to respond with a valid
  `_RouteDecision` object.
- **`{**state, "route": decision.route}`\*\* — The standard LangGraph pattern for
  updating state: spread all existing fields and override the one you changed.

---

## Step 7 — Build nl2sql_node

**File:** `src/api/v1/agents/agents.py`

The NL2SQL node has three responsibilities:

### 7.1 — Generate SQL

```python
schema_info = db.get_table_info()

sql_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are a PostgreSQL expert. Given the database schema below, write a single
valid SELECT query that answers the user's question.

Rules:
- Return ONLY the raw SQL — no explanation, no markdown fences, no backticks.
- Use only the tables and columns present in the schema.
- Do NOT generate INSERT, UPDATE, DELETE, DROP, or any DML/DDL statements.
- Always add a LIMIT clause (max 50 rows) unless the question asks for aggregates.
- For product or text searches: NEVER search for the full multi-word phrase as one
  ILIKE pattern. Instead, split the search into individual meaningful keywords and
  OR them together across both name and description columns.
  Example — user asks "wireless headset":
    WHERE (name ILIKE '%wireless%' OR description ILIKE '%wireless%')
       OR (name ILIKE '%headset%'  OR description ILIKE '%headset%')
       OR (name ILIKE '%headphones%' OR description ILIKE '%headphones%')
  Use your knowledge of synonyms (headset/headphones, laptop/notebook, etc.)
  to cast a wider net when the exact term may not match.

Database schema:
{schema}"""
    ),
    ("human", "Question: {question}")
])

sql_chain = sql_prompt | llm
raw_sql = sql_chain.invoke({"schema": schema_info, "question": state["query"]})
```

This approach uses `db.get_table_info()` directly (live schema introspection) and
passes the schema into a custom prompt. **No external chain library is needed** —
just a `ChatPromptTemplate | llm` pipe.

Key rules enforced in the prompt:

- One keyword per ILIKE clause, not a full phrase — prevents zero-result misses
  (e.g. user says "headset", database has "headphones")
- Synonym expansion — the LLM is told to apply domain knowledge
- SELECT-only guard and LIMIT clause for safety and performance

**Strip Markdown fences** in case the model wraps the SQL in triple backticks:

````python
content = raw_sql.content
if isinstance(content, list):          # Gemini may return a list of parts
    content = "".join(
        p.get("text", "") if isinstance(p, dict) else str(p)
        for p in content
    )
generated_sql = content.strip().strip("```").strip()
if generated_sql.lower().startswith("sql"):
    generated_sql = generated_sql[3:].strip()
````

### 7.2 — Execute SQL

```python
try:
    sql_result = db.run(generated_sql)
except Exception as exc:
    sql_result = f"SQL execution error: {exc}"
```

`db.run()` uses the `rag_readonly` role — it cannot write, drop, or alter
anything. If the LLM hallucinated an `INSERT` or `DROP`, the database role
blocks it.

### 7.3 — Summarise into AIResponse

```python
structured_llm = llm.with_structured_output(AIResponse)
answer_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a helpful data analyst. Answer the user's question using "
        "the SQL query results below. Be concise and format numbers/lists clearly. "
        "Set policy_citations to empty string, "
        "page_no to 'N/A', and document_name to 'agentic_rag_db'."
    ),
    (
        "human",
        "Question: {query}\n\nSQL Used:\n{sql}\n\nQuery Results:\n{result}"
    )
])
chain = answer_prompt | structured_llm
answer = chain.invoke({
    "query": state["query"],
    "sql": generated_sql,
    "result": sql_result
})
response = answer.model_dump()
response["policy_citations"] = ""
response["sql_query_executed"] = generated_sql
```

After the LLM returns the structured answer, `policy_citations` is cleared and
`sql_query_executed` is populated with the actual SQL. This keeps the field
semantically correct — citations are for documents, SQL belongs in its own field.
Trainees can inspect `sql_query_executed` in any response to see exactly what
the agent ran against the database.

---

## Step 8 — Wire the LangGraph with Conditional Edges

**File:** `src/api/v1/agents/agents.py`

```python
def build_rag_graph():
    graph = StateGraph(RAGState)

    # Register all nodes
    graph.add_node("router",         router_node)
    graph.add_node("nl2sql",         nl2sql_node)
    graph.add_node("vector_search",  vector_search_node)
    graph.add_node("rerank",         rerank_node)
    graph.add_node("generate_answer", generate_answer_node)

    # Entry point is now the router, not vector_search
    graph.set_entry_point("router")

    # Conditional branching: read state["route"] to pick next node
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"],   # selector function
        {
            "product":  "nl2sql",
            "document": "vector_search",
        }
    )

    # NL2SQL path ends immediately after one node
    graph.add_edge("nl2sql", END)

    # RAG path: three sequential nodes
    graph.add_edge("vector_search", "rerank")
    graph.add_edge("rerank",        "generate_answer")
    graph.add_edge("generate_answer", END)

    return graph.compile()
```

**How `add_conditional_edges` works:**

```
add_conditional_edges(
    source_node,        ← which node triggers the branch
    selector_fn,        ← a function that receives state and returns a key
    mapping dict        ← key → next node name
)
```

LangGraph calls `selector_fn(state)` after `source_node` finishes and uses the
return value as a key into the mapping dict to find the next node.

---

## 13. How NL2SQL Works (Deep Dive)

```
Natural Language Question
         │
         ▼
┌───────────────────────────────────────────────────────────────┐
│ Custom Gemini SQL prompt  (db.get_table_info() injected)      │
│                                                               │
│  Prompt includes:                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Rules: SELECT only, LIMIT 50, keyword-per-ILIKE,       │  │
│  │        synonym expansion                               │  │
│  │                                                        │  │
│  │ Table: products                                        │  │
│  │                                                        │  │
│  │ Table: products                                        │  │
│  │   columns: id, name, category_id, price, stock_quantity│  │
│  │   sample rows:                                         │  │
│  │     (1, 'Wireless Headphones', 1, 149.99, 85)          │  │
│  │     (2, 'Mechanical Keyboard', 1, 89.99, 120)          │  │
│  │                                                        │  │
│  │ Table: categories  ... (similar structure)             │  │
│  │ Table: orders      ...                                 │  │
│  │ Table: order_items ...                                 │  │
│  │                                                        │  │
│  │ Question: "What are the top 3 most expensive products?"│  │
│  └────────────────────────────────────────────────────────┘  │
│                         │                                     │
│                         ▼  Gemini generates                   │
│              SELECT name, price FROM products                 │
│              ORDER BY price DESC LIMIT 3;                     │
└───────────────────────────────────────────────────────────────┘
         │
         ▼  db.run()  (rag_readonly — SELECT only)
  Raw result string:
  "[('LEGO Technic Bugatti Chiron', 369.99),
    ('Adjustable Dumbbell Set', 299.99),
    ('4K USB-C Monitor 27\"', 329.99)]"
         │
         ▼  Gemini (structured output) + post-processing
  AIResponse:
    answer: "The 3 most expensive products are:
             1. 4K USB-C Monitor 27\" — $329.99
             2. LEGO Technic Bugatti Chiron — $369.99
             3. Adjustable Dumbbell Set — $299.99"
    policy_citations: ""   ← empty for product route
    page_no: "N/A"
    document_name: "agentic_rag_db"
    sql_query_executed: "SELECT name, price FROM products ORDER BY price DESC LIMIT 3;"
```

---

## 14. How the Router Works (Deep Dive)

The router is a **zero-shot classifier** powered by Gemini. It works because:

1. **Structured output** forces a binary decision — no ambiguous free text.
2. **Prompt engineering** gives the model a precise description of each route
   along with the exact table names available in the SQL path.
3. **Literal type constraint** (`Literal["product", "document"]`) means any
   hallucinated third category raises a Pydantic validation error immediately.

Example classifications:

| Query                                           | Expected Route | Reasoning                                |
| ----------------------------------------------- | -------------- | ---------------------------------------- |
| "What is the price of the Mechanical Keyboard?" | `product`      | Price is a column in `products`          |
| "List all orders placed in the last 7 days"     | `product`      | Orders table in `agentic_rag_db`         |
| "Which category has the most products?"         | `product`      | JOIN between `categories` and `products` |
| "What is the company's return policy?"          | `document`     | Text document, not in DB                 |
| "Explain the loan approval process"             | `document`     | Policy document                          |
| "How many Vitamin D products are in stock?"     | `product`      | `stock_quantity` in `products`           |

---

## 15. Security — Why the Read-Only Role Matters

The `rag_readonly` PostgreSQL role is the **last line of defence** against SQL
injection or LLM prompt injection attacks.

**Defence layers in this system:**

| Layer               | Mechanism                                                                                                   |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| 1. Prompt design    | Custom SQL prompt explicitly forbids `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, and DML/DDL statements |
| 2. Database role    | `rag_readonly` has only `SELECT` privileges — any write/drop attempt fails at the DB level                  |
| 3. Session setting  | `default_transaction_read_only = on` for `rag_readonly` — even `BEGIN; DROP TABLE` fails                    |
| 4. `include_tables` | `SQLDatabase` only exposes the four business tables — internal PGVector tables are hidden                   |

**What happens if the LLM generates a malicious query?**

```sql
-- LLM output (would never be reached past layer 1, but hypothetically)
DROP TABLE products;
```

```
ERROR:  permission denied for table products
       (rag_readonly can only SELECT)
```

The `try/except` in `nl2sql_node` catches the error and returns it in
`sql_result`, which Gemini then reports as a friendly error message to the user.

---

## 16. Testing the System

### Start the server

```bash
uvicorn main:app --reload
```

### Test product route (NL2SQL)

```bash
# List products by price
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the top 5 most expensive products?"}' | python3 -m json.tool

# Stock check
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Which products have stock below 50 units?"}' | python3 -m json.tool

# Orders analysis
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How many orders are in pending status?"}' | python3 -m json.tool

# Category breakdown
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "List all products in the Sports & Outdoors category with their prices"}' | python3 -m json.tool
```

Expected shape of response for a product query:

```json
{
  "query": "What are the top 5 most expensive products?",
  "answer": "The 5 most expensive products are:\n1. LEGO Technic Bugatti Chiron — $369.99\n...",
  "policy_citations": "",
  "page_no": "N/A",
  "document_name": "agentic_rag_db",
  "sql_query_executed": "SELECT name, price FROM products ORDER BY price DESC LIMIT 5;"
}
```

`sql_query_executed` contains the exact SQL that ran — trainees can copy it into
`psql` to verify results independently. `policy_citations` is intentionally empty
for product queries (it is only populated on the document/RAG path).

### Test document route (Reranking RAG)

```bash
# This should route to the RAG pipeline (requires a PDF to be uploaded first)
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the minimum CIBIL score for a personal loan?"}' | python3 -m json.tool
```

### Verify routing in server logs

When the server is running with `--reload`, watch the console output:

```
[router_node] Route → 'product' | Reason: The query asks about product prices in the database.
[nl2sql_node] Generated SQL:
SELECT name, price FROM products ORDER BY price DESC LIMIT 5;
[nl2sql_node] Raw result (truncated): ...
[nl2sql_node] Answer generated.
```

or for the document path:

```
[router_node] Route → 'document' | Reason: The query is about loan policy documents.
[vector_search_node] Retrieved 20 chunks from PGVector
[rerank_node] Top 10 chunks after reranking:
  Rank 1 | Cohere score: 0.9821 | original index: 3
  ...
[generate_answer_node] Answer generated.
```

---

## 17. Troubleshooting

### `AGENTIC_RAG_DB_URL is not set`

Your `.env` file is missing the variable. Copy from `.env.example` and fill in
real values. Make sure `load_dotenv(override=True)` runs before the function is called.

### `psycopg2.OperationalError: could not connect to server`

PostgreSQL is not running, or the host/port in `AGENTIC_RAG_DB_URL` is wrong.
Check with: `psql -U rag_readonly -d agentic_rag_db -c "SELECT 1;"`

### `role "rag_readonly" does not exist`

The seed script was not run, or was run against the wrong instance.
Re-run: `psql -U postgres -f sql/seed.sql`

### LLM returns SQL with Markdown fences

Already handled in `nl2sql_node` with the strip logic. If you see a new format,
add it to the strip chain.

### Router always returns `"document"` for product questions

Check that the system prompt lists the table names explicitly. The model needs
concrete hints (`products, categories, orders, order_items`) to make the right call.

### `ModuleNotFoundError: langchain_community`

Run `pip install -e .` again — `langchain-community` is in `pyproject.toml`.

### SQL runs but returns empty results

Run the query directly in `psql` to verify data exists. The seed may not have
run to completion — check for errors in the `psql` output.

---

## File Reference

| File                                                                            | Role                                                                                     |
| ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [sql/seed.sql](../sql/seed.sql)                                                 | Creates `agentic_rag_db`, `rag_readonly` role, schema, and seed data                     |
| [.env.example](../.env.example)                                                 | Template for all required environment variables                                          |
| [src/core/db.py](../src/core/db.py)                                             | `get_vector_store()` + `get_sql_database()`                                              |
| [src/api/v1/tools/tools.py](../src/api/v1/tools/tools.py)                       | `RAGState` definition + `vector_search_node`                                             |
| [src/api/v1/agents/agents.py](../src/api/v1/agents/agents.py)                   | `router_node`, `nl2sql_node`, `rerank_node`, `generate_answer_node`, `build_rag_graph()` |
| [src/api/v1/services/query_service.py](../src/api/v1/services/query_service.py) | Thin wrapper calling `run_vector_search_agent()`                                         |
| [src/api/v1/routes/query.py](../src/api/v1/routes/query.py)                     | FastAPI route handlers                                                                   |
| [src/api/v1/schema/query_schema.py](../src/api/v1/schema/query_schema.py)       | `AIResponse`, `QueryRequest` Pydantic models                                             |
