# Docker Setup Guide

This document outlines the steps to run the **Reranking RAG System** using Docker and Docker Compose.

The architecture consists of:

1.  **FastAPI Application**: The core API service built with Python 3.13.
2.  **PostgreSQL (pgvector)**: Database for storing vector embeddings.
3.  **PostgreSQL (agentic_rag_db)**: Mock e-commerce database for Natural Language to SQL (NL2SQL) operations.

## Prerequisites

- Docker Desktop or Docker Engine installed.
- Docker Compose installed.
- Make sure ports `8000`, `5432`, and `5433` are available.

## Step 1: Environment Variables

Create a `.env` file in the root of your project based on `.env.example`. _Note: Never commit your actual `.env` file._

Using the structure from `.env.example`:

```env
COHERE_API_KEY=your_cohere_key
OPENAI_API_KEY=your_google_key
OPENAI_EMBEDDING_MODEL="text-embedding-3-small"
OPENAI_CHAT_MODEL=gpt-5.4

# Updated to use Docker network service names
SQLALCHEMY_DATABASE_URL=postgresql+psycopg://your_user:your_password@pgvector_db:5432/your_pgvector_db

AGENTIC_RAG_DB_URL=postgresql+psycopg://rag_readonly:rag_readonly_pass@agentic_db:5432/agentic_rag_db
```

## Step 2: Build and Run with Docker Compose

To start the entire stack, run from the root directory:

```bash
docker compose up -d --build
```

This will spin up three containers:

- `fastapi_app`: The API server running on port `8000`.
- `pgvector_db`: PostgreSQL with pgvector extension running on port `5432` (mapped to `5432` on host).
- `agentic_db`: PostgreSQL mock database mapped to `5433` on the host to avoid port conflicts.

## Step 3: Verify the Setup

1.  Check container status:
    ```bash
    docker compose ps
    ```
2.  Check the API health endpoint:
    ```bash
    curl http://localhost:8000/health
    ```
    Expected output: `{"status": "ok"}`
3.  View API documentation:
    Navigate to `http://localhost:8000/docs` in your browser.

## Database Initialization Notes

- **pgvector_db**: Standard vector store initialization.
- **agentic_db**: If you have a `seed.sql` file under `./sql/`, it will automatically execute when the container starts for the first time if mounted to `/docker-entrypoint-initdb.d/` (this is configured in the docker-compose.yml).

## Shutting Down

To stop and remove containers, networks, and volumes:

```bash
docker compose down -v
```

_(Omit `-v` if you want to persist the database volumes for next time)_
