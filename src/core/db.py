import os
from dotenv import load_dotenv
from langchain_postgres import PGVector
from langchain_openai import OpenAIEmbeddings


load_dotenv(override=True)
model = os.getenv("OPENAI_EMBEDDING_MODEL")
api_key = os.getenv("OPENAI_API_KEY")
pg_connection = os.getenv("SQLALCHEMY_DATABASE_URL")


def get_embeddings():
    return OpenAIEmbeddings(
        model=model,
        api_key=api_key
    )


def get_vector_store(collection_name: str = "RerankingRAGVectorStore"):
    return PGVector(
        collection_name=collection_name,
        connection=pg_connection,
        embeddings=get_embeddings(),
        use_jsonb=True
    )