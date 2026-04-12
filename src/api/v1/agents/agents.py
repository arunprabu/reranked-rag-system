import os

import cohere
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END

from src.api.v1.schema.query_schema import AIResponse
from src.api.v1.tools.tools import RAGState, vector_search_node

load_dotenv(override=True)


# ── 1. Node 2: Rerank ──────────────────────────────────────────────────────────
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


# ── 4. Node 3: Generate Answer ─────────────────────────────────────────────────
# Formats the top 3 reranked chunks as context and calls Gemini LLM.
# Uses structured output to enforce the AIResponse schema.

def generate_answer_node(state: RAGState) -> RAGState:
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GOOGLE_LLM_MODEL"),
        google_api_key=os.getenv("GOOGLE_API_KEY")
    )
    structured_llm = llm.with_structured_output(AIResponse)

    context = "\n\n".join([
        f"[Source: {doc.metadata.get('source', 'unknown')} | Page: {doc.metadata.get('page', -1) + 1 if doc.metadata.get('page') is not None else '?'}]\n{doc.page_content}"
        for doc in state["reranked_docs"]
    ])

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a helpful assistant. Answer the user's question using only the "
            "provided context. Be precise and always cite the source document and page number."
        ),
        ("human", "Context:\n{context}\n\nQuestion: {query}")
    ])

    chain = prompt | structured_llm
    result = chain.invoke({"context": context, "query": state["query"]})

    print(f"[generate_answer_node] Answer generated.")
    return {**state, "response": result.model_dump()}


# ── 5. Build the LangGraph ─────────────────────────────────────────────────────
# Three nodes wired in a simple linear sequence.
#   vector_search → rerank → generate_answer → END

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


# Compile once at module load — reused across all requests
rag_graph = build_rag_graph()


# ── 6. Public entrypoint (called by query_service.py) ─────────────────────────
def run_vector_search_agent(query: str) -> dict:
    initial_state: RAGState = {
        "query": query,
        "retrieved_docs": [],
        "reranked_docs": [],
        "response": {}
    }
    final_state = rag_graph.invoke(initial_state)
    return final_state["response"]
