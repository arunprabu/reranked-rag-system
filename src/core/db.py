import os
from dotenv import load_dotenv
from langchain_postgres import PGVector
from langchain_openai import OpenAIEmbeddings
from langchain_community.utilities import SQLDatabase

load_dotenv(override=True)
model = os.getenv("OPENAI_EMBEDDING_MODEL")
api_key = os.getenv("OPENAI_API_KEY")
pg_connection = os.getenv("PG_CONNECTION_STRING")


def get_embeddings():
    return OpenAIEmbeddings(model=model, api_key=api_key)


def get_vector_store(collection_name: str = "RerankingRAGVectorStore"):
    if not pg_connection:
        raise ValueError("PG_CONNECTION_STRING is not set. Check your .env file.")
    return PGVector(
        collection_name=collection_name,
        connection=pg_connection,
        embeddings=get_embeddings(),
        use_jsonb=True,
    )


def get_sql_database() -> SQLDatabase:
    """Return a LangChain SQLDatabase connected to the agentic_rag_db (read-only).

    Uses the rag_readonly role from sql/seed.sql — SELECT privileges only.
    Connection string is read from AGENTIC_RAG_DB_URL in the environment.
    """
    db_url = os.getenv("AGENTIC_RAG_DB_URL")
    if not db_url:
        raise ValueError("AGENTIC_RAG_DB_URL is not set. Check your .env file.")
    return SQLDatabase.from_uri(
        db_url,
        include_tables=["products", "categories", "orders", "order_items"],
        sample_rows_in_table_info=2,
    )
