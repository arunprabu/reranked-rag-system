# Step-by-Step: Build an Agentic RAG that Connects to an RDBMS

> A hands-on, build-it-from-scratch guide for the **NL2SQL** path of this project.
>
> By the end you will have a LangGraph agent that, for every incoming question,
> decides whether to **query a PostgreSQL database** (structured data) or fall
> back to the **document RAG pipeline** (unstructured PDFs) — and answers safely
> through a read-only database role.

This guide describes exactly what lives in this branch (`nl2sql-agentic-rag`).
Every code block matches the real files. The chat model is **OpenAI**
(`ChatOpenAI`); you can swap it for any LangChain chat model without changing the
structure.

---

## Table of Contents

1. [The Idea: Why "Agentic"?](#1-the-idea-why-agentic)
2. [Architecture at a Glance](#2-architecture-at-a-glance)
3. [Prerequisites](#3-prerequisites)
4. [Step 1 — Seed the e-commerce database](#step-1--seed-the-e-commerce-database)
5. [Step 2 — Configure environment variables](#step-2--configure-environment-variables)
6. [Step 3 — Install the SQL dependencies](#step-3--install-the-sql-dependencies)
7. [Step 4 — Add a read-only SQL connection (`db.py`)](#step-4--add-a-read-only-sql-connection-dbpy)
8. [Step 5 — Extend the graph state (`tools.py`)](#step-5--extend-the-graph-state-toolspy)
9. [Step 6 — Build the router node](#step-6--build-the-router-node)
10. [Step 7 — Build the NL2SQL node](#step-7--build-the-nl2sql-node)
11. [Step 8 — Wire the LangGraph with conditional edges](#step-8--wire-the-langgraph-with-conditional-edges)
12. [Step 9 — Expose it through the API](#step-9--expose-it-through-the-api)
13. [Step 10 — Run and test](#step-10--run-and-test)
14. [Security: the read-only role is your seatbelt](#14-security-the-read-only-role-is-your-seatbelt)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. The Idea: Why "Agentic"?

A plain RAG pipeline always does the same thing:

```
Question → Embed → Vector Search → Rerank → LLM → Answer
```

That is perfect for "What does the HR policy say about leave?" but the wrong tool
for "How many orders are still pending?" — that answer lives in a database table,
not a PDF.

An **agentic** system adds a **decision step**. A _router_ inspects the question
first and dispatches it to the right tool:

| Question                                   | Route      | Tool                       |
| ------------------------------------------ | ---------- | -------------------------- |
| "What are the 5 most expensive products?"  | `product`  | NL2SQL → PostgreSQL        |
| "How many orders are in 'shipped' status?" | `product`  | NL2SQL → PostgreSQL        |
| "What are the HR helpdesk working hours?"  | `document` | Reranking RAG → PDF chunks |
| "Explain the refund policy"                | `document` | Reranking RAG → PDF chunks |

We model this in **LangGraph** as a graph with **conditional edges** — the path
through the graph depends on the router's decision.

---

## 2. Architecture at a Glance

```
POST /api/v1/query
        │
        ▼
  run_search_agent(query)                     (agents.py)
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │                      LangGraph Pipeline                       │
 │                                                              │
 │   router_node          → classifies: route = product|document│
 │      │                                                       │
 │   ┌──┴───────────┐                                           │
 │  product      document                                       │
 │   │              │                                           │
 │   ▼              ▼                                           │
 │ nl2sql_node    vector_search_node  (PGVector, k=20)          │
 │   │              │                                           │
 │   │            rerank_node         (Cohere cross-encoder)    │
 │   │              │                                           │
 │   │            generate_answer_node                          │
 │   │              │                                           │
 │   └──────► END ◄─┘                                           │
 └──────────────────────────────────────────────────────────────┘
        │
        ▼
   AIResponse (JSON): query, answer, policy_citations,
                      page_no, document_name, sql_query_executed
```

The **product** path is one node (`nl2sql_node`). The **document** path is the
existing three-node reranking pipeline. Both converge on `END` and return the
same `AIResponse` shape, so the API contract never changes.

---

## 3. Prerequisites

| Requirement    | Notes                                                  |
| -------------- | ------------------------------------------------------ |
| Python         | 3.13+                                                  |
| PostgreSQL     | 14+ (one instance is fine — we use two databases)      |
| OpenAI API key | for `ChatOpenAI` (router, SQL generation, summarising) |
| Cohere API key | for the document path's reranker                       |

> **Two databases, one server.** The PGVector store (document embeddings) and the
> `agentic_rag_db` (e-commerce tables) are separate databases. They can live on
> the same PostgreSQL server; they just have different connection strings.

---

## Step 1 — Seed the e-commerce database

The script `sql/seed.sql` builds everything the NL2SQL tool needs: the database,
a **read-only role**, the schema (`categories`, `products`, `orders`,
`order_items`), and realistic sample data.

```bash
# Run as a PostgreSQL superuser
psql -U postgres -f sql/seed.sql
```

What it does, in order:

1. Drops & recreates `agentic_rag_db` (clean slate — comment out in production).
2. Creates the `rag_readonly` login role.
3. Creates the four tables.
4. Seeds 7 categories, 25 products, 12 orders, ~30 order items.
5. Grants **`SELECT` only** to `rag_readonly`.
6. Sets `default_transaction_read_only = on` for `rag_readonly` — a session-level
   safety net.

Verify it — the second command **must fail**:

```bash
psql -U rag_readonly -d agentic_rag_db -c "SELECT COUNT(*) FROM products;"
# Expected: 25

psql -U rag_readonly -d agentic_rag_db -c "INSERT INTO products (name, price) VALUES ('hack', 1);"
# Expected: ERROR — cannot execute INSERT in a read-only transaction
```

---

## Step 2 — Configure environment variables

Copy the template and fill in real values:

```bash
cp .env.example .env
```

```dotenv
# LLM + reranker
OPENAI_API_KEY=sk-...
OPENAI_CHAT_MODEL=gpt-4o-mini          # any ChatOpenAI-compatible model
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
COHERE_API_KEY=...

# PGVector store — document embeddings (the RAG/document path)
PG_CONNECTION_STRING=postgresql+psycopg://your_user:your_password@localhost:5432/your_pgvector_db

# e-commerce DB — the NL2SQL tool (the product path)
# Credentials match sql/seed.sql — rag_readonly is SELECT-only
AGENTIC_RAG_DB_URL=postgresql+psycopg://rag_readonly:rag_readonly_pass@localhost:5432/agentic_rag_db
```

> **Why a separate `AGENTIC_RAG_DB_URL`?** It points at the e-commerce database
> _and_ authenticates as `rag_readonly`. The document store keeps using
> `PG_CONNECTION_STRING`. Keeping them separate means the NL2SQL agent
> physically cannot touch your vector store.

---

## Step 3 — Install the SQL dependencies

LangChain's `SQLDatabase` utility talks to PostgreSQL through SQLAlchemy and
`psycopg2`:

```bash
source .venv/bin/activate
pip install -e .          # langchain-community + psycopg2-binary are in pyproject.toml
```

`psycopg` (v3) is already present for PGVector; `psycopg2-binary` is what
SQLAlchemy/`SQLDatabase` uses. They coexist without conflict.

---

## Step 4 — Add a read-only SQL connection (`db.py`)

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
        sample_rows_in_table_info=2,   # gives the LLM concrete example values
    )
```

What `SQLDatabase.from_uri()` buys you:

- **Schema introspection** — column names, types, and foreign keys, ready to drop
  into a prompt via `db.get_table_info()`.
- **Sample rows** — `sample_rows_in_table_info=2` appends two example rows per
  table so the model sees real values (e.g. that `status` is `'shipped'`, not
  `'SHIPPED'`).
- **Safe execution** — `db.run(sql)` runs the query through the read-only role.

**Why `include_tables`?** Without it, `SQLDatabase` would also expose PGVector's
internal `langchain_pg_embedding` table. Listing only the four business tables
keeps the schema context small, focused, and accurate.

---

## Step 5 — Extend the graph state (`tools.py`)

**File:** `src/api/v1/tools/tools.py`

LangGraph threads a single `state` dict through every node. Declare **every**
field any node will write — up front — in the `TypedDict`.

```python
class RAGState(TypedDict):
    query: str
    retrieved_docs: List[Document]   # document path — wide retrieval (k=20)
    reranked_docs: List[Document]    # document path — narrowed by reranker (top_n=10)
    response: dict                   # final structured answer (both paths)
    route: str                       # "product" or "document" — set by router_node
    generated_sql: str               # SQL generated by nl2sql_node
    sql_result: str                  # raw SQL execution result
```

The three new fields power the product path:

| Field           | Written by    | Purpose                                 |
| --------------- | ------------- | --------------------------------------- |
| `route`         | `router_node` | Drives the conditional edge             |
| `generated_sql` | `nl2sql_node` | Traceability / debugging                |
| `sql_result`    | `nl2sql_node` | Raw DB output before the LLM phrases it |

---

## Step 6 — Build the router node

**File:** `src/api/v1/agents/agents.py`

The router is a **zero-shot classifier**. We use the LLM's **structured output**
so the decision is a typed value, not free text we have to parse.

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

Three things make this robust:

- **`Literal["product", "document"]`** — Pydantic rejects any third value, so a
  hallucinated route raises a validation error instead of silently misrouting.
- **`with_structured_output(...)`** — forces the model to return a valid
  `_RouteDecision` object.
- **Naming the tables in the prompt** — concrete hints
  (`products, categories, orders, order_items`) are what let the model tell a
  "product" question from a "document" one.

---

## Step 7 — Build the NL2SQL node

**File:** `src/api/v1/agents/agents.py`

This single node has three jobs: **generate SQL**, **execute it**, and
**summarise the result**.

### 7.1 Generate SQL from the live schema

```python
def nl2sql_node(state: RAGState) -> RAGState:
    llm = _get_llm()
    db = get_sql_database()

    schema_info = db.get_table_info()      # live schema + sample rows

    sql_prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """You are a PostgreSQL expert. Given the database schema below,
            write a single valid SELECT query that answers the user's question.

            Rules:
            - Return ONLY the raw SQL — no explanation, no markdown fences, no backticks.
            - Use only the tables and columns present in the schema.
            - Do NOT generate INSERT, UPDATE, DELETE, DROP, or any DML/DDL statements.
            - Always add a LIMIT clause (max 50 rows) unless the question asks for aggregates.
            - For product or text searches: NEVER search for the full multi-word phrase as one
            ILIKE pattern. Instead, split the search into individual meaningful keywords
            and OR them together across both name and description columns.
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

We inject `db.get_table_info()` straight into the prompt — no extra chain library
needed, just a `ChatPromptTemplate | llm` pipe. The two rules that matter most in
practice:

- **One keyword per ILIKE clause** prevents zero-result misses (user types
  "headset", the row says "headphones").
- **SELECT-only + LIMIT** keeps generated queries safe and fast.

Then strip any stray Markdown fences the model adds:

````python
    content = raw_sql.content
    if isinstance(content, list):           # some models return a list of parts
        content = "".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    generated_sql = content.strip().strip("```").strip()
    if generated_sql.lower().startswith("sql"):
        generated_sql = generated_sql[3:].strip()
    print(f"[nl2sql_node] Generated SQL:\n{generated_sql}")
````

### 7.2 Execute through the read-only role

```python
    try:
        sql_result: str = db.run(generated_sql)
    except Exception as exc:
        sql_result = f"SQL execution error: {exc}"
```

`db.run()` connects as `rag_readonly`. If the model ever emits an `INSERT` or
`DROP`, the database rejects it and the `try/except` turns the error into a
string the LLM can explain to the user — the app never crashes.

### 7.3 Summarise into the structured `AIResponse`

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
        "result": sql_result,
    })

    response = answer.model_dump()
    response["policy_citations"] = "N/A"
    response["sql_query_executed"] = generated_sql
    return {
        **state,
        "generated_sql": generated_sql,
        "sql_result": str(sql_result),
        "response": response,
    }
```

The product path fills `sql_query_executed` with the exact query that ran — copy
it into `psql` to verify any answer independently — and sets the document-only
fields (`policy_citations`, `page_no`, `document_name`) to sensible placeholders.

---

## Step 8 — Wire the LangGraph with conditional edges

**File:** `src/api/v1/agents/agents.py`

```python
def build_rag_graph():
    graph = StateGraph(RAGState)

    graph.add_node("router", router_node)
    graph.add_node("nl2sql", nl2sql_node)
    graph.add_node("vector_search", vector_search_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("generate_answer", generate_answer_node)

    # Entry point is the router, not vector_search
    graph.set_entry_point("router")

    # Branch on state["route"]
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"],     # selector → returns "product" | "document"
        {
            "product": "nl2sql",
            "document": "vector_search",
        }
    )

    # Product path: one node, then done
    graph.add_edge("nl2sql", END)

    # Document path: the reranking RAG pipeline
    graph.add_edge("vector_search", "rerank")
    graph.add_edge("rerank", "generate_answer")
    graph.add_edge("generate_answer", END)

    return graph.compile()
```

`add_conditional_edges(source, selector_fn, mapping)` is the heart of the agent:
after `source` runs, LangGraph calls `selector_fn(state)` and uses the returned
string as a key into `mapping` to choose the next node.

```
add_conditional_edges(
    "router",                       ← node that just ran
    lambda state: state["route"],   ← selector function
    {"product": "nl2sql", "document": "vector_search"}   ← key → next node
)
```

---

## Step 9 — Expose it through the API

The service and route layers stay thin — they don't care which path the graph
took, because both return the same `AIResponse`.

**`src/api/v1/services/query_service.py`**

```python
from src.api.v1.agents.agents import run_search_agent


def query_documents(query: str):
    return run_search_agent(query)
```

**`src/api/v1/routes/query.py`**

```python
@router.post("/query")
def query_endpoint(request: QueryRequest):
    return query_documents(request.query)
```

---

## Step 10 — Run and test

```bash
uvicorn main:app --reload
```

**Product route (NL2SQL):**

```bash
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the top 5 most expensive products?"}' | python3 -m json.tool
```

```json
{
  "query": "What are the top 5 most expensive products?",
  "answer": "The 5 most expensive products are:\n1. LEGO Technic Bugatti Chiron — $369.99\n...",
  "policy_citations": "N/A",
  "page_no": "N/A",
  "document_name": "agentic_rag_db",
  "sql_query_executed": "SELECT name, price FROM products ORDER BY price DESC LIMIT 5;"
}
```

More product questions to try:

```bash
-d '{"query": "Which products have stock below 50 units?"}'
-d '{"query": "How many orders are in pending status?"}'
-d '{"query": "List all products in the Sports & Outdoors category with their prices"}'
```

**Document route (Reranking RAG)** — requires an ingested PDF:

```bash
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the working hours of the HR helpdesk?"}' | python3 -m json.tool
```

**Confirm routing in the server logs:**

```
[router_node] Route → 'product' | Reason: The query asks about product prices in the database.
[nl2sql_node] Generated SQL:
SELECT name, price FROM products ORDER BY price DESC LIMIT 5;
[nl2sql_node] Raw result (truncated): ...
[nl2sql_node] Answer generated.
```

---

## 14. Security: the read-only role is your seatbelt

Never trust an LLM to be the only thing standing between a user and your data.
This system has four independent layers of defence:

| Layer               | Mechanism                                                                          |
| ------------------- | ---------------------------------------------------------------------------------- |
| 1. Prompt design    | SQL prompt forbids `INSERT/UPDATE/DELETE/DROP` and any DDL/DML                     |
| 2. Database role    | `rag_readonly` holds **only** `SELECT` — writes fail at the engine                 |
| 3. Session setting  | `default_transaction_read_only = on` — even `BEGIN; DROP TABLE ...` is rejected    |
| 4. `include_tables` | `SQLDatabase` exposes only the four business tables; the vector store stays hidden |

Even if a prompt-injection attack slipped a `DROP TABLE products;` past layer 1:

```
ERROR:  cannot execute DROP TABLE in a read-only transaction
```

The `try/except` in `nl2sql_node` catches it and the agent reports a friendly
message instead of crashing.

---

## 15. Troubleshooting

| Symptom                                         | Fix                                                                                 |
| ----------------------------------------------- | ----------------------------------------------------------------------------------- |
| `AGENTIC_RAG_DB_URL is not set`                 | Add it to `.env`; ensure `load_dotenv()` runs before `get_sql_database()` is called |
| `role "rag_readonly" does not exist`            | Re-run `psql -U postgres -f sql/seed.sql`                                           |
| `could not connect to server`                   | PostgreSQL not running, or wrong host/port in `AGENTIC_RAG_DB_URL`                  |
| Router always picks `document` for DB questions | Make sure the table names are listed explicitly in the router prompt                |
| SQL runs but returns nothing                    | Run the query directly in `psql`; check the seed completed without errors           |
| `ModuleNotFoundError: langchain_community`      | `pip install -e .` again                                                            |
| LLM wraps SQL in ` ``` ` fences                 | Already handled by the strip logic in `nl2sql_node`; extend it for new formats      |

---

## File Reference

| File                                   | Role                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------- |
| `sql/seed.sql`                         | Creates `agentic_rag_db`, the `rag_readonly` role, schema, and seed data   |
| `.env.example`                         | Template for all required environment variables                            |
| `src/core/db.py`                       | `get_vector_store()` + `get_sql_database()`                                |
| `src/api/v1/tools/tools.py`            | `RAGState` + `vector_search_node`                                          |
| `src/api/v1/agents/agents.py`          | `router_node`, `nl2sql_node`, the reranking nodes, and `build_rag_graph()` |
| `src/api/v1/services/query_service.py` | Thin wrapper calling `run_search_agent()`                                  |
| `src/api/v1/routes/query.py`           | FastAPI route handlers                                                     |
| `src/api/v1/schema/query_schema.py`    | `AIResponse`, `QueryRequest` Pydantic models                               |
