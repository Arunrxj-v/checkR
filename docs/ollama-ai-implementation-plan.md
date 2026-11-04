# CheckR — Replace Mock AI with Real Local Gemma 3 4B (Ollama)

Implementation plan produced from a full audit of the existing codebase on
2026-11-04. This document is the working plan; a final implementation report
follows the same structure.

---

## 1. Audit findings

### 1.1 What already exists (preserved, not rewritten)

| Area | Location | Status |
|---|---|---|
| React + Vite + TS frontend, design system | `frontend/` | preserved |
| FastAPI backend, auth, exams, submissions, results | `backend/app/` | preserved |
| Job queue / background worker | `app/workers/worker.py`, `app/services/job_service.py` | preserved |
| PDF rendering (PyMuPDF), preprocessing (OpenCV/PIL) | `app/imaging/` | preserved |
| Provider abstraction (`AIProvider` protocol, factory, validation) | `app/ai/base.py`, `factory.py`, `validation.py` | extended |
| Versioned prompts (OCR + 4 evaluation families) | `app/prompts/` | extended (OCR v2) |
| Heuristic question segmentation (cross-page) | `app/segmentation/segmenter.py` | extended (model-aware path) |
| Question ↔ page mapping, answer regions | `app/services/page_mapping.py` | preserved |
| Teacher review with audit trail (ai/teacher/final score separation) | `app/services/review_service.py` | preserved |
| Alembic migrations (single initial schema) | `alembic/versions/aa0ac4094fef_initial_schema.py` | unchanged |
| Tests (128 backend, 34 frontend) | `backend/tests/`, `frontend/src/**/*.test.ts` | extended |

### 1.2 Mock AI locations (to be removed from production paths)

| # | Location | Problem |
|---|---|---|
| M1 | `app/ai/mock.py` — `MockProvider` | deterministic fake OCR + fake scores |
| M2 | `app/ai/factory.py` | defaults to mock; **silently falls back to mock on unknown provider** |
| M3 | `app/core/config.py` | `ai_provider` defaults to `"mock"` |
| M4 | `.env` / `.env.example` / `docker-compose.yml` | `AI_PROVIDER=mock` configured |
| M5 | `app/db/seed.py` `_create_sample_submission` | calls the configured provider at startup, then overrides text with known manuscript (wasted real inference under a real provider) |
| M6 | `frontend/src/components/layout/AppShell.tsx` | "Mock AI" badge, `MockModeBanner` |
| M7 | `frontend/src/pages/SettingsPage.tsx` | "Mock"/"Live" badge + mock copy |
| M8 | `frontend/src/pages/EvaluationWorkspace.tsx` | "(mock)" provenance note |
| M9 | `app/services/evaluation_service.py` audit text | "Mock evaluation: …" |

### 1.3 Functional gaps vs. requirements

| # | Gap |
|---|---|
| G1 | No Ollama provider: `local` speaks OpenAI-compatible `/v1/chat/completions`, has no `/api/tags` availability/model check, defaults to `llava` |
| G2 | No connectivity/model verification at startup, `/health` or `/settings` (only checks `bool(AI_BASE_URL)`) |
| G3 | OCR prompt v1 returns only `{text, confidence, regions}` — no question numbers, sub-questions, continuation, diagrams, unreadable regions, `manual_review_required` |
| G4 | No previous-page context during OCR → multi-page continuation relies purely on regex heading detection |
| G5 | Segmentation ignores any model-reported answer structure |
| G6 | When Ollama is down the submission fails with the generic "No pages could be processed. Check the scan quality." instead of an actionable AI error |
| G7 | No `OCR_ENABLED` / `EVALUATION_ENABLED` switches, no `OLLAMA_*` settings |
| G8 | No tests for the Ollama wire protocol, unavailable/missing-model paths, invalid model JSON, model-detected continuation |
| G9 | Frontend statuses do not cover the required "Waiting for processing / Extracting answers / Evaluating answer / Ready for teacher review / Processing failed / Ollama unavailable / Model not installed" wording |

---

## 2. Target architecture (unchanged from task spec)

```
CheckR → FastAPI → AI service layer → Ollama runtime → gemma3:4b
                                          ├─ Vision/OCR  (handwriting_v2 prompt)
                                          └─ Evaluation  (theory|numerical|programming|diagram prompts)
```

One Ollama instance, one model, two internally separate capabilities
(separate prompts, separate services, separate provenance records).

---

## 3. Work items

### Phase A — Configuration & provider

1. **`app/core/config.py`**
   - `AIProviderName` += `"ollama"`; default `ai_provider = "ollama"`.
   - New settings: `ollama_base_url` (`http://localhost:11434`), `ollama_model`
     (`gemma3:4b`), `ollama_request_timeout` (300), `ollama_max_retries` (2),
     `ocr_enabled` (True), `evaluation_enabled` (True).
   - Warnings: no API key required for ollama; drop the production
     `AI_API_KEY` warning for it.
2. **`app/ai/ollama.py` (new)** — native Ollama client:
   - `GET /api/tags` → connection + model availability, TTL-cached (15 s).
   - `POST /api/chat` → vision (`images: [base64]`) and text inference,
     `stream=false`, `format=json`, temperature 0.1.
   - Timeout = `OLLAMA_REQUEST_TIMEOUT`, retries = `OLLAMA_MAX_RETRIES`
     with exponential backoff.
   - Typed errors with `kind` (`unavailable` / `model_missing` / `timeout` /
     `bad_response`) and actionable messages:
     - "Ollama is unavailable. Start the local Ollama service to process answer sheets."
     - "gemma3:4b is not installed. Run: ollama pull gemma3:4b"
   - `health()` → `{provider, model, display_name ("Gemma 3 4B · Local"),
     status: ok|unavailable|model_missing, ok, detail, is_mock:false, …}`.
3. **`app/ai/factory.py`** — wire `ollama`; **delete the silent mock
   fallback** (unknown provider now raises `AIProviderError`); `mock` remains
   selectable only when explicitly configured (tests + seed).
4. **`app/ai/base.py`** — `AIProviderError` gains `kind`; provider protocol
   gains optional `previous_context` kwarg for OCR (accepted by all providers,
   used by Ollama).

### Phase B — Structured OCR (Gemma vision)

5. **`app/prompts/ocr/handwriting_v2.py` (new, current)** — dedicated,
   version-controlled prompt: faithful transcription, preserve wording /
   terminology / math / language, question + sub-question numbers,
   continuation flags, diagrams, struck-through text, unreadable sections,
   uncertainty markers, never invent, never summarise, never correct the
   student → validated JSON
   `{page_number, transcription, confidence, detected_answers[{question_number,
   transcription, started_on_previous_page, continues_on_next_page, regions,
   uncertain_segments, confidence}], diagrams, unreadable_regions,
   manual_review_required}`. `handwriting_v1` stays in the registry (existing
   cached rows remain valid).
6. **`app/ai/schemas.py` / `app/ai/types.py`** — strict `RawOCR` extension +
   `OCRPageResult.detected_answers / diagrams / unreadable_regions /
   manual_review_required`.
7. **`app/ai/validation.py`** — normalise/clamp detected-answer regions and
   confidences; never fabricate values.
8. **`app/segmentation/segmenter.py`** — model-aware path:
   `segment_answers()` uses `detected_answers` when the model returned them,
   merging blocks across pages (continuation), mapping `1(a)` → question 1,
   flagging unresolved continuations/uncertain segments; falls back to the
   existing heuristic when no model structure is present.
9. **`app/services/processing_service.py`**
   - Preflight `provider.health()` before OCR/evaluation stages → fail fast
     with the actionable message (never a silent mock fallback).
   - Pass previous page's transcription as OCR context (continuation).
   - Persist model-detected answers (already inside `raw_response`), feed them
     to segmentation.
   - Honour `OCR_ENABLED` / `EVALUATION_ENABLED`.
   - One page at a time (M1-friendly), unchanged caching by
     `page_id + prompt_version`.

### Phase C — Evaluation

10. **`app/services/evaluation_service.py`** — honour `EVALUATION_ENABLED`,
    keep strict validation (`0 ≤ awarded ≤ max`, criteria sum = total),
    provenance (`provider, model, prompt_version, engine_version, created_at`),
    audit wording without "Mock".
11. Prompts for the 4 question families already exist and satisfy the
    criteria-based / partial-mark / semantic-equivalence rules — kept as-is.

### Phase D — Health, startup, seed, env

12. **`app/api/routes/system.py`** — `/health` and `/settings` report
    `ai.status`, `ai.detail`, `ai.display_name`, `ai.available`,
    `ai.model_installed`, `ai.ocr_enabled`, `ai.evaluation_enabled`
    (short-timeout, cached availability check).
13. **`app/main.py`** — startup logs the AI status (non-fatal warning with the
    actionable message when Ollama/model missing).
14. **`app/db/seed.py`** — seed demo submission becomes purely deterministic
    seed data: no provider calls at all (manuscript text + boxes stored as
    seed OCR, `provider="seed"`, `is_mock=True`, `processing_meta.seed_data`),
    evaluated with an explicitly constructed `MockProvider` (labelled
    `is_mock=True`). No real-submission path ever reaches mock.
15. **`.env`, `.env.example`, `docker-compose.yml`** —
    `AI_PROVIDER=ollama`, `OLLAMA_*`, `OCR_ENABLED`, `EVALUATION_ENABLED`
    (single source of truth for the model name: `OLLAMA_MODEL`).

### Phase E — Frontend (no redesign, status wording only)

16. `lib/types.ts` — extend `settings.ai` with the new status fields.
17. `lib/status.ts` — labels: *Waiting for processing, Reading handwriting,
    Extracting answers, Evaluating answer, Ready for teacher review,
    Processing failed* (+ answer-level *Needs manual review*).
18. `AppShell.tsx` — badge becomes "Gemma 3 4B · Local" with an
    available/unavailable state; `MockModeBanner` → `AiStatusBanner`.
19. `SettingsPage.tsx` — provider/model/status rows with actionable hint
    (`ollama pull gemma3:4b` / start Ollama).
20. `EvaluationWorkspace.tsx` — provenance shows the real model; seed rows
    labelled as seed data rather than "mock AI".

### Phase F — Testing

21. `tests/test_ollama_provider.py` — `/api/tags` availability (ok / model
    missing / unreachable), `/api/chat` image payload, invalid JSON retry,
    404 model-not-installed, actionable messages, health payload.
22. `tests/test_ocr_detection.py` — model-detected answers, multi-page
    continuation, sub-question mapping, unreadable/uncertain flags, heuristic
    fallback.
23. `tests/test_processing_failures.py` — Ollama down → submission FAILED with
    actionable message (no fabricated pages), OCR/EVALUATION disabled paths.
24. `tests/test_evaluation_safety.py` — zero/partial/full marks, invalid score
    ranges, malformed model output → flag/invalid, low confidence → teacher
    review flag.
25. `tests/test_ollama_integration.py` — optional, auto-skipped unless Ollama
    is reachable: real `gemma3:4b` OCR of a generated handwritten sample +
    real criteria-based evaluation + teacher accept/override + audit.
26. Existing 128 backend + 34 frontend tests must keep passing; production
    build must succeed.

### Phase G — Real end-to-end run

27. Generate an actual handwritten-style answer-sheet sample (macOS
    handwriting font rendered to PDF), run the full pipeline with real Ollama
    inference, capture sample OCR + evaluation output for the report.
