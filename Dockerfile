# ─────────────────────────────────────────────────────────────────────────────
# A minimal Dockerfile for the Reranking RAG demo.
#
# Goal: package this FastAPI app into one image so it runs the same way on any
# machine — "it works on my laptop" becomes "it works everywhere".
#
# Read top to bottom; each numbered step is explained in
#   references/docker-demo-guide.md
# ─────────────────────────────────────────────────────────────────────────────

# 1. Start from a small, official Python image (matches .python-version → 3.13).
FROM python:3.13-slim

# 2. Everything below runs inside this folder in the container.
WORKDIR /app

# 3. Install "uv" — a fast tool that downloads and installs Python packages.
RUN pip install --no-cache-dir uv

# 4. Copy ONLY the dependency list first. Docker caches this layer, so when you
#    change app code (but not dependencies) the slow install step is skipped.
COPY pyproject.toml .

# 5. Install every dependency listed in pyproject.toml into the system Python.
RUN uv pip install --system -r pyproject.toml

# 6. Now copy the rest of the application code into the image.
COPY . .

# 7. Document that the app listens on this port inside the container.
EXPOSE 9005

# 8. The command that starts the server when the container runs.
#    --host 0.0.0.0 makes it reachable from outside the container.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9005"]
