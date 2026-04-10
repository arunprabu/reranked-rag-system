```
src/
├── api/
│ └── v1/
│ ├── agents/
│ │ └── agents.py # LangGraph pipeline: RAGState + 3 nodes + graph
│ ├── routes/
│ │ └── query.py # FastAPI endpoints: POST /query, POST /admin/upload
│ ├── schema/
│ │ └── query_schema.py # Pydantic models: QueryRequest, AIResponse
│ ├── services/
│ │ └── query_service.py # Thin service layer — calls run_vector_search_agent()
│ └── tools/
│ └── tools.py # vector_search() — PGVector retrieval tool
├── core/
│ └── db.py # get_vector_store(), get_embeddings()
└── ingestion/
└── ingestion.py # PDF ingestion: load → chunk → embed → store
data/
├── HR_Knowledge_Base_2025.pdf
└── HR_Knowledge_Base_2026.pdf
uploaded_pdfs/ # Runtime upload directory
references/
├── architecture.md
├── reranking-rag-implementation-guide.md
└── questions-to-test.md
main.py # FastAPI app entry point
pyproject.toml
.env.example
main.py
pyproject.toml
README.md
.env
```

---

## Before Reranking — Raw Vector Search Output (`retrieved_docs`, k=10)

Chunks are ordered by **cosine similarity score** from the embedding model.
The model ranked `chunk_id: 45676` (FY24-25 report) first, even though the query asks specifically about **FY24** data — because both chunks share very similar token patterns.
No relevance score is visible; order is the only signal.

```json
{
  "query": "what is gross revenue in FY24",
  "retrieved_results": [
    {
      "rank": 1,
      "chunk_id": 45676,
      "cosine_similarity": 0.91,
      "content": "% chg. Y-o-Y FY24 | Customer Base: 478.8M | ARPU: ₹195.1 | Data Traffic: 45.0B GB ...\n• ARPU increased to ₹195.1 with partial follow-through of the tariff hike ...",
      "metadata": {
        "page": 5,
        "title": "RIL-Media-Release-RIL-Q2-FY2024-25-Financial-and-Operational-Performance",
        "source": "file1.pdf"
      }
    },
    {
      "rank": 2,
      "chunk_id": 3454,
      "cosine_similarity": 0.89,
      "content": "% chg. Y-o-Y FY24 | Customer Base: 478.8M | ARPU: ₹195.1 | Data Traffic: 45.0B GB ...\n• Engagement levels continued to remain strong with total data and voice traffic increasing by 24% ...",
      "metadata": {
        "page": 40,
        "title": "RIL-Media-Release-RIL-Q2-FY2025-26-Financial-and-Operational-Performance",
        "source": "file2.pdf"
      }
    },
    {
      "rank": 3,
      "chunk_id": 9821,
      "cosine_similarity": 0.85,
      "content": "Gross Revenue for FY24 stood at ₹9,74,864 crore, registering a growth of 10.8% over FY23. EBITDA for FY24 was ₹1,85,674 crore ...",
      "metadata": {
        "page": 12,
        "title": "RIL-Annual-Report-FY2023-24",
        "source": "file3.pdf"
      }
    }
    // ... 7 more chunks
  ]
}
```

> **Problem:** `chunk_id: 45676` (rank 1) is from the FY24-25 quarterly report — it mentions FY24 figures as a comparison row, not as the primary subject. The actual FY24 annual gross revenue answer is buried at rank 3 (`chunk_id: 9821`).

---

## After Reranking — Cohere Cross-Encoder Output (`reranked_docs`, top_n=3)

The cross-encoder reads the **query and each chunk together**, understanding that the user wants the FY24 _annual gross revenue_ figure — not a Y-o-Y comparison table. It re-scores and re-orders accordingly.

```json
{
  "query": "what is gross revenue in FY24",
  "reranked_results": [
    {
      "rank": 1,
      "original_rank": 3,
      "chunk_id": 9821,
      "relevance_score": 0.9743,
      "content": "Gross Revenue for FY24 stood at ₹9,74,864 crore, registering a growth of 10.8% over FY23. EBITDA for FY24 was ₹1,85,674 crore ...",
      "metadata": {
        "page": 12,
        "title": "RIL-Annual-Report-FY2023-24",
        "source": "file3.pdf"
      }
    },
    {
      "rank": 2,
      "original_rank": 1,
      "chunk_id": 45676,
      "relevance_score": 0.6812,
      "content": "% chg. Y-o-Y FY24 | Customer Base: 478.8M | ARPU: ₹195.1 ...",
      "metadata": {
        "page": 5,
        "title": "RIL-Media-Release-RIL-Q2-FY2024-25-Financial-and-Operational-Performance",
        "source": "file1.pdf"
      }
    },
    {
      "rank": 3,
      "original_rank": 2,
      "chunk_id": 3454,
      "relevance_score": 0.5201,
      "content": "% chg. Y-o-Y FY24 | Customer Base: 478.8M | ARPU: ₹195.1 ...",
      "metadata": {
        "page": 40,
        "title": "RIL-Media-Release-RIL-Q2-FY2025-26-Financial-and-Operational-Performance",
        "source": "file2.pdf"
      }
    }
  ]
}
```

> **Result:** `chunk_id: 9821` (the FY24 Annual Report with the actual gross revenue figure) is promoted to rank 1. The LLM now uses this as the primary context and produces a precise, grounded answer.

---

## Key Difference at a Glance

|                | Vector Search (bi-encoder)                             | After Reranking (cross-encoder)                    |
| -------------- | ------------------------------------------------------ | -------------------------------------------------- |
| Scoring signal | Cosine similarity of embeddings                        | Joint query+doc relevance score                    |
| Rank 1 chunk   | FY24-25 quarterly report (mentions FY24 as comparison) | FY24 Annual Report (directly answers the question) |
| Score visible? | No (implicit order only)                               | Yes (`relevance_score` 0–1)                        |
| Speed          | Fast (pre-computed vectors)                            | Slower (inference per pair)                        |
| Best for       | Candidate retrieval (k=10)                             | Final selection (top_n=3)                          |
