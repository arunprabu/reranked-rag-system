# Running this project with Docker — a beginner's guide

This guide explains how we put the Reranking RAG app inside a **Docker
container** and run it. No prior Docker experience needed.

---

## 1. Why Docker? (30-second version)

Normally, to run this project you must install the right Python version, create
a virtual environment, and install ~25 packages. If any of those differ on your
machine, you get the classic *"but it works on my laptop"* problem.

**Docker** packages the app **and** everything it needs (Python, libraries, the
code) into a single **image**. Anyone can run that image and get the exact same
result. A running copy of an image is called a **container**.

```
Dockerfile  ──(docker build)──▶  Image  ──(docker run)──▶  Container (the app, running)
```

---

## 2. The two files that make this work

### `Dockerfile` — the recipe for building the image

Each step below maps to a numbered comment in the `Dockerfile`:

| Step | Line | What it does |
|------|------|--------------|
| 1 | `FROM python:3.13-slim` | Start from a small official image that already has Python 3.13. |
| 2 | `WORKDIR /app` | Use `/app` inside the container as our project folder. |
| 3 | `RUN pip install uv` | Install `uv`, a fast package installer. |
| 4 | `COPY pyproject.toml .` | Copy **only** the dependency list first. |
| 5 | `RUN uv pip install -r pyproject.toml` | Install all the project's Python packages. |
| 6 | `COPY . .` | Copy the rest of our source code into the image. |
| 7 | `EXPOSE 9005` | Note that the app listens on port **9005**. |
| 8 | `CMD ["uvicorn", ...]` | Start the FastAPI server when the container runs. |

**Why copy `pyproject.toml` before the code (steps 4–6)?**
Docker remembers ("caches") each step. Installing packages is slow; copying code
is fast. By installing packages *before* copying the code, Docker can reuse the
installed-packages layer every time you change only code — so rebuilds are quick.

### `.dockerignore` — what to leave out

Just like `.gitignore`, this lists things Docker should **not** copy into the
image: the 2 GB local `.venv`, the `.git` history, and — importantly — the
`.env` file with your secret API keys. Keeping `.env` out means secrets are
never baked into the image; we pass them in at run time instead (see below).

---

## 3. Build the image

Run this from the project root (the folder with the `Dockerfile`):

```bash
docker build -t reranking-rag-demo .
```

- `-t reranking-rag-demo` gives the image a friendly name ("tag").
- The `.` at the end means "use this folder as the build context."

The first build takes a few minutes (it downloads Python packages). Later builds
are much faster thanks to caching.

---

## 4. Run the container

```bash
docker run --rm -p 9005:9005 --env-file .env reranking-rag-demo
```

- `--rm` automatically deletes the container when you stop it (keeps things tidy).
- `-p 9005:9005` connects **port 9005 on your machine** → **port 9005 in the
  container**. This is what makes the app reachable in your browser.
- `--env-file .env` passes your API keys / database URLs into the container.
- `reranking-rag-demo` is the image we just built.

> Don't have a `.env` yet? Copy `.env.example` to `.env` and fill in your keys.
> You can also drop `--env-file .env` just to see the server start — the home and
> health pages work without any keys (see the note in section 6).

---

## 5. Check that it's running

With the container running, open these in your browser (or use `curl`):

- http://localhost:9005/ → `{"Message": "Hello World"}`
- http://localhost:9005/health → `{"status": "ok"}`
- http://localhost:9005/docs → interactive Swagger API page (try the endpoints here)

```bash
curl http://localhost:9005/health
# {"status":"ok"}
```

To stop the app, go back to the terminal and press **Ctrl + C**.

---

## 6. Good to know (for the full RAG demo)

- The `/` and `/health` pages prove the app is **running and reachable** — they
  need no database or keys. Great for a first "Docker works!" moment.
- The actual **query** endpoints (`/api/v1/query`) talk to PostgreSQL (pgvector)
  and the OpenAI/Cohere/Tavily APIs. For those to return real answers you need:
  - valid keys in your `.env`, and
  - the two Postgres databases running and reachable from the container.
- This single-container setup is intentionally **minimal** for learning. The
  project also ships a `docker-compose.yml` that starts the app **and** both
  databases together — use that when you want the whole system wired up at once.

---

## Command cheat-sheet

```bash
# Build the image
docker build -t reranking-rag-demo .

# Run it (app on http://localhost:9005)
docker run --rm -p 9005:9005 --env-file .env reranking-rag-demo

# See running containers
docker ps

# Stop it: press Ctrl + C in the run terminal
```
