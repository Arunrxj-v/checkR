# CheckR

**AI-assisted, human-in-the-loop evaluation of handwritten examination answer sheets.**

CheckR reads scanned answer-sheet booklets, splits them into per-question answers,
proposes a **criteria-level mark** for each answer against the examiner's marking
scheme, and then gets out of the way: nothing is ever finalised without a teacher
decision on the record.

The AI proposes. The examiner decides. Every decision is auditable.

![Evaluation workspace](docs/screenshots/evaluation-workspace.png)

---

## Table of contents

- [What it does](#what-it-does)
- [Design principles](#design-principles)
- [Screens](#screens)
- [Architecture](#architecture)
- [Processing pipeline](#processing-pipeline)
- [Human-in-the-loop guarantees](#human-in-the-loop-guarantees)
- [Data model](#data-model)
- [Repository layout](#repository-layout)
- [Quick start (Docker)](#quick-start-docker)
- [Local development (no Docker)](#local-development-no-docker)
- [Demo account & seed data](#demo-account--seed-data)
- [Configuration](#configuration)
- [Authentication & access](#authentication--access)
- [AI providers](#ai-providers)
- [Mock mode](#mock-mode)
- [API reference](#api-reference)
- [Frontend](#frontend)
- [Tests & linting](#tests--linting)
- [Production notes](#production-notes)

---

## What it does

| Area | Capability |
| --- | --- |
| **Authentication** | Email/password, bcrypt hashing, JWT access + refresh tokens, role-based access (`admin`, `teacher`, `evaluator`, `student`), ownership-scoped resources |
| **Examinations** | Create exams, define questions with type, max marks, expected answer, keywords, and an ordered **marking scheme** of criteria |
| **Uploads** | Multi-page PDF, JPG and PNG; page-count and size limits enforced at the API boundary |
| **Imaging** | Non-destructive preprocessing: deskew, contrast/normalisation, thumbnails. Originals are never overwritten |
| **OCR / transcription** | Handwriting transcription through a provider abstraction, with confidence and per-region bounding boxes |
| **Segmentation** | Splits page transcripts into answers keyed by question number, with low-confidence / unassigned text surfaced rather than silently dropped |
| **Evaluation** | Partial-mark scoring **per marking criterion**, plus reasoning, strengths, gaps, contradictions and flags |
| **Confidence** | Every AI result carries a confidence score banded into `high` / `medium` / `low`; low confidence is flagged for a human |
| **Review** | Accept, override with a teacher mark, or flag — with an optional examiner note |
| **Results** | Per-submission result, finalise / reopen, per-exam aggregates (average, high, low, completion) and CSV export |
| **Audit** | Immutable `audit_logs` record of every evaluation and review action, with actor, entity and description |
| **Jobs** | A durable PostgreSQL-backed queue with retries, plus an optional Redis wake-up signal |

---

## Design principles

1. **The AI never has the final word.** AI scores are stored separately from teacher
   scores and are never overwritten. A teacher decision supersedes, it does not erase.
2. **Never trust OCR blindly.** Every evaluation is given the raw answer *image* as
   well as the transcription, so the model can cross-check what the transcription
   claims. Low-confidence transcriptions are flagged for manual verification.
3. **Validate everything the model returns.** All model output is parsed, clamped and
   repaired before it can touch the database — never minted or invented. See
   `backend/app/ai/validation.py`.
4. **No secrets in code.** Configuration comes from the environment; the app warns at
   startup when a secret is weak or a provider is misconfigured.
5. **No fake features.** Every button, chip and panel in the UI is wired to a real
   endpoint and real state, including the explicit "Mock AI" provenance surfaced
   throughout the interface.

---

## Screens

| Dashboard | Evaluation queue |
| --- | --- |
| ![Dashboard](docs/screenshots/dashboard.png) | ![Evaluation queue](docs/screenshots/evaluation-queue.png) |

| Exam & marking scheme | Results |
| --- | --- |
| ![Exam detail](docs/screenshots/exam-detail.png) | ![Exam results](docs/screenshots/exam-results.png) |

| Sign in | Settings & audit trail |
| --- | --- |
| ![Login](docs/screenshots/login.png) | ![Settings](docs/screenshots/settings.png) |

| Evaluation workspace — question-bound manuscript viewer |
| --- |
| ![Evaluation workspace](docs/screenshots/evaluation-workspace.png) |

The interface follows the **Academic Precision** design system shipped in
`design files/`: a restrained navy/gold academic palette, tabular-figure marks
(`font-mono tnum`), and a three-panel evaluation workspace. Selecting a question
moves the manuscript viewer to the page it was detected on and highlights the
detected lines; the toolbar chip names those pages (`Q2 · Pages 1–2`).

---

## Architecture

```
                    ┌────────────────────────┐
   Browser  ──────► │  React + TS + Vite SPA │   (frontend/)
                    └───────────┬────────────┘
                                │  /api  (dev-server proxy in Docker)
                                ▼
                    ┌────────────────────────┐
                    │  FastAPI (app.main)    │  REST, JWT auth, rate limits
                    └───────┬────────┬───────┘
                            │        │ enqueue
              ┌─────────────┘        └──────────────┐
              ▼                                     ▼
   ┌────────────────────┐               ┌──────────────────────┐
   │ PostgreSQL         │  FOR UPDATE   │  Worker process      │
   │ (data + job queue) │◄──SKIP LOCKED─│  app.workers.worker  │
   └────────────────────┘               └──────────┬───────────┘
                                                   │
              ┌────────────────────────────────────┼────────────────────┐
              ▼                    ▼               ▼                    ▼
     ┌────────────────┐   ┌──────────────┐  ┌─────────────┐   ┌──────────────────┐
     │ Imaging        │   │ AI provider  │  │ Segmentation│   │ Storage          │
     │ PyMuPDF/Pillow │   │ mock|gemini| │  │ question↔   │   │ local | S3       │
     │ deskew, thumbs │   │ openai|...   │  │ answer      │   │ originals/pages  │
     └────────────────┘   └──────────────┘  └─────────────┘   └──────────────────┘
```

**Why PostgreSQL holds the queue:** correctness never depends on Redis. Jobs are
claimed with `SELECT … FOR UPDATE SKIP LOCKED`, so several workers can run safely
and a crash simply leaves the job to be retried. Redis is used only to shorten the
poll interval so the UI feels immediate — if it is down, everything still works.

---

## Processing pipeline

A submission moves through these statuses:

```
uploaded → processing → ocr_processing → answers_detected → ai_evaluating
        → ready_for_review → reviewed → completed
                                                   ↘ failed
```

Each stage is a job type (`process_submission`, `preprocess_page`, `ocr_page`,
`segment_answers`, `evaluate_answer`, `evaluate_submission`, `generate_result`):

1. **Extract** — PDF pages are rendered to images (or a JPG/PNG is taken as-is).
   The original artefact is stored untouched.
2. **Preprocess** — deskew, normalise, build a thumbnail. All derivatives are stored
   under separate keys.
3. **OCR** — the provider transcribes each page with a confidence and region boxes.
4. **Segment** — transcripts are split into answers keyed by question number. Text
   that cannot be attributed is reported, not discarded; uncertain boundaries are
   flagged. Each answer keeps the OCR region boxes it was read from, together with
   the page each box belongs to, so the workspace can open the manuscript on the
   right page instead of inferring it from roster position.
5. **Evaluate** — each answer is scored criterion-by-criterion against the marking
   scheme, with the answer image supplied alongside the transcription.
6. **Await review** — the submission lands in `ready_for_review` and appears in the
   evaluation queue.
7. **Finalise** — once every answer carries a teacher decision, the sheet can be
   finalised and its result becomes final.

---

## Human-in-the-loop guarantees

- **AI and teacher marks are stored in different columns.** `answers.ai_score` is
  never mutated by a review; `answers.teacher_score` records the human value. The
  `final_score` is the effective one.
- **Superseded evaluations are retained.** Re-running the AI creates a new
  `evaluations` row; the previous one remains queryable via
  `GET /api/answers/{id}/evaluations`.
- **Every decision is an immutable audit record** (`answer.review.accepted`,
  `answer.review.overridden`, `answer.review.flagged`, `submission.finalised`, …).
- **Finalisation requires completeness.** Finalising a sheet with unreviewed answers
  is rejected with a `400` explaining what remains.
- **Reopening is explicit and audited** (`POST /submissions/{id}/reopen`).

---

## Data model

15 tables, created by the initial Alembic revision:

| Table | Purpose |
| --- | --- |
| `users` | Accounts, bcrypt password hashes, roles |
| `refresh_tokens` | Rotating refresh tokens |
| `exams` | Examinations owned by a teacher |
| `questions` | Questions with type, marks, expected answer, keywords |
| `marking_criteria` | Ordered per-question criteria and their marks |
| `submissions` | One student's booklet, status, aggregates |
| `submission_pages` | Page artefacts (original / processed / thumbnail keys) |
| `answers` | Per-question detected answers, transcription, AI + teacher marks |
| `answer_regions` | Bounding boxes mapping an answer to page regions |
| `ocr_results` | Raw OCR output, confidence, provider/model provenance |
| `evaluations` | One row per AI evaluation run (provider, model, prompt, engine) |
| `evaluation_criteria` | Per-criterion outcome for an evaluation |
| `teacher_reviews` | Human decisions, with reason and actor |
| `processing_jobs` | Durable job queue |
| `audit_logs` | Immutable action log |

`JSON` columns use native `JSONB` on PostgreSQL with a portable fallback elsewhere,
so the same models run on SQLite in tests.

**Question → answer → page mapping.** The relationship the workspace navigates by
lives in `answer_regions`: each row points at a `submission_pages` row and carries
normalised `(x0, y0, x1, y1)` coordinates. `app/services/page_mapping.py` builds the
per-answer view of that data for `GET /api/answers/{id}` (`pages`, ordered by page
number, each with its regions) and `GET /api/submissions/{id}/answers`
(`page_numbers` for the roster). Nothing is hard-coded in the frontend and no
mapping is ever invented:

| Source | `page_mapping_source` | `page_mapping_uncertain` |
| --- | --- | --- |
| Region boxes recorded during segmentation | `regions` | `false` |
| Detection metadata (`source_pages`) only, e.g. a boundary that spanned pages | `detection_meta` | `true` |
| No evidence at all | `unknown` | `true` (`pages: []`) |

When the mapping is unknown the viewer stays where it is and says so — it never
falls back to page 1.

---

## Repository layout

```
checkR/
├── backend/
│   ├── app/
│   │   ├── ai/            provider abstraction, mock/gemini/openai/anthropic/local, validation
│   │   ├── api/           routers, dependencies, rate limits
│   │   ├── core/          config, logging, security
│   │   ├── db/            base, session, enums, seed
│   │   ├── imaging/       PDF rasterisation and page preprocessing
│   │   ├── models/        SQLAlchemy models
│   │   ├── prompts/       versioned prompt modules (OCR + per-answer-type evaluation)
│   │   ├── schemas/       Pydantic request/response models
│   │   ├── segmentation/  question ↔ answer segmentation
│   │   ├── services/      business logic (incl. page_mapping.py — answer → page)
│   │   ├── storage/       local + S3 backends
│   │   ├── workers/       background worker
│   │   └── main.py        FastAPI app factory
│   ├── alembic/           migrations
│   ├── tests/             pytest suite
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/    UI primitives, layout, domain components
│   │   ├── lib/           API client, types, formatting, authOptions.ts, answerNavigation.ts
│   │   └── pages/         one module per screen
│   └── Dockerfile
├── design files/          visual source of truth
├── docs/screenshots/
├── docker-compose.yml
└── .env.example
```

---

## Quick start (Docker)

Requires Docker with Compose v2.

```bash
cp .env.example .env          # then edit the ports/secret if needed
docker compose up --build
```

Then open **http://localhost:5173** and sign in with the demo account below.

The stack starts four services:

| Service | Host port (default) | Notes |
| --- | --- | --- |
| `frontend` | `5173` (`FRONTEND_HOST_PORT`) | Vite dev server; proxies `/api` to the backend |
| `backend` | `8000` (`BACKEND_HOST_PORT`) | Runs migrations, seeds, then serves the API |
| `postgres` | `5432` (`POSTGRES_HOST_PORT`) | Primary datastore **and** job queue |
| `redis` | `6379` (`REDIS_HOST_PORT`) | Optional wake-up signal only |

If any of those ports are already taken on your machine, change the matching
variable in `.env` — the published ports are configurable for exactly this reason.

Useful commands:

```bash
docker compose logs -f backend          # follow API logs
docker compose exec backend pytest -q   # run the test suite in the container
docker compose exec postgres psql -U checkr -d checkr
docker compose down                     # stop (keeps volumes)
docker compose down -v                  # stop and wipe data
```

---

## Local development (no Docker)

**Backend** (Python 3.11+; 3.12/3.13 are both fine):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Point the app at a PostgreSQL instance. Use the values published in the
# repository .env (the compose stack maps its Postgres to 5434, not 5432):
export DATABASE_URL="postgresql+asyncpg://checkr:checkr@localhost:5434/checkr"
export DATABASE_URL_SYNC="postgresql+psycopg://checkr:checkr@localhost:5434/checkr"

alembic upgrade head
python -m app.db.seed                      # create the demo account + sample data

# Serve on the port the repository publishes (BACKEND_HOST_PORT in .env — 8010
# here, because 8000 is commonly already taken). The frontend dev server reads
# the same value, so the two stay in step.
export BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-8010}"
uvicorn app.main:app --reload --port "$BACKEND_HOST_PORT"
```

A worker is only needed for background jobs:

```bash
cd backend && python -m app.workers.worker
```

**Frontend**:

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173 (5174 if the compose stack holds 5173)
```

The dev server serves the SPA and proxies `/api` to the backend, so the app is
always same-origin (no CORS in the login path). The target is resolved in this
order — `VITE_PROXY_TARGET` from the environment (docker compose sets this to
`http://backend:8000`, since container ports are not host ports), then
`VITE_PROXY_TARGET` in an env file, then
`http://127.0.0.1:$BACKEND_HOST_PORT` from the repository `.env`, then
`http://127.0.0.1:8000`. Vite prints the resolved target on startup and probes it:

```
➜  /api        proxied to http://127.0.0.1:8010
```

`127.0.0.1` is used deliberately rather than `localhost`, which can resolve to
IPv6 and reach an unrelated service.

### If sign-in returns 404 or 500

The login request goes to `/api/auth/login` on the dev server's own origin and is
forwarded to the backend, so a failure there is a **proxy target** problem, not a
missing route:

| What you see | What it means |
| --- | --- |
| `{"error":{"code":"not_found"}}` (no `detail` field) | Something that is not CheckR owns the target port |
| `500` / `ECONNREFUSED` in the Vite log | Nothing is listening on the target port |

Check the `➜  /api  proxied to …` line, and the startup probe warning if there is
one. To point the dev server somewhere else for one run:

```bash
VITE_PROXY_TARGET=http://127.0.0.1:8010 npm run dev
```

To confirm the backend itself is healthy:

```bash
curl -s http://127.0.0.1:8010/api/health
curl -s -X POST http://127.0.0.1:8010/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"teacher@checkr.edu","password":"CheckR!2026"}'
```

---

## Demo account & seed data

On start, CheckR ensures the demo data exists:

- a teacher — **`teacher@checkr.edu` / `CheckR!2026`**
- the exam **Computer Networks — Internal Examination (CS312, 45 marks)** with
  5 questions and full marking schemes
- one generated answer-sheet booklet for *Marcus Vance (2026-CN-014)*, drawn as a
  three-page PDF and pushed through the whole pipeline, so the evaluation queue,
  workspace and results are populated immediately

In mock mode the seeded script is read back as a coherent manuscript (the
transcript matches what is visibly written on the page, and the regions it reports
match where those lines were drawn) and evaluated, leaving some answers flagged for
manual review so the review workflow is demonstrable. The seeded script also
exercises the page mapping: Q1 is on page 1, **Q2 continues across pages 1–2**, and
Q3–Q5 are on pages 2–3.

Seeding is idempotent — the demo **account** is guaranteed and the demo exam and
sample submission are created once, then left alone. It runs automatically on
backend startup (`SEED_ON_STARTUP`, never in production) and can be run on demand;
this is the only supported way the demo credentials are created — there is no
manual `INSERT` anywhere:

```bash
docker compose exec backend python -m app.db.seed    # ensure demo account + data
docker compose down -v && docker compose up --build  # rebuild from empty
```

The seeded credentials are a **development affordance, not a shipped password**.
The sign-in screen never hard-codes them: it asks the server
(`GET /api/auth/environment`) which account may be advertised, and the server
answers `null` in production no matter what the environment says
(`EXPOSE_DEMO_CREDENTIALS` is ignored when `ENVIRONMENT=production`, and a startup
warning records that it was ignored). In production the panel is absent from the
DOM entirely, and the seeded account is not created at all.

---

## Configuration

All configuration is environment-driven. See `.env.example` for the annotated
list. Highlights:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development` \| `production` |
| `DATABASE_URL` / `DATABASE_URL_SYNC` | localhost Postgres | Async driver / sync (Alembic) driver |
| `REDIS_URL` | `redis://localhost:6379/0` | Optional job wake-up signal |
| `JWT_SECRET` | insecure default | **Must** be replaced in production (surfaced at startup) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | `30` / `14` | Token lifetimes |
| `AI_PROVIDER` | `mock` | `mock` \| `gemini` \| `openai` \| `anthropic` \| `local` |
| `AI_API_KEY` | *(empty)* | Provider credential — never hard-coded |
| `AI_CONFIDENCE_HIGH` / `AI_CONFIDENCE_MEDIUM` | `0.85` / `0.60` | Confidence banding |
| `STORAGE_PROVIDER` | `local` | `local` \| `s3` |
| `MAX_UPLOAD_MB` / `MAX_SUBMISSION_PAGES` | `40` / `80` | Upload guardrails |
| `WORKER_POLL_INTERVAL_SECONDS` / `WORKER_MAX_ATTEMPTS` | `2` / `3` | Queue behaviour |
| `SEED_ON_STARTUP` | `true` | Seed demo data on first boot |
| `SELF_REGISTRATION_ENABLED` | `false` | Allow sign-up from the sign-in screen (see below) |
| `EXPOSE_DEMO_CREDENTIALS` | *(unset)* | Show the demo hint; development only, ignored in production |

`.env` is gitignored; only `.env.example` is committed.

---

## Authentication & access

CheckR is deployed as **institution-controlled infrastructure**, so the default is
that nobody can create an account from the sign-in screen:

- **Account provisioning is administrative.** `SELF_REGISTRATION_ENABLED` defaults
  to `false`; the seed script (or an operator) creates accounts out of band.
  `POST /api/auth/register` returns **403** while it is closed — the link is hidden
  in the UI *and* refused by the server. Set the flag to `true` only if open sign-up
  is a deliberate decision for a deployment.
- **The server decides what the screen may show.** `GET /api/auth/environment`
  (public, no token) returns `{ environment, self_registration_enabled,
  demo_credentials }`. The SPA renders the registration link and the development
  demo hint from that payload, and fails closed while it loads or if it errors.
- **Sign-in failures never enumerate accounts.** An unknown address and a wrong
  password both return `401 Invalid email or password.`, surfaced as an inline
  alert next to the form rather than a transient toast.
- **Credentials are never logged.** The logging configuration redacts any line
  containing sensitive keywords; request bodies are not logged.
- **Protected routes** are wrapped in `RequireAuth`, which redirects anonymous
  visitors to `/login` and returns them to the page they asked for after sign-in.
  Access tokens live in memory-backed `localStorage` and expire in 30 minutes;
  a failed refresh signs the session out everywhere at once.
- **Responsive sign-in.** Two panels on desktop (institutional message + form); a
  single centred column below `lg`, with the brand collapsed to the wordmark and
  the "audit, line by line" promise.

---

## AI providers

The provider abstraction lives in `backend/app/ai/`. Every provider implements the
same two operations — transcribe a page, and evaluate an answer — and returns the
same typed result, so the rest of the system is provider-agnostic.

| Provider | Notes |
| --- | --- |
| `mock` | **Default.** No network, no cost, deterministic. See below. |
| `gemini` | Google Gemini vision models |
| `openai` | OpenAI chat/vision models |
| `anthropic` | Claude models |
| `local` | Any OpenAI-compatible endpoint via `AI_BASE_URL` (e.g. Ollama, vLLM) |

Prompts are versioned modules under `backend/app/prompts/` — one for OCR plus one
per answer type (`theory_v1`, `numerical_v1`, `programming_v1`, `diagram_v1`), with a
shared engine version. Every evaluation row records the **provider, model, prompt
version and engine version** that produced it, and the UI shows that provenance, so
a mark can always be traced back to exactly how it was produced.

Switching provider is configuration only:

```bash
AI_PROVIDER=gemini
AI_API_KEY=...            # never committed
AI_MODEL=gemini-2.0-flash
```

---

## Mock mode

`AI_PROVIDER=mock` (the default) makes the entire product testable offline:

- No network calls and no API key required.
- Output is derived from a **stable hash of its inputs**, so the same page or answer
  always produces the same result — tests can assert exact outcomes.
- Every result is tagged `is_mock=True`, and the UI distinguishes mock from real AI
  in three places: the header chip, the Settings screen, and the per-answer
  *Evaluation Provenance* panel, which also warns that the score is for
  demonstration only.

This is what makes the demo reproducible: what you see in the screenshots is what a
fresh `docker compose up` produces.

---

## API reference

All routes are under `/api`. Authentication is a bearer JWT.

**System**

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness plus database, storage and AI status and config warnings |
| `GET` | `/settings` | Effective runtime configuration (secrets redacted) |
| `GET` | `/audit-logs` | Immutable audit trail |

**Auth**

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/auth/environment` | Public sign-in policy: registration + demo hint (never credentials in production) |
| `POST` | `/auth/register` | Create an account — **403** unless `SELF_REGISTRATION_ENABLED` |
| `POST` | `/auth/login` | Obtain access + refresh tokens |
| `POST` | `/auth/refresh` | Exchange a refresh token |
| `POST` | `/auth/logout` | Revoke a refresh token |
| `GET` | `/auth/me` | Current user |
| `PATCH` | `/auth/me` | Update profile |
| `POST` | `/auth/password` | Change password |

**Exams & questions**

| Method | Path | Description |
| --- | --- | --- |
| `GET`/`POST` | `/exams` | List / create |
| `GET`/`PATCH`/`DELETE` | `/exams/{exam_id}` | Read / update / delete |
| `GET` | `/exams/{exam_id}/stats` | Queue and review statistics |
| `GET`/`POST` | `/exams/{exam_id}/questions` | List / add questions |
| `PATCH`/`DELETE` | `/questions/{question_id}` | Update / delete a question |
| `GET` | `/exam-limits` | Upload/page limits for the client |

**Submissions & pages**

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/exams/{exam_id}/submissions` | Upload one or more booklets (multipart) |
| `GET` | `/submissions` | List, filterable by `exam_id`, `status`, `search` |
| `GET` | `/submissions/{id}` | Detail including pages |
| `GET` | `/submissions/{id}/status` | Lightweight polling target |
| `PATCH`/`DELETE` | `/submissions/{id}` | Update metadata / delete |
| `GET` | `/submissions/{id}/pages` | Page list |
| `GET` | `/pages/{page_id}/image?variant=` | Authenticated page image (`original`\|`processed`\|`thumbnail`) |
| `POST` | `/pages/{page_id}/retry` | Retry a failed page |
| `POST` | `/submissions/{id}/process` | (Re)run the pipeline |
| `GET` | `/submissions/{id}/jobs` | Job history for the submission |

**Answers, review & results**

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/submissions/{id}/answers` | Detected answers, each with `page_numbers` for the roster |
| `GET` | `/answers/{id}` | Full detail: page mapping (`pages`), regions, question, marking scheme, evaluation, reviews |
| `GET` | `/answers/{id}/evaluation` | Current evaluation |
| `GET` | `/answers/{id}/evaluations` | Evaluation history (superseded runs retained) |
| `POST` | `/answers/{id}/evaluate` | Queue a re-evaluation |
| `PUT` | `/answers/{id}/review` | `accepted` \| `overridden` \| `flagged` |
| `GET` | `/answers/{id}/reviews` | Review history |
| `GET` | `/submissions/{id}/result` | Result for a submission |
| `POST` | `/submissions/{id}/finalize` | Finalise (requires all answers reviewed) |
| `POST` | `/submissions/{id}/reopen` | Reopen a finalised sheet |
| `GET` | `/submissions/{id}/progress` | Answer counts by status |
| `GET` | `/exams/{exam_id}/results` | Exam overview rows for CSV export |

Interactive docs are available at **http://localhost:8000/docs** while the backend
is running.

---

## Frontend

React 18 + TypeScript + Vite + Tailwind, with `@tanstack/react-query` for server
state and `react-router-dom` for routing.

| Route | Screen |
| --- | --- |
| `/` | Dashboard — queue counters, recent activity |
| `/exams`, `/exams/:id` | Examinations and question/marking-scheme authoring |
| `/answer-sheets` | All candidate scripts with processing state |
| `/evaluation`, `/submissions/:id/evaluate` | Evaluation queue and the three-panel workspace |
| `/submissions/:id` | Submission status and pages |
| `/results`, `/results/:examId` | Results and per-exam aggregates with CSV export |
| `/settings` | Runtime config, account, audit trail |

**Keyboard shortcuts in the workspace:** `N` next answer, `P` previous, `A` accept,
`E` override (focuses the mark field), `F` flag, `+`/`-` zoom. `N`/`P` re-select the
answer *and* re-synchronise the manuscript viewer with it.

**Question-bound manuscript viewer.** Selecting a question drives the viewer to the
page that answer was actually detected on, highlights the detected regions, and
updates the answer-scoped page counter (e.g. `Q3 · Pages 5–6`, `Current answer page:
1 / 2`). Multi-page answers page only through their own pages; single-page and
unmapped answers fall back to whole-document navigation. Page navigation never
changes the selected question, the last page viewed per answer is restored when you
return to it, and an unconfirmed mapping is labelled "uncertain" rather than
guessed. The rules live in `src/lib/answerNavigation.ts` (unit-tested) — the
component only wires them up.

Page scans sit behind an authorised endpoint, so `<img src>` cannot be used
directly. The `AuthImage` component fetches the bytes with the bearer token and
serves them from a short-lived object URL. `npm run build` is TypeScript-strict
(`tsc -b && vite build`) and passes cleanly.

**Sign-in.** Two panels on desktop, one centred column below `lg`. The screen asks
`GET /api/auth/environment` what to render, so the registration link and the
development demo hint are policy from the server, not constants in the bundle —
there is no password anywhere in `frontend/src`. The decision logic lives in
`src/lib/authOptions.ts` (unit-tested) and fails closed: nothing extra is shown
until the server has answered.

---

## Tests & linting

```bash
cd backend
.venv/bin/python -m pytest -q          # 125 tests
.venv/bin/ruff check app tests         # lint (also run in CI)

cd ../frontend
npm test                               # vitest — viewer navigation + sign-in policy
```

The suite covers auth and ownership, the upload/processing pipeline, OCR and
evaluation validation, segmentation, the answer → manuscript-page mapping (at the
API boundary and in the pure mapping module), review semantics (AI score preserved
on override), finalisation rules and result aggregation. Tests run against SQLite via
`aiosqlite`, so no database service is required. The frontend tests model the
workspace's viewer (question selection, multi-page answers, `N`/`P`, manual page
navigation, uncertain mappings, returning to a question) and the sign-in policy
(registration hidden when closed, demo credentials only from a non-production
payload, fail-closed while the environment loads).

Two security properties are pinned by tests rather than convention:
`backend/tests/test_auth_environment.py` asserts that demo credentials are never
returned in production — even with `EXPOSE_DEMO_CREDENTIALS=true` — and that
registration is refused while it is disabled. The browser suite
(`/tmp/checkr_verify/login_check.mjs` during development) additionally drives the
real login screen in both a development and a production-shaped stack: loading
state, invalid and valid sign-in, sign-out, protected-route redirect, the absence
of shipped credentials, and the mobile/tablet/desktop layouts.

---

## Production notes

- **Set `JWT_SECRET`** to a long random value; the app warns when it is weak or
  default. Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- **Set `ENVIRONMENT=production`** — this disables the interactive API docs
  (`/docs`) and demo seeding, and enables the production configuration checks that
  run at startup.
- **Use S3-compatible storage** for answer-sheet artefacts:
  `STORAGE_PROVIDER=s3` plus `S3_BUCKET`, `S3_REGION` and credentials. The storage
  interface is already provider-independent, so no application code changes.
- **Run the worker as a separate process/container** and scale it horizontally —
  job claiming is safe under concurrency.
- **Frontend**: `npm run build` emits a static bundle in `frontend/dist/` to serve
  from any static host or CDN. The frontend `Dockerfile` intentionally runs the dev
  server, because `docker-compose.yml` is a development stack.
- **Rate limits** are applied to authentication, upload and evaluation endpoints.
- **Accounts are provisioned, not self-served.** Keep `SELF_REGISTRATION_ENABLED`
  at its default (`false`) and create operator accounts from the host (the seed
  script, a management command, or your institution's directory sync). The demo
  hint disappears on its own in production; `EXPOSE_DEMO_CREDENTIALS` is ignored
  and reported as a warning if it was left on.
- **Secrets**: nothing secret is committed; `.env` is gitignored and only
  `.env.example` ships.
