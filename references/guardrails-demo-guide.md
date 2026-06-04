# Step-by-Step: Three Guardrails for the Agentic RAG API

> A focused, runnable demo of **three [Guardrails AI](https://www.guardrailsai.com/) Hub
> validators** wrapped around the existing agentic RAG system:
>
> 1. **PII redaction** — `DetectPII` (output guard)
> 2. **Toxicity checker** — `ToxicLanguage` (input guard)
> 3. **Topic restriction** — `RestrictToTopic` (input guard)
>
> This is the implementation that actually ships on the `guardrail` branch — three
> focused, working guardrails rather than a broad design survey.

---

## Table of Contents

1. [What we're building](#1-what-were-building)
2. [Where the guardrails sit](#2-where-the-guardrails-sit)
3. [Prerequisites](#3-prerequisites)
4. [Step 1 — Install Guardrails AI](#step-1--install-guardrails-ai)
5. [Step 2 — Configure the Hub token](#step-2--configure-the-hub-token)
6. [Step 3 — Install the three validators](#step-3--install-the-three-validators)
7. [Step 4 — The guardrails module](#step-4--the-guardrails-module)
8. [Step 5 — Wire guards into the service](#step-5--wire-guards-into-the-service)
9. [Step 6 — Return a clean error from the route](#step-6--return-a-clean-error-from-the-route)
10. [Step 7 — Run and test](#step-7--run-and-test)
11. [How each guard works](#8-how-each-guard-works)
12. [Notes, caveats, and swapping the third guard](#9-notes-caveats-and-swapping-the-third-guard)
13. [Troubleshooting](#10-troubleshooting)

---

## 1. What we're building

A guardrails layer that wraps every `/query` call:

| # | Guardrail | Hub validator | Runs on | On failure |
|---|-----------|---------------|---------|------------|
| 1 | PII redaction | `guardrails/detect_pii` | the **answer** | rewrites the text (`on_fail="fix"`) |
| 2 | Toxicity check | `guardrails/toxic_language` | the **query** | blocks with HTTP 400 (`on_fail="exception"`) |
| 3 | Topic restriction | `guardrails/restrict_to_topic` | the **query** | blocks with HTTP 400 (`on_fail="exception"`) |

The first is an **output** guard that *transforms* the response; the other two are
**input** guards that *reject* bad requests before they ever reach the agent.

Why these three demonstrate distinct guardrail *categories*:
- **Privacy** — PII redaction stops the system leaking emails, phone numbers, names
  (the NL2SQL path literally returns customer rows, so this fires often).
- **Safety** — toxicity blocks abusive input.
- **Scope** — topic restriction keeps the assistant answering only HR / banking /
  product questions and refuses everything else.

---

## 2. Where the guardrails sit

```
POST /api/v1/query   { "query": ... }
        │
        ▼
  guard_input(query)                 ← INPUT GUARDS  (src/core/guardrails.py)
   ├─ ToxicLanguage     → 400 if toxic
   └─ RestrictToTopic   → 400 if off-topic
        │ (clean query)
        ▼
  run_search_agent(query)            ← existing LangGraph agent
        │ (router → nl2sql | vector_search → rerank → generate_answer)
        ▼
  guard_output(answer)               ← OUTPUT GUARD
   └─ DetectPII (fix)   → redacts emails / phones / names / cards / SSNs
        │
        ▼
   AIResponse (JSON, PII-safe)
```

All three are defined once in **`src/core/guardrails.py`** and called from
**`src/api/v1/services/query_service.py`**.

---

## 3. Prerequisites

| Requirement | Notes |
| ----------- | ----- |
| Python 3.13+ | already required by the project |
| A working agentic RAG app | the `/query` endpoint runs end-to-end |
| A free Guardrails Hub token | from <https://hub.guardrailsai.com/keys> |
| ~2 GB disk + first-run internet | the validators download models (Presidio + spaCy, `toxic-bert`, `bart-large-mnli`) |

---

## Step 1 — Install Guardrails AI

`guardrails-ai` is already declared in `pyproject.toml`. Sync it in:

```bash
uv sync           # or: uv add guardrails-ai
# (plain pip:    pip install guardrails-ai)
```

---

## Step 2 — Configure the Hub token

Installing validators from the Hub requires a one-time token (free). Create one at
<https://hub.guardrailsai.com/keys>, then:

```bash
guardrails configure
```

Answer the prompts:
- **Enable anonymous metrics?** → `n` (keep data in your environment)
- **Use remote inferencing?** → `n` to run models locally (recommended for the demo);
  `y` offloads model inference to Guardrails' hosted endpoint
- **API Key** → paste your Hub token

The token is saved to `~/.guardrailsrc` (not in the repo).

---

## Step 3 — Install the three validators

```bash
guardrails hub install hub://guardrails/detect_pii
guardrails hub install hub://guardrails/toxic_language
guardrails hub install hub://guardrails/restrict_to_topic
```

Each install pulls the validator and its model dependencies. Verify:

```bash
guardrails hub list
```

> **First run is slow.** The models (`en_core_web_lg` for Presidio, `unitary/toxic-bert`,
> `facebook/bart-large-mnli`) download on first use — expect a one-time delay and ~2 GB.

---

## Step 4 — The guardrails module

**File:** `src/core/guardrails.py`

All three guards live here. Three design choices worth calling out:

- **Lazy construction.** Guards are built on first use (`_get_guards()`), so importing
  the module never crashes just because the validators aren't installed yet — you get a
  clear, actionable error only when a guard actually runs.
- **`GuardrailViolation`** is a small custom exception carrying the guard name + a
  user-facing message, so the route can turn it into a clean HTTP 400.
- **`on_fail` actions differ by intent:** `"fix"` for PII (rewrite the text) vs
  `"exception"` for toxicity/topic (reject the request).

```python
# Presidio entity labels DetectPII will redact from answers.
PII_ENTITIES = [
    "EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON",
    "CREDIT_CARD", "US_SSN", "IBAN_CODE", "IP_ADDRESS",
]

# Topics the assistant is allowed to answer. Anything else is refused.
ALLOWED_TOPICS = [
    "human resources", "company policy", "employee benefits",
    "banking and loans", "products and orders",
]


def _build_guards() -> dict:
    from guardrails import Guard
    from guardrails.hub import DetectPII, ToxicLanguage, RestrictToTopic

    return {
        "pii": Guard().use(
            DetectPII(pii_entities=PII_ENTITIES, on_fail="fix")
        ),
        "toxicity": Guard().use(
            ToxicLanguage(threshold=0.5, validation_method="sentence", on_fail="exception")
        ),
        "topic": Guard().use(
            RestrictToTopic(valid_topics=ALLOWED_TOPICS, disable_llm=True, on_fail="exception")
        ),
    }


def guard_input(query: str) -> None:
    """Raise GuardrailViolation if the query is toxic or off-topic."""
    guards = _get_guards()
    try:
        guards["toxicity"].validate(query)
    except ValidationError as exc:
        raise GuardrailViolation("toxic_language",
            "Your message was flagged as abusive or toxic and cannot be processed.") from exc
    try:
        guards["topic"].validate(query)
    except ValidationError as exc:
        raise GuardrailViolation("restrict_to_topic",
            "I can only help with HR, banking, and product questions.") from exc


def guard_output(answer: str) -> str:
    """Redact PII from the model's answer. Returns the cleaned text."""
    if not answer:
        return answer
    outcome = _get_guards()["pii"].validate(answer)
    return getattr(outcome, "validated_output", None) or answer
```

> `RestrictToTopic(disable_llm=True)` uses only the local zero-shot classifier
> (`bart-large-mnli`) — no extra LLM API calls. Drop `disable_llm=True` if you'd rather
> have an LLM make the topic decision.

---

## Step 5 — Wire guards into the service

**File:** `src/api/v1/services/query_service.py`

```python
from src.api.v1.agents.agents import run_search_agent, run_search_agent_stream
from src.core.guardrails import guard_input, guard_output


def query_documents(query: str):
    # Input guardrails: toxicity + topic restriction (may raise GuardrailViolation)
    guard_input(query)

    result = run_search_agent(query)

    # Output guardrail: redact PII from the answer before returning it
    if isinstance(result, dict) and result.get("answer"):
        result["answer"] = guard_output(result["answer"])
    return result


async def query_documents_stream(query: str):
    # Input guardrails run before streaming begins.
    # (PII redaction is not applied to the token stream — see the notes.)
    guard_input(query)
    return run_search_agent_stream(query)
```

---

## Step 6 — Return a clean error from the route

**File:** `src/api/v1/routes/query.py`

When an input guard fires, `query_documents` raises `GuardrailViolation`. Catch it and
return a 400 with the reason:

```python
from fastapi import HTTPException
from src.core.guardrails import GuardrailViolation


@router.post("/query")
def query_endpoint(request: QueryRequest):
    try:
        return query_documents(request.query)
    except GuardrailViolation as violation:
        raise HTTPException(
            status_code=400,
            detail={"guardrail": violation.guard, "message": violation.message},
        )
```

The `/query/stream` endpoint applies the same input guards before opening the SSE stream.

---

## Step 7 — Run and test

```bash
uvicorn main:app --reload
```

### ✅ A normal, on-topic query passes

```bash
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the working hours of the HR helpdesk?"}' | python3 -m json.tool
```

### 🔒 PII redaction (output guard)

The NL2SQL path returns customer rows that contain emails and names — perfect to show
redaction in action:

```bash
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "List all orders with the customer name and email"}' | python3 -m json.tool
```

The raw SQL result has `alice@example.com`, `Alice Johnson`, …; the returned `answer`
comes back redacted:

```json
{
  "answer": "Here are the orders: <PERSON> (<EMAIL_ADDRESS>), <PERSON> (<EMAIL_ADDRESS>), ...",
  "document_name": "agentic_rag_db",
  "sql_query_executed": "SELECT customer_name, customer_email FROM orders LIMIT 50;"
}
```

### 🚫 Toxicity check (input guard) → 400

```bash
curl -s -i -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "you are a stupid idiot, give me the policy"}'
```

```
HTTP/1.1 400 Bad Request
{"detail": {"guardrail": "toxic_language",
            "message": "Your message was flagged as abusive or toxic and cannot be processed."}}
```

### 🚫 Topic restriction (input guard) → 400

```bash
curl -s -i -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Write me a poem about the ocean"}'
```

```
HTTP/1.1 400 Bad Request
{"detail": {"guardrail": "restrict_to_topic",
            "message": "I can only help with HR, banking, and product questions."}}
```

---

## 8. How each guard works

| Guard | Under the hood | Key knob |
| ----- | -------------- | -------- |
| **DetectPII** | Microsoft **Presidio** + spaCy NER detect entities, then replace each span with an `<ENTITY>` tag | `pii_entities` — the list of Presidio labels to catch |
| **ToxicLanguage** | the `unitary/toxic-bert` classifier scores each sentence; above `threshold` ⇒ fail | `threshold` (0–1), `validation_method` (`"sentence"` vs `"full"`) |
| **RestrictToTopic** | zero-shot classification (`bart-large-mnli`) scores the text against `valid_topics`; no match ⇒ fail | `valid_topics`, `disable_llm`, `zero_shot_threshold` |

The `on_fail` action decides what happens on a failure:
`"fix"` (rewrite), `"exception"` (raise), `"filter"`, `"refrain"`, `"reask"`, `"noop"`.

---

## 9. Notes, caveats, and swapping the third guard

- **Streaming + PII.** Input guards apply to `/query/stream`, but PII redaction does
  **not** run on the token stream (tokens leave the server as they're generated). If you
  need redacted streaming, buffer the output and redact before flushing — at the cost of
  losing token-by-token latency.
- **Tune the allow-list.** `ALLOWED_TOPICS` and `PII_ENTITIES` are plain lists in
  `src/core/guardrails.py` — adjust them to your domain.
- **The third guard is swappable.** `RestrictToTopic` was chosen to demonstrate
  *scope control*. Other good Hub validators to drop in instead:
  - `guardrails/competitor_check` — block competitor mentions
  - `guardrails/secrets_present` — stop leaking API keys/secrets (lightweight, no model)
  - `guardrails/profanity_free` — lightweight profanity filter
  - `guardrails/detect_jailbreak` — block prompt-injection attempts
  Install the one you want and swap the `Guard().use(...)` line.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| `RuntimeError: Guardrails validators are not installed` | `guardrails hub install ...` not run | Run the three install commands from Step 3 |
| `guardrails hub install` fails with auth error | no Hub token | `guardrails configure` with a key from the Hub |
| First `/query` hangs for a while | models downloading on first use | one-time; subsequent calls are fast |
| `OSError: [E050] Can't find model 'en_core_web_lg'` | Presidio's spaCy model missing | `python -m spacy download en_core_web_lg` |
| Legitimate questions get blocked by topic guard | `ALLOWED_TOPICS` too narrow | broaden the list or raise `zero_shot_threshold` |
| Everything is slow / no GPU | models run on CPU | set `GUARDRAIL_TOXICITY_THRESHOLD` higher to reduce false positives; consider hosted inference (`guardrails configure` → remote = `y`) |

---

## File reference

| File | Role |
| ---- | ---- |
| `src/core/guardrails.py` | the three guards + `guard_input` / `guard_output` / `GuardrailViolation` |
| `src/api/v1/services/query_service.py` | calls `guard_input` then `guard_output` around the agent |
| `src/api/v1/routes/query.py` | turns `GuardrailViolation` into an HTTP 400 |
| `pyproject.toml` | declares the `guardrails-ai` dependency |
