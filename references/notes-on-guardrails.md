# Notes on Guardrails — Concepts, Caveats & Deep Dives

> Companion notes to `guardrails-setup.md`.  
> These notes cover the **why** behind design decisions, important edge-case warnings,
> theoretical foundations, and governance concepts that trainees should understand
> before building production guardrail systems.

---

## 1. RAIL Specifications (Reliable AI Markup Language)

### What RAIL Is
RAIL is Guardrails AI's XML-based declarative language for specifying:
- The **schema** of expected LLM output (typed fields, required/optional)
- **Validation rules** per field (`format=` attribute)
- **Corrective actions** (`on-fail-*` attributes: `noop`, `fix`, `exception`, `reask`)

### RAIL vs Pydantic Guards
Guardrails AI now supports both approaches:

| Approach | When to Use |
|---|---|
| **RAIL XML** | Complex multi-field structured outputs with mixed validator types; when non-Python stakeholders need to read/edit the spec |
| **Pydantic Guard** | Simpler schemas; Python-first teams; tighter IDE support |
| **Guard.use() chaining** | Free-text validation without a schema (input/output moderation) |

In `guardrails-setup.md`, we use RAIL for financial responses (multi-field structured) and `Guard.use()` for input moderation (free-text). This is intentional.

### `on-fail` Action Reference

| Action | Behaviour |
|---|---|
| `noop` | Log the failure; return the original value anyway |
| `exception` | Raise `ValidationError`; caller must handle it |
| `fix` | Apply the `fix_value` returned by the validator |
| `reask` | Re-prompt the LLM with the error message appended (costs another LLM call) |
| `filter` | Remove the failing field from the output object |

> **Banking recommendation**: Use `exception` on input rails and `fix` on output rails.
> Never use `reask` in production without rate-limit protection — it doubles LLM costs.

---

## 2. Validators: Length, Format, Regex, Semantic

### Length Validators
`ValidLength(min, max)` validates character or list-item count.  
Common pitfall: **Unicode characters count as 1 character regardless of byte size**.
For multilingual banking apps (Hindi, Tamil), test with non-ASCII strings.

### Format / Regex Validators
`RegexMatch(regex=...)` runs `re.search()` by default (partial match), not `re.fullmatch()`.
Always anchor your patterns:
```python
# Wrong — matches "abc123xyz" as well
RegexMatch(regex=r"\d{10}")

# Correct — IFSC code must be exactly 11 chars
RegexMatch(regex=r"^[A-Z]{4}0[A-Z0-9]{6}$")
```

### Semantic Validators
Semantic validators (e.g., `ToxicLanguage`, `BiasCheck`, `ProvenanceLLM`) use ML models
under the hood. Key considerations:

- **Latency**: Each semantic validator adds 200ms–2s to the guardrail pipeline.
  Chain them thoughtfully — put fast rule-based validators first.
- **Remote inference**: Guardrails Hub offers hosted inference for heavy validators.
  For banking data, **always use local inference** (`guardrails configure` → disable remote).
- **Threshold tuning**: Default thresholds are tuned for general English. Banking text
  (dense jargon, abbreviations like NPA, CIBIL, RTGS) may trigger false positives.
  Start with high thresholds (0.8+) and lower them after evaluation.

---

## 3. Custom Validators for the Banking Domain

### Validator Design Principles
1. **Single responsibility**: Each validator checks one concern.
2. **Fix vs block**: Use `fix_value` when the response can be repaired (add disclaimer).
   Use `FailResult` without `fix_value` when the response must be blocked entirely.
3. **Score conservatively**: Assign detection scores < 1.0 to allow the framework to
   combine scores from context words.
4. **Test with adversarial examples**: Try inputs designed to evade each pattern.

### Key Indian Banking Entities for Presidio

| Entity | Pattern | Risk if Leaked |
|---|---|---|
| Aadhaar | `[2-9]\d{11}` | Identity theft, UIDAI violation |
| PAN | `[A-Z]{5}[0-9]{4}[A-Z]` | Tax fraud, KYC bypass |
| IFSC | `[A-Z]{4}0[A-Z0-9]{6}` | Account targeting |
| UPI VPA | `[\w.-]+@[a-zA-Z]+` | Payment fraud |
| CIBIL Score | Numeric 300–900 in credit context | Privacy violation |

> **Important**: Presidio's default `PHONE_NUMBER` recogniser covers Indian mobile numbers
> (`+91` prefix), but may miss landline numbers. Add a custom pattern for `0XX-XXXXXXXX`
> format if your documents contain branch landlines.

---

## 4. Hallucination Detection and Mitigation

### Three Categories of Hallucination in RAG

| Type | Description | Detection Method |
|---|---|---|
| **Intrinsic** | LLM contradicts the source document | ProvenanceLLM validator; token overlap |
| **Extrinsic** | LLM adds information not in source | Provenance score below threshold |
| **Confabulation** | LLM generates plausible but invented details | LLM self-confidence scoring |

### Why RAG Alone Doesn't Prevent Hallucination
Retrieval grounds the LLM in relevant documents, but does not prevent it from:
- Blending information from multiple chunks incorrectly
- Fabricating page numbers or section titles that don't exist
- Applying a policy from one product type to another

**The defence in depth**: RAG (grounding) + provenance validator (detection) + confidence scoring (escalation) + HITL (fallback).

### Confidence Score Calibration
The LLM self-confidence approach (asking the LLM to score itself 1–10) is a form of
**verbal uncertainty quantification**. It is:
- Fast and cheap (one extra LLM call)
- Less accurate than ensemble methods or Monte Carlo Dropout
- Sufficient for a first-line filter; escalate to human for scores < 0.5

For a more rigorous approach in production, consider:
- **Semantic Entropy** (Kuhn et al., 2023) — run the query 3× with temperature=1.0,
  measure entropy across outputs
- **Factual Consistency Score** (FCS) using a dedicated NLI model

---

## 5. PII Detection and Data Protection

### Data Minimisation Strategy
Following **GDPR Art. 5(1)(c)** and **RBI IT Framework**:

1. **Query**: Hash stored in audit log; raw query never persisted
2. **Retrieved chunks**: Used in context; never cached to disk
3. **LLM response**: PII redacted before storage or logging
4. **Audit events**: `detail_excerpt` truncated to 200 chars

### Presidio Confidence Scores
Presidio assigns a confidence score (0–1) to each detected entity.
The default threshold is 0.35. For banking:
- **Raise to 0.7** for input blocking (avoid false positives that frustrate users)
- **Keep at 0.35** for output redaction (better safe than sorry)

You can tune per-entity thresholds:
```python
results = _analyzer.analyze(
    text=text,
    language="en",
    score_threshold=0.7   # Only flag high-confidence detections
)
```

### Pseudonymisation vs Anonymisation
| Technique | GDPR Status | Use Case |
|---|---|---|
| **Redaction** (replace with `<REDACTED>`) | Anonymisation | Audit logs, responses to users |
| **Pseudonymisation** (replace with consistent fake) | Pseudonymisation (still personal data) | Developer testing with real data patterns |
| **Tokenisation** (replace with reversible token) | Pseudonymisation | When you need to re-identify for downstream systems |

For this RAG system: use **redaction** on responses and **hashing** on audit logs.

---

## 6. AI Bias — Types and Mitigation

### Types of Bias Relevant to Banking AI

| Bias Type | Description | Example in Banking RAG |
|---|---|---|
| **Data bias** | Training data over/under-represents groups | LLM trained mostly on urban lending data may reflect urban-centric loan norms |
| **Model bias** | Model weights encode societal stereotypes | LLM produces more cautious loan advice for names that sound female |
| **Evaluation bias** | Benchmark doesn't represent all user groups | Testing only on English queries; system fails on Hinglish inputs |
| **Feedback bias** | RLHF reinforces majority-preference responses | Minority community financial queries rated lower in human feedback |

### Fairness Metrics

| Metric | Formula | Target |
|---|---|---|
| Demographic Parity | P(positive \| group A) = P(positive \| group B) | Equal approval rates across demographic groups |
| Equal Opportunity | TPR(A) = TPR(B) | Same rate of correctly identifying eligible applicants |
| Calibration | Confidence scores equally reliable across groups | No group gets systematically over/under-confident answers |

### Debiasing Techniques Applied Here
1. **Validator-level**: `BiasCheck` validator flags biased language in outputs
2. **Prompt-level**: System prompt explicitly forbids demographic differentiation
3. **Input-level**: Input sanitisation removes demographic proxies before LLM processing
4. **Evaluation**: `tests/test_guardrails.py` includes fairness test cases

---

## 7. Privacy and Data Protection in RAG

### The RAG Privacy Attack Surface

```
User Query → [Embedding] → Vector Search → [Retrieved Chunks] → LLM → Response
    ↑                              ↑                                      ↑
Query may contain PII    Chunks may embed PII         Response may echo PII
from user's account          from documents                from chunks
```

Each arrow is a potential privacy leak point. Presidio guards are applied at:
- **Query ingestion** (PII blocking on sensitive entities)
- **Response generation** (PII redaction on all output)

### Chunk-Level PII in Documents
During ingestion (`src/ingestion/ingestion.py`), consider adding a pre-ingestion
PII scan that redacts PII from document chunks before they are stored in PGVector.
This prevents PII from policy documents (e.g., sample customer names in templates)
from being retrieved and echoed in responses.

```python
# Recommended addition to ingestion.py
from src.guardrails.presidio_engine import redact_pii

# Before embedding each chunk:
chunk.page_content = redact_pii(chunk.page_content)
```

---

## 8. Enterprise AI Governance Framework

### The Four-Layer Governance Stack

```
Layer 1: Technical Controls     ← Guardrails AI validators, Presidio, NeMo rails
Layer 2: Process Controls       ← Human-in-the-Loop escalation, model cards
Layer 3: Organisational Controls← AI Ethics Committee, Responsible AI policy
Layer 4: Regulatory Controls    ← GDPR, CCPA, RBI IT Framework compliance mapping
```

### Model Card Template (Mandatory for Production)

Every model/LLM deployed in a banking system should have a model card documenting:
- **Model name and version**: e.g., `gemini-2.0-flash` (2025-Q1 checkpoint)
- **Intended use**: Banking policy Q&A; not for credit decisioning
- **Out-of-scope uses**: Real-time credit scoring, identity verification
- **Training data**: Unknown (Google proprietary) — reason for provenance guardrails
- **Known limitations**: May hallucinate loan rates not in context
- **Fairness assessment**: Bias tested on gender/age proxy queries (see test suite)
- **Guardrails applied**: List all active validators and their `on_fail` settings
- **Monitoring**: Audit log location; alert thresholds

### Risk Assessment Matrix

| Risk | Likelihood | Impact | Control | Residual Risk |
|---|---|---|---|---|
| PII leaked in response | Medium | Critical | Presidio redaction | Low |
| Hallucinated loan rate | High | High | ProvenanceLLM + HITL | Medium |
| Jailbreak injection | Low | High | DetectJailbreak + NeMo | Low |
| Biased credit advice | Medium | High | BiasCheck + proxy rules | Low |
| Model drift over time | Medium | Medium | Weekly audit log review | Medium |

---

## 9. Accountability and Explainability

### Decision Auditing
Every guardrail decision is logged with:
- A **hash** of the original query (linkable if the original query is known, but not reversible)
- The **event type** (what was triggered)
- The **guardrail** that triggered it
- A **timestamp** (ISO-8601 UTC)

This satisfies **GDPR Art. 22** requirements for automated decision documentation.

### Model Interpretability in RAG
Unlike a black-box classifier, RAG offers **native explainability**:
- `policy_citations` field shows which document section was used
- `page_no` lets auditors verify the source
- `confidence_score` quantifies uncertainty

For regulators, the chain `Query → Retrieved Chunk → Answer → Citation` is
the audit trail. Preserve it in every response.

### HITL (Human-in-the-Loop) Patterns

| Pattern | When to Use |
|---|---|
| **Escalation** | Confidence < 0.5; hallucination flagged → route to human agent |
| **Review queue** | Edge cases; novel query types → flag for human review before response |
| **Override** | Human expert can override a blocked response with justification logged |
| **Feedback loop** | Human corrections fed back to improve validator thresholds |

---

## 10. AI Governance and Compliance

### Internal AI Policy Checklist
Before deploying guardrails to production, verify:

- [ ] All validators tested with domain-specific adversarial examples
- [ ] Audit logs reviewed and confirmed to contain no raw PII
- [ ] Model card completed and version-controlled
- [ ] RAIL spec reviewed by Legal/Compliance team
- [ ] Data retention policy implemented (purge audit logs after N days per RBI norms)
- [ ] Incident response runbook tested with a simulated breach

### Third-Party Audit Preparation
For external auditors (SOC2, ISO 27001, RBI IT Examination):

1. **Evidence package**: `references/guardrails-setup.md` (technical controls)
2. **Test results**: `pytest tests/test_guardrails.py --html=audit_report.html`
3. **Audit logs**: Exported from application logs for the audit period
4. **Model card**: Signed by the AI system owner
5. **Guardrail configuration**: `src/guardrails/` directory (version history in Git)

### Industry Standards Alignment

| Standard | Alignment |
|---|---|
| **NIST AI RMF** | Govern → Map → Measure → Manage cycle implemented via audit logging + model cards |
| **ISO/IEC 42001** | AI management system; RAIL specs serve as AI system documentation |
| **EU AI Act (High Risk)** | Credit/financial AI = high risk; HITL + audit trails required |
| **RBI Master Direction on IT** | Annex 1 audit trails; Annex 7 incident management |

---

## 11. AI System Lifecycle Management

### Deployment Stages

```
Research  →  Development  →  Staging  →  Production  →  Monitoring  →  Retirement
   │               │             │             │               │              │
 Risk           Unit tests    Integration   Canary        Weekly audit   Model card
assessment     (validators)    tests        deploy        log review     archived
```

### Validator Version Pinning
Do not use `guardrails hub install hub://guardrails/toxic_language` without pinning
a version in production. Validators can change detection models between updates.

```bash
# Pin to specific version
guardrails hub install hub://guardrails/toxic_language@0.3.2
```

Add pinned versions to `pyproject.toml` using the validator's PyPI package name.

### Model Monitoring Checklist (Weekly)

- [ ] Check audit logs for spike in `OUTPUT_BLOCKED` events (indicates model drift)
- [ ] Check audit logs for spike in `INPUT_BLOCKED` events (indicates adversarial attack)
- [ ] Re-run `tests/test_guardrails.py` with the live model
- [ ] Review `HITL_ESCALATION` events for new query patterns not covered by existing guardrails
- [ ] Update validator thresholds if false positive/negative rates change

### Rollback Procedure

```bash
# 1. Block new requests (maintenance mode)
export GUARDRAIL_ON_FAIL_OUTPUT=exception   # Strictest mode

# 2. Identify last known good commit
git log --oneline src/guardrails/

# 3. Revert guardrails config
git revert <bad_commit_hash>

# 4. Redeploy
uvicorn main:app --reload

# 5. Verify
pytest tests/test_guardrails.py -v
```

---

## 12. Stakeholder Communication and Transparency

### User-Facing Transparency
The API should communicate guardrail activity to end users:

```json
{
  "answer": "The minimum CIBIL score for a home loan is typically 750 (indicative, subject to change).",
  "confidence_score": 0.87,
  "guardrails_applied": ["pii_input_check", "toxic_language", "provenance_llm", "pii_output_redaction"],
  "disclaimer": "This answer is based on policy documents as of the document upload date. Consult a financial advisor for decisions."
}
```

### Internal Stakeholder Reporting
Monthly report to AI Ethics Committee:
1. Total queries processed
2. Input blocks by category (PII, jailbreak, toxicity)
3. Output blocks/fixes by category
4. HITL escalation rate and resolution time
5. Validator false positive/negative rates from test suite
6. Any new regulatory guidance affecting guardrail configuration

---

*These notes are maintained alongside `guardrails-setup.md` and should be updated when validator versions, regulatory guidance, or project architecture changes.*
