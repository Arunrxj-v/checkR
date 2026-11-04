# CheckR — Local AI (Ollama + Gemma 3 4B) Implementation Report

Date: 2026-11-04
Status: complete — all tests green, real inference verified end-to-end

---

## 1. Summary

CheckR's mock AI pipeline has been replaced with **real local inference**:

* **Runtime:** Ollama (native API, `GET /api/tags` + `POST /api/chat`)
* **Model:** `gemma3:4b` — one model, two capabilities (handwriting OCR and
  answer evaluation), each with its own versioned prompt, schema and
  provenance record
* **Provider:** `AI_PROVIDER=ollama` (the default); `mock` survives only as an
  explicit opt-in for the test suite and the deterministic development seed
* **No paid/external APIs** (Gemini/OpenAI/Anthropic providers still exist as
  code, but nothing in the production path selects them and no API key is
  configured)
* **No silent fallback:** if Ollama is unreachable or the model is not
  installed, the submission fails with an actionable message — it never
  degrades into fabricated results

The teacher remains the final authority: `ai_score`, `teacher_score` and
`final_score` stay separate, every evaluation is flagged for review when
confidence is low or validation fails, and nothing auto-finalises.

---

## 2. Architecture

```
upload ──► job queue (existing worker)
              │
              ▼
   ┌─ Stage 1: process_submission ─────────────────────────────────────┐
   │ preflight_ai()  →  OllamaProvider.require_available()             │
   │     GET /api/tags  → unavailable | model_missing | ok             │
   │ per page: preprocess → POST /api/chat (image + handwriting_v2)    │
   │     strict JSON schema (RawOCR) → validate_ocr() → OCRResult row  │
   │     previous page's transcription passed as continuation context   │
   └────────────────────────────────────────────────────────────────────┘
              │ enqueue
              ▼
   ┌─ Stage 2: segment_answers_job ────────────────────────────────────┐
   │ model detected_answers (preferred) → line-scan heuristic (fallback)│
   │ multi-page answers merged; continuation/uncertainty flags kept     │
   │ Answer + AnswerRegion rows (page + normalised 0-1 box per answer)  │
   └────────────────────────────────────────────────────────────────────┘
              │ enqueue
              ▼
   ┌─ Stage 3: evaluate_submission ────────────────────────────────────┐
   │ per answer: question + max marks + expected answer + criteria      │
   │   + student transcription + ORIGINAL PAGE IMAGES + OCR confidence  │
   │   → POST /api/chat (text + images) → RawEvaluation schema         │
   │   → validate_evaluation(): 0 ≤ awarded ≤ max, criteria sum = total│
   │   → Evaluation row (provider/model/prompt_version/status/notes)    │
   │   → Answer.ai_score (+ flag when invalid / low confidence)         │
   └────────────────────────────────────────────────────────────────────┘
              │
              ▼
   READY_FOR_REVIEW ──► teacher accept / override / flag ──► finalize
        (human-in-the-loop; ai_score is never overwritten)
```

Key properties:

* **Background only** — inference runs inside the existing job queue; HTTP
  handlers never block on the model.
* **One page at a time** — pages are processed sequentially, `keep_alive=10m`
  keeps the model resident during a batch and releases it afterwards (8 GB
  Apple M1 friendly).
* **Cached** — OCR rows are reused per page + prompt version; re-processing is
  idempotent; evaluations are superseded (never deleted) on re-run.
* **Retried** — a single retry loop in `OllamaProvider._chat` covers transport
  errors, 5xx, malformed JSON and schema violations, with exponential backoff
  (`1.5 * 2**attempt`, `OLLAMA_MAX_RETRIES=2`). Configuration errors are never
  retried.
* **Fatal vs. recoverable** — `unavailable` / `model_missing` / `config` abort
  the whole submission immediately (`_fatal_ai_error`); a single bad page
  (e.g. `bad_response`) fails only that page and the batch continues.
* **Structured OCR** — the vision model returns per-question blocks
  (`question_number`, `transcription`, continuation flags, regions,
  `uncertain_segments`, `manual_review_required`); anything unusable is
  dropped, never repaired with invented geometry.

---

## 3. Files changed

### Backend — new

| File | Purpose |
| --- | --- |
| `backend/app/ai/ollama.py` | Production provider: availability probe (TTL-cached 15 s, 5 s timeout), native `/api/chat` (vision `images` + text, `format: "json"`, `keep_alive`), OCR + evaluation, retry/classification, `display_name_for()` → `Gemma 3 4B · Local` |
| `backend/app/prompts/ocr/handwriting_v2.py` | Versioned structured OCR prompt (faithfulness rules, uncertainty markers, no-hallucination instructions, JSON contract) |
| `backend/tests/test_ollama_provider.py` | Unit tests for the provider with mocked HTTP (availability, model-missing, image payload, retries, schema violations, capability switches) |
| `backend/tests/test_ocr_detection.py` | Question-number parsing, multi-page association, continuation flags, heuristic fallback, OCR validation |
| `backend/tests/test_processing_failures.py` | Ollama down / model missing / OCR disabled / fatal error mid-loop / one-bad-page / evaluation disabled / unknown provider |
| `backend/tests/test_evaluation_safety.py` | Marks in range, criteria reconciliation, low-confidence flagging, provider failure, provenance + audit, validation rules |
| `backend/tests/test_ollama_integration.py` | **Real inference** (auto-skipped without Ollama): handwritten sample → OCR → evaluation → teacher accept/override → audit |
| `docs/ollama-ai-implementation-plan.md` | Implementation plan (audit findings, gaps, phases) |

### Backend — modified

| File | Change |
| --- | --- |
| `app/core/config.py` | `ai_provider` default `ollama`; `ollama_base_url/model/request_timeout/max_retries/keep_alive`; `ocr_enabled` / `evaluation_enabled`; updated warnings |
| `app/ai/base.py` | `AIProviderError.kind` (`unavailable`/`model_missing`/`timeout`/`bad_response`/`config`); `previous_context` in the protocol |
| `app/ai/factory.py` | Rewritten — **mock fallback removed**; unknown provider raises a `config` error |
| `app/ai/schemas.py` | `RawDetectedAnswer`, `RawOCRDiagram`, `RawUnreadableRegion`, extended `RawOCR`; accepts the prompt's `transcription` key as an alias for `text` |
| `app/ai/validation.py` | Structured OCR normalisation (confidence clamp, region/box cleanup, per-answer structure) |
| `app/ai/types.py` | `OCRPageResult` extended (`detected_answers`, `diagrams`, `unreadable_regions`, `manual_review_required`) |
| `app/ai/http_utils.py` | JSON decode failures classified as `bad_response` |
| `app/ai/{gemini,openai,anthropic,local,mock}.py` | Accept `previous_context`; unchanged otherwise |
| `app/prompts/registry.py`, `app/prompts/ocr/__init__.py` | `handwriting_v2` is current; `handwriting_v1` kept for cached rows |
| `app/segmentation/segmenter.py` | Model-aware segmentation (`segment_answers`), `parse_model_question_number`, continuation/sub-question handling, heuristic fallback |
| `app/services/processing_service.py` | Preflight, capability switches, previous-page context, fatal-error abort, detected answers → segmentation, richer failure messages |
| `app/services/evaluation_service.py` | `provider=` override (seed only), `evaluation_enabled` guard, audit wording |
| `app/api/routes/system.py` | Normalised AI payload: `status/detail/display_name/available/model_installed/ocr_enabled/evaluation_enabled` on `/health` and `/settings` |
| `app/main.py` | Non-fatal startup AI status probe |
| `app/db/seed.py` | Fully deterministic seed — **no provider calls**; manuscript text stored as OCR with `provider="seed"`, `is_mock=True` |
| `.env.example` (and local `.env`) | `AI_PROVIDER=ollama`, `OLLAMA_*` block, capability switches |

### Frontend — modified (status/labels only, no redesign)

| File | Change |
| --- | --- |
| `src/lib/types.ts` | `AppSettings.ai` extended with status/detail/display name/capability flags |
| `src/lib/status.ts` | Production status labels (Ollama unavailable, Model not installed, Waiting for processing, Reading handwriting, Extracting answers, Evaluating answer, Ready for teacher review, Needs manual review, Processing failed) |
| `src/components/layout/AppShell.tsx` | `Gemma 3 4B · Local` badge; `MockModeBanner` → `AiStatusBanner` (unavailable / model-missing states) |
| `src/pages/SettingsPage.tsx` | Status badge, display name, capability flags, actionable hint (`ollama pull gemma3:4b`, `ollama serve`) |
| `src/pages/EvaluationWorkspace.tsx` | Provenance shown as `Ollama · local`, seed-data note wording |

---

## 4. Migrations

**None.** No ORM model changed — every field this feature needed
(`OCRResult.raw_response`, `Answer.detection_meta`, `Answer.is_handwriting_uncertain`,
`Evaluation.provider/model/prompt_version/engine_version/validation_notes`,
`Submission.processing_meta`, …) already existed in the initial schema
(`aa0ac4094fef_initial_schema.py`). Structure returned by the model is stored
inside the existing JSON/text columns, so no schema evolution was required and
existing databases work unchanged.

---

## 5. Mocks removed / retained

**Removed from production paths**

* `get_provider()` no longer falls back to `MockProvider` when the configured
  provider is missing or broken — an unknown/broken `AI_PROVIDER` raises
  `AIProviderError(kind="config")` with an actionable message.
* The seed demo no longer calls any provider: manuscript text and boxes are
  stored as OCR rows with `provider="seed"` and `is_mock=True`, and scoring is
  done by an explicitly constructed `MockProvider(seed_salt="seed")` passed as
  `provider=` — never selected implicitly.
* No simulated progress: the frontend only renders real pipeline states.

**Retained (explicitly labelled)**

* `AI_PROVIDER=mock` for the unit-test suite (conftest sets it before app
  import) — deterministic, offline, zero network.
* Mock results are always stored with `is_mock=True` and provider `mock`, and
  the UI distinguishes them; a real submission never receives a fabricated
  result.

---

## 6. Configuration

`.env` / `.env.example`:

```ini
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_REQUEST_TIMEOUT=300
OLLAMA_MAX_RETRIES=2
OLLAMA_KEEP_ALIVE=10m
OCR_ENABLED=true
EVALUATION_ENABLED=true
```

Defaults live in `app/core/config.py`; the model name is defined **once** there
and referenced everywhere else (provider, prompts, health payload, UI label).
Availability is checked with `GET /api/tags`; inference uses `POST /api/chat`
with `format: "json"` and, for OCR, the page image in `messages[].images`.

Error messages are actionable and tested:

* `Ollama is unavailable. Start the local Ollama service to process answer sheets.`
* `gemma3:4b is not installed. Run: ollama pull gemma3:4b`
* `Handwriting recognition is disabled (OCR_ENABLED=false).`
* `AI evaluation is disabled (EVALUATION_ENABLED=false).`

---

## 7. Test results

| Suite | Result |
| --- | --- |
| Backend unit/integration (offline) | **185 passed** |
| Backend real-Ollama integration | **2 passed** (skipped automatically when Ollama is absent) |
| Backend total | **187 passed**, `ruff check app tests` clean |
| Frontend unit tests | **34 passed** |
| Frontend `tsc --noEmit` | clean |
| Frontend production build | succeeds (371 kB JS / 35 kB CSS gzip 103/7 kB) |

New coverage highlights:

* `test_processing_failures.py` — Ollama down → submission `FAILED` with
  "Ollama is unavailable…", **zero OCR rows**; model missing → "ollama pull";
  OCR/Evaluation disabled; fatal error aborts the loop after one call;
  one bad page doesn't kill the batch (`failed_pages: [1]`); unknown provider
  is a config error, not mock.
* `test_evaluation_safety.py` — full/partial/zero marks; over-max clamped and
  marked `INVALID` + flagged; criterion over its own max clamped with a note;
  criteria sum overrides an inconsistent total; negative → 0; low confidence →
  "Low AI confidence" flag; missing reasoning → invalid; provider failure → no
  evaluation row, answer `FAILED`; reviewed answers never re-evaluated without
  force; provenance + audit assertions.
* `test_ocr_detection.py` — model question-number formats (`1`, `Q2`,
  `1(a)`, `2. c`, `5(i)`) and junk rejection (`192.168.10.0/26`), multi-page
  continuation both resolved and unresolved, sub-question roll-up, heuristic
  fallback, OCR region/box validation.
* `test_ollama_provider.py` — request shape (`/api/chat`, `format=json`,
  base64 image, system prompt), retry/backoff, missing-model classification,
  schema-violation retry, capability switches.

---

## 8. Real model test (end-to-end)

`pytest tests/test_ollama_integration.py -q -s` (requires `ollama serve` and
`ollama pull gemma3:4b`; auto-skips otherwise). It renders a handwritten page
with the macOS *Bradley Hand Bold* font, then runs the **real** pipeline and
the teacher flow. Runtime on this machine (Apple M1, 8 GB): **~70–110 s total**
for OCR + 2 evaluations.

Both tests passed. Captured output:

**Real OCR (`gemma3:4b`, prompt `handwriting_v2`):**

```
Q1. The three way handshake works like this:

the client sends SYN, the server replies SYN-ACK,
and the client sends ACK to establish the connection.

Q2. A /26 has 64 addresses so 62 usable hosts.
```

**Real evaluation:**

```
5.00/5.00 confidence=0.99 status=valid
reasoning: The answer correctly identifies all three stages of the TCP
three-way handshake and explains their roles in establishing a connection.
  - SYN packet: 1.00/1.00
  - SYN-ACK packet: 1.00/1.00
  - ACK packet: 1.00/1.00
  - Correct sequence: 1.00/1.00
  - Purpose or explanation: 1.00/1.00

2.00/6.00 confidence=1.00 status=valid
reasoning: The student correctly identifies the number of addresses and then
correctly calculates the number of usable hosts. …
  - Host bits: 0.00/2.00
  - Usable host count: 2.00/2.00
  - Broadcast address: 0.00/2.00
```

**Model identity:** `Gemma 3 4B · Local (gemma3:4b)`

Verified in the same run: OCR row is `is_mock=False`, `provider="ollama"`,
`prompt_version=handwriting_v2`, confidence in range; answers have
transcriptions and resolvable page/region links; evaluations carry
provider/model/prompt/engine provenance and `0 ≤ awarded ≤ max`; submission
ends `ready_for_review` (never auto-completed); teacher **accept** makes
`final_score == ai_score`; teacher **override** changes `teacher_score`/
`final_score` while `ai_score` is preserved; audit log contains
`answer.evaluated` and `answer.review.*`.

The Q2 result (2/6) is semantically correct: the student only wrote the usable
host count, so the two unwritten criteria scored zero — partial credit works
per criterion, not per keyword.

---

## 9. Known limitations / notes

1. **Latency & memory** — `gemma3:4b` at Q4 on an 8 GB M1: roughly 20–70 s per
   page/evaluation. `OLLAMA_REQUEST_TIMEOUT=300` covers it; large booklets take
   a while. `OLLAMA_KEEP_ALIVE=10m` balances reload cost vs. memory.
2. **Vision accuracy** — the verified sample transcribed perfectly, but small
   handwriting, diagrams and dense pages can still produce uncertainty. That is
   exactly what `uncertain_segments`, `manual_review_required`,
   `is_handwriting_uncertain` and the flagging path are for: uncertain answers
   are surfaced to the teacher instead of being silently graded.
3. **Model output drift** — a 4 B model occasionally omits fields or returns a
   total that disagrees with its criteria. The schema validation + retry loop
   repairs/clamps what it can (with `validation_notes`) and marks the rest
   `INVALID` + flagged; it never invents content.
4. **No Postgres/Docker in this environment** — the backend suite runs on
   in-memory SQLite (per `conftest.py`); production uses the existing Postgres
   migration, unchanged (§4).
5. **Other providers** (`gemini`, `openai`, `anthropic`, `local`) remain in the
   codebase but are untested by this work and not part of the production path;
   `AI_PROVIDER` defaults to `ollama`.
6. **Integration test is opt-in-by-environment** — it auto-runs when Ollama is
   up (as here) and skips otherwise; `CHECKR_SKIP_OLLAMA_TESTS=1` forces a skip
   on machines where inference must not run.
7. **`.env` is gitignored** — only `.env.example` is committed; the local
   `.env` carries the same Ollama block.

---

## 10. How to run

```bash
# one-time
brew install ollama            # if missing
ollama pull gemma3:4b
ollama serve &                 # http://localhost:11434

# backend
cd backend && uvicorn app.main:app --reload      # API
python -m app.worker                             # job worker (or WORKER_ENABLED=true)

# frontend
cd frontend && npm run dev

# tests
cd backend && python -m pytest -q                # 185 offline tests
python -m pytest tests/test_ollama_integration.py -q -s   # real inference (2 tests)
cd frontend && npm test && npm run build
```
