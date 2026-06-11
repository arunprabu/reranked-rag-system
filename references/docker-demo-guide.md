# Running this project with Docker — a beginner's guide

This guide explains how we put the Reranking RAG app inside a **Docker
container** and run it. No prior Docker experience needed.

---

## 1. Why Docker? (30-second version)

Normally, to run this project you must install the right Python version, create
a virtual environment, and install ~25 packages. If any of those differ on your
machine, you get the classic _"but it works on my laptop"_ problem.

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

| Step | Line                                   | What it does                                                    |
| ---- | -------------------------------------- | --------------------------------------------------------------- |
| 1    | `FROM python:3.13-slim`                | Start from a small official image that already has Python 3.13. |
| 2    | `WORKDIR /app`                         | Use `/app` inside the container as our project folder.          |
| 3    | `RUN pip install uv`                   | Install `uv`, a fast package installer.                         |
| 4    | `COPY pyproject.toml .`                | Copy **only** the dependency list first.                        |
| 5    | `RUN uv pip install -r pyproject.toml` | Install all the project's Python packages.                      |
| 6    | `COPY . .`                             | Copy the rest of our source code into the image.                |
| 7    | `EXPOSE 9005`                          | Note that the app listens on port **9005**.                     |
| 8    | `CMD ["uvicorn", ...]`                 | Start the FastAPI server when the container runs.               |

**Why copy `pyproject.toml` before the code (steps 4–6)?**
Docker remembers ("caches") each step. Installing packages is slow; copying code
is fast. By installing packages _before_ copying the code, Docker can reuse the
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

### Troubleshooting: logs say "startup complete" but the page won't load

If the terminal shows `Uvicorn running on http://0.0.0.0:9005` and
`Application startup complete`, but http://localhost:9005 still won't open, the
container is almost always running **without a published port**. This happens
when you start it with a bare `docker run reranking-rag-demo` and forget the
`-p 9005:9005` flag.

`0.0.0.0:9005` inside the container only means "the app listens on every network
_inside_ the container." Your laptop still can't reach it until you map a host
port with `-p`.

**How to tell.** Run `docker ps` and look at the `PORTS` column:

```
9005/tcp                       ← exposed only — NOT reachable from your laptop
0.0.0.0:9005->9005/tcp         ← published — this is what you want
```

**The fix.** You can't add a port mapping to a container that already exists —
you must recreate it. Stop/remove the old one and run again _with_ `-p`:

```bash
docker rm -f <container-name>          # name is shown by `docker ps`
docker run --rm -p 9005:9005 --env-file .env reranking-rag-demo
```

> Tip: add `--name reranking-rag-demo` to your `docker run` so the container has
> a predictable name instead of a random one like `competent_panini`.

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
  databases together — use that when you want the whole system wired up at once
  (see section 7).

---

## 7. Run the whole stack with Docker Compose

The single container above runs only the **app**. The real demo also needs two
PostgreSQL databases. `docker-compose.yml` starts all three together — the app
plus both databases — with one command, on one private network.

### What you get

| Service       | What it is                                                                 | Reachable at          |
| ------------- | -------------------------------------------------------------------------- | --------------------- |
| `fastapi_app` | The RAG API                                                                | http://localhost:8000 |
| `pgvector_db` | Postgres + pgvector — stores document embeddings                           | host port **5440**    |
| `agentic_db`  | Postgres for the e-commerce NL2SQL route (auto-seeded from `sql/seed.sql`) | host port **5441**    |

> **About the ports.** Inside Compose the app reaches the databases by _name_
> (`pgvector_db`, `agentic_db`) over a private network — it does **not** use the
> host ports above. Those are published only so _you_ can connect a tool like
> DBeaver from your laptop, and they're set to **5440 / 5441** on purpose to
> avoid clashing with any Postgres you may already run on **5432** or **5433**.
>
> **Note the app port:** Compose serves the app on **8000** (not 9005 like the
> standalone container in section 4).

### Step 1 — create your `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in your API keys. Leave the `PG_CONNECTION_STRING` and
`AGENTIC_RAG_DB_URL` lines as they are — they already point at the Compose
service names.

### Step 2 — start everything

```bash
docker compose up --build
```

The first run builds the app image and downloads the two Postgres images, so give
it a few minutes. When you see uvicorn's _"Application startup complete"_, open:

- http://localhost:8000/health → `{"status":"ok"}`
- http://localhost:8000/docs → try the `/api/v1/query` endpoint

Prefer the background? Add `-d` and follow the logs:

```bash
docker compose up --build -d
docker compose logs -f
```

### Step 3 — stop it

```bash
docker compose down       # stop and remove the containers
docker compose down -v    # ...and also wipe the databases (fresh start)
```

Use `down -v` whenever you want the e-commerce database re-seeded from
`sql/seed.sql` on the next `up` — the seed only runs when the database is empty.

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

# ── Or run the whole stack (app + both databases) ──
docker compose up --build        # app on http://localhost:8000
docker compose logs -f           # follow the logs
docker compose down              # stop everything
docker compose down -v           # stop AND wipe the databases
```
