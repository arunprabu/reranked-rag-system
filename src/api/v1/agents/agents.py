import os
from typing import Literal
import cohere
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from src.api.v1.schema.query_schema import AIResponse
from src.api.v1.tools.tools import RAGState, vector_search_node
from src.core.db import get_sql_database

load_dotenv()


# ── Helper: build the OpenAI LLM ──────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_CHAT_MODEL"),
        api_key=os.getenv("OPENAI_API_KEY")
    )


# ── Node 0: Router ────────────────────────────────────────────────────────────
# Uses the OpenAI LLM (structured output) to classify the user's query.
#
# "product" → query is about products, prices, stock, orders, categories
#             → routes to nl2sql_node (PostgreSQL / agentic_rag_db)
# "document" → query is about policies, procedures, text documents
#             → routes to the RAG pipeline (vector_search → rerank → generate_answer)

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
    return {
        **state, 
        "route": decision.route
    }


# ── Node NL2SQL: Translate query to SQL → Execute → Summarise ─────────────────
# Step 1  Build a prompt with the live DB schema (table/column names + 2 sample
#          rows per table) and ask the LLM to write a single SELECT statement.
# Step 2  SQLDatabase.run() executes the SQL as the read-only rag_readonly user.
#          Even if the LLM hallucinated a DML statement, the DB role blocks it.
# Step 3  The LLM summarises the raw results as a structured AIResponse.

def nl2sql_node(state: RAGState) -> RAGState:
    llm = _get_llm()
    db = get_sql_database()

    # ── Step 1: Generate SQL using the LLM + live schema ────────────────────
    schema_info = db.get_table_info()

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
    raw_sql = sql_chain.invoke({
        "schema": schema_info,
        "question": state["query"]
    })
    # The LLM may return content as a list of parts or a plain string
    content = raw_sql.content
    if isinstance(content, list):
        content = "".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    generated_sql = content.strip().strip("```").strip()
    if generated_sql.lower().startswith("sql"):
        generated_sql = generated_sql[3:].strip()
    print(f"[nl2sql_node] Generated SQL:\n{generated_sql}")

    # ── Step 2: Execute SQL ──────────────────────────────────────────────────
    try:
        sql_result: str = db.run(generated_sql)
    except Exception as exc:
        sql_result = f"SQL execution error: {exc}"
    print(f"[nl2sql_node] Raw result (truncated): {str(sql_result)[:200]}")

    # ── Step 3: Summarise into AIResponse ────────────────────────────────────
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
            "Question: {query}\n\n"
            "SQL Used:\n{sql}\n\n"
            "Query Results:\n{result}"
        )
    ])

    chain = answer_prompt | structured_llm
    answer = chain.invoke({
        "query": state["query"],
        "sql": generated_sql,
        "result": sql_result
    })
    print("[nl2sql_node] Answer generated.")
    response = answer.model_dump()
    response["policy_citations"] = "N/A"
    response["sql_query_executed"] = generated_sql
    return {
        **state,
        "generated_sql": generated_sql,
        "sql_result": str(sql_result),
        "response": response
    }


# ── Node 2: Rerank ──────────────────────────────────────────────────────────────
# Uses Cohere's cross-encoder reranker.
# Unlike bi-encoders (which embed query and doc separately),
# a cross-encoder sees query + doc TOGETHER → more accurate relevance scoring.

def rerank_node(state: RAGState) -> RAGState:
    co = cohere.ClientV2(api_key=os.getenv("COHERE_API_KEY"))
    docs = state["retrieved_docs"]

    rerank_response = co.rerank(
        model="rerank-english-v3.0",
        query=state["query"],
        documents=[doc.page_content for doc in docs],
        top_n=10
    )

    # Map Cohere result indices back to LangChain Document objects
    reranked_docs = [docs[r.index] for r in rerank_response.results]

    print(f"[rerank_node] Top {len(reranked_docs)} chunks after reranking:")
    for i, r in enumerate(rerank_response.results):
        print(f"  Rank {i+1} | Cohere score: {r.relevance_score:.4f} | original index: {r.index}")

    return {**state, "reranked_docs": reranked_docs}


# ── Node 3: Generate Answer ─────────────────────────────────────────────────
# Formats the top 10 reranked chunks as context and calls the OpenAI LLM.
# Uses structured output to enforce the AIResponse schema.

def generate_answer_node(state: RAGState) -> RAGState:
    llm = _get_llm()
    structured_llm = llm.with_structured_output(AIResponse)

    context = "\n\n".join([
        f"[Source: {doc.metadata.get('source', 'unknown')} | Page: {doc.metadata.get('page', -1) + 1 if doc.metadata.get('page') is not None else '?'}]\n{doc.page_content}"
        for doc in state["reranked_docs"]
    ])

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a helpful assistant. Answer the user's question using only the "
            "provided context.\n\n"
            "IMPORTANT: The context may contain chunks from MULTIPLE versions of the same "
            "document (e.g. a 2025 edition and a 2026 edition). When the answer differs "
            "across versions, do NOT pick only one. Instead:\n"
            "  - Lead with the most recent / current version's answer (highest year).\n"
            "  - Then explicitly note how earlier versions differed "
            "(e.g. 'As of the 2026 policy ...; previously, under the 2025 policy ...').\n"
            "  - If all versions agree, just give the single answer.\n\n"
            "Citation rules (fill the structured fields):\n"
            "  - document_name: comma-separated list of EVERY source document you used.\n"
            "  - page_no: comma-separated page numbers, aligned with the documents above.\n"
            "  - policy_citations: a readable citation combining each document and its page "
            "(e.g. 'HR_Knowledge_Base_2026.pdf, Page 1; HR_Knowledge_Base_2025.pdf, Page 1').\n"
            "Always cite ALL versions you drew the answer from, not just one."
        ),
        ("human", "Context:\n{context}\n\nQuestion: {query}")
    ])

    chain = prompt | structured_llm
    result = chain.invoke({"context": context, "query": state["query"]})

    print(f"[generate_answer_node] Answer generated.")
    return {**state, "response": result.model_dump()}


# ── Build the LangGraph ────────────────────────────────────────────────────────
# The graph now has two paths selected by the router:
#
#   router ──► "product"  ──► nl2sql_node ──► END
#          └─► "document" ──► vector_search ──► rerank ──► generate_answer ──► END

def build_rag_graph():
    graph = StateGraph(RAGState)

    graph.add_node("router", router_node)
    graph.add_node("nl2sql", nl2sql_node)
    graph.add_node("vector_search", vector_search_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("generate_answer", generate_answer_node)

    graph.set_entry_point("router")

    # Conditional routing: "product" → nl2sql, "document" → vector_search
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {
            "product": "nl2sql",
            "document": "vector_search",
        }
    )

    graph.add_edge("nl2sql", END)

    graph.add_edge("vector_search", "rerank")
    graph.add_edge("rerank", "generate_answer")
    graph.add_edge("generate_answer", END)

    compiled_agent = graph.compile()
    graph_image = compiled_agent.get_graph().draw_mermaid_png()
    with open("references/reranking_workflow.png", "wb") as f:
        f.write(graph_image)

    return compiled_agent



# Compile once at module load — reused across all requests
rag_graph = build_rag_graph()



# ── Public entrypoint (called by query_service.py) ─────────────────────────
def run_search_agent(query: str) -> dict:
    initial_state: RAGState = {
        "query": query,
        "retrieved_docs": [],
        "reranked_docs": [],
        "response": {},
        "route": "",
        "generated_sql": "",
        "sql_result": "",
    }
    final_state = rag_graph.invoke(initial_state)
    return final_state["response"]
