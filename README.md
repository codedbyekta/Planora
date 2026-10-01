# Planora — Plan Tomorrow Around You

Planora is a personalized AI productivity scheduler. It learns each user's own focus patterns from their real, validated work sessions and uses that history to recommend **which task to do at which time**, based on predicted focus, task difficulty, priority, deadline, and remaining duration.

This project started as a Pomodoro-style task tracker (*TimeWise AI*) and was upgraded incrementally, step by step, into Planora — a full session-validation pipeline, a per-user Random Forest focus predictor with an honest historical-average fallback, a task × focus scheduling engine, and a monitored model-retraining/promotion flow. The upgrade preserved the original authentication, task management, and database rather than rebuilding from scratch.

## Problem statement

Most to-do apps assume every hour of your day is equally good for every task. In reality, people have real, personal, time-of-day focus patterns — some people do their best deep work at 9 AM, others at 9 PM — and those patterns don't show up anywhere in a plain task list. Planora tracks real focus sessions, turns them into a transparent, explainable score, and uses that history to suggest *when* to do *which* task, instead of just tracking *what* is left to do.

**Focus Score is a proxy for focus and engagement during a session — it is explicitly not a claim about how productive, correct, or valuable the work produced was.**

## Key features

- JWT authentication: register, login, logout, protected routes
- Task management with difficulty, priority, deadline, estimated/remaining duration, and status
- A full focus-session lifecycle: start → activity tracking → pause/resume → complete or interrupt → a feedback form that is the *only* way a session becomes validated
- Client-side idle detection that never auto-penalizes inactivity — the person confirms whether idle time was genuine distraction or heads-down thinking
- A transparent, weighted 0–100 Focus Score, computed only for validated sessions
- A historical-average fallback used until a user has enough validated history
- A per-user Random Forest focus predictor, trained only once 30+ validated sessions exist, and used only if it actually beats the naive historical average on held-out data
- Multi-window focus predictions (`GET /predictions`) and a single best-window recommendation (`GET /recommendations`)
- A task × focus scheduling engine (`GET /schedule`) that matches open tasks to predicted focus windows, respecting deadlines, priority, and remaining duration — not just sorting by predicted focus
- A monitored, gated model-retraining and promotion flow: new data volume, drift, and performance-degradation checks decide *whether* to retrain; a new candidate model is only promoted if it is actually as good as or better than the currently active one
- Strict per-user data and model isolation throughout

## Architecture

```
React + Vite (frontend)
        │  Axios + JWT
        ▼
FastAPI (backend)
  auth · tasks · sessions · predictions
  recommendations · schedule · dashboard
  analytics · weekly-report
        │
        ▼
PostgreSQL  ◄────────────┐
        │                │
        ▼                │
ml/ (pure Python, no HTTP)
  train_model.py    → feature engineering, RandomForest training/eval
  retrain_monitor.py → trigger / drift / degradation / promotion
  predict.py         → multi-window predictions (read-only re: training)
  recommendation.py  → single best-window recommendation
  schedule.py         → task × focus scheduling
```

`crud.py` is the only place that touches the database from route handlers; every query filters by the JWT-derived `user_id`. The `ml/` package has no FastAPI or HTTP dependency — it operates purely on ORM objects and plain Python data, which is what makes it possible to reuse it identically from routes, background tasks, and standalone scripts (`seed_data.py`, manual retrain runs).

## Tech stack

| Layer | Technologies |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS, React Router, Axios, Recharts |
| Backend | Python, FastAPI, SQLAlchemy 2.x, Pydantic v2 |
| Auth | JWT (python-jose), Passlib/bcrypt |
| Database | PostgreSQL, manual SQL migration script (no ORM auto-migrate, no Alembic) |
| ML | pandas, NumPy, scikit-learn (RandomForestRegressor), joblib |
| Background work | FastAPI `BackgroundTasks` (no Celery/Redis — not needed at this scale) |
| Tests | pytest, FastAPI `TestClient` |

## Database schema

```
users
 ├─ tasks              (title, description, difficulty, priority, deadline,
 │                       estimated_duration, remaining_duration, status, completed)
 ├─ focus_sessions      (start/end time, active/idle duration, pause_count,
 │                       focus_rating, engagement_rating, goal_status,
 │                       interrupted, interruption_reason, idle_reclassified,
 │                       focus_score, validation_status)
 ├─ predictions         (window_start/end, predicted_focus_score, source,
 │                       model_version) — append-only, kept for future
 │                       predicted-vs-actual analysis
 ├─ model_versions      (model_version, trained_at, training_sample_count,
 │                       validation_metric (MAE), model_status: active /
 │                       retired / rejected / candidate, feature_version)
 ├─ recommendations      (latest computed recommendation, cached for the dashboard)
 └─ productivity_logs    (original daily productivity aggregate, unchanged)
```

Every child table carries a `user_id` foreign key. Every query in `crud.py` filters by it, and it is always taken from the JWT via `get_current_user` — no endpoint accepts a client-supplied `user_id`.

## The ML pipeline

**Features** (target: `focus_score`, 0–100):

| Feature | What it is |
|---|---|
| `hour_of_day` | 0–23, from the session's start time |
| `day_of_week` | 0 (Monday) – 6 (Sunday) |
| `task_difficulty_encoded` | easy=0 / medium=1 / hard=2 |
| `session_duration` | total session length in minutes |
| `active_ratio` | active time ÷ (active + idle) time, with idle-reclassified time folded into "active" first |
| `pause_count` | number of pauses during the session |
| `previous_focus` | this same user's own immediately-preceding validated session's score (a lag feature; the very first session is backfilled with that user's own mean) |

Only sessions with `validation_status="valid"` are ever used — a session the user never rated, or one thrown out as too short to be meaningful, never enters training, a baseline average, or a "typical value" calculation.

**Historical-average fallback.** Below 30 validated sessions, Planora always uses a simple, transparent per-hour average — no ML involved. 30 is documented in code as an initial prototype safeguard, not a universal statistical rule.

**Random Forest.** At 30+ validated sessions, a `RandomForestRegressor` (50 trees, depth 5) is trained per user, from a small, swappable `MODEL_REGISTRY` so a different algorithm could be compared later without touching the rest of the pipeline. It's evaluated on a held-out 20% split (random by default; a chronological split exists behind a flag, not yet the default) and reports MAE, RMSE, and R². Crucially, it's also compared against a naive per-hour baseline computed from the training set and scored on the *same* held-out rows — the model is only considered usable (`beats_baseline: true`) if it actually beats that baseline. Crossing 30 sessions is never treated as proof the model is trustworthy.

**Retraining monitor and promotion.** A retrain is even considered only once 5+ new validated sessions have accumulated since the last training *attempt* (not since the active model's own snapshot — anchoring it to the last attempt is what prevents a rejected candidate from triggering a retrain on every subsequent request). Once that volume trigger fires, two diagnostic checks add context to *why*:
- **Drift** — has the mean focus score of the user's most recent sessions shifted by 15+ points from what the active model was trained on? A single unusual session can never trigger this; it only runs once enough new sessions exist and is an average, not a single point.
- **Performance degradation** — replaying the *currently active* model against those same recent sessions and checking whether its real-world error has grown to 1.5× its training-time MAE.

A freshly retrained candidate **never** automatically replaces the active model. It's promoted only if it trained successfully, beat the baseline, and either there's no active model yet or its MAE is at least as good as (or within a small stability tolerance of) the active model's MAE. Otherwise it's recorded with `model_status="rejected"` and the active model is left untouched. Every attempt — promoted or not — gets its own `model_versions` row; nothing is ever deleted, so the full lineage is queryable. The very first training for a user runs synchronously (so they see ML-backed results immediately); every retrain after that runs via FastAPI `BackgroundTasks` so it never blocks a request.

## Focus Score

Computed only for validated sessions, as a transparent weighted sum (0–100):

| Component | Weight |
|---|---|
| Self-reported focus + engagement ratings (1–5 each) | 35% |
| Active-time ratio (active ÷ active+idle, deep-work-confirmed idle counted as active) | 25% |
| Goal outcome (achieved / partial / not achieved) | 20% |
| Pause behavior (only heavy pausing costs points) | 10% |
| Active-duration consistency (was this a real block of time) | 10% |

Task difficulty is deliberately **not** a scoring weight — the score measures how focused a session was, independent of what was worked on; difficulty is used later by the scheduler, not baked into the score itself. An interruption is never automatically treated as low focus — only the actual worked time counts. A separate, older formula (duration ratio / completion / length bonus) still backs the original one-shot `POST /sessions` endpoint for backward compatibility.

## Scheduling algorithm

`GET /schedule` builds every valid `(task, predicted window)` pair, scores each one, sorts all pairs by score, and greedily claims the highest-scoring pair first — not a plain sort of tasks by predicted focus. The score combines:
- **Fit**: how well the task's difficulty matches the window's focus tier (high focus → hard tasks, low focus → easy tasks)
- **Priority bonus**: low/medium/high/urgent
- **Urgency bonus**: grows sharply as a task's deadline leaves it fewer and fewer eligible windows — this is what lets an urgent or deadline-critical task override the normal focus-based match

A window is only eligible if it starts before the task's deadline, and a slot's length is `min(remaining_duration, window length)` — a task longer than one window gets a note that it needs another session, rather than being silently truncated. Anything that can't be scheduled is reported with a specific reason (deadline already passed, lost to a higher-scoring task, etc). This is a single greedy pass, not a globally optimal solver — see Limitations.

## API overview

| Method & Path | Purpose |
|---|---|
| `POST /auth/register`, `POST /auth/login` | Account creation / JWT login |
| `GET /me` | Current user |
| `GET /tasks`, `POST /tasks`, `PUT /tasks/{id}`, `DELETE /tasks/{id}` | Task CRUD |
| `GET /tasks/{id}/suggested-time` | Best single time slot for one task |
| `POST /sessions` | Legacy one-shot session save (back-compat) |
| `GET /sessions` | List past sessions |
| `POST /sessions/start` | Begin a session |
| `POST /sessions/{id}/activity` | Aggregated activity heartbeat (never raw events) |
| `POST /sessions/{id}/pause` / `/resume` | Pause / resume |
| `POST /sessions/{id}/interrupt` | End a session due to interruption |
| `POST /sessions/{id}/complete` | End a session normally |
| `POST /sessions/{id}/feedback` | The only way a session becomes validated + scored |
| `GET /predictions` | Predicted focus score per candidate time window |
| `GET /recommendations` | Single best recommended window, with reason |
| `GET /schedule` | Full task → window plan, plus unscheduled tasks and why |
| `GET /dashboard`, `GET /analytics`, `GET /weekly-report` | Original app features, unchanged |

Every route resolves the user from the JWT — none accept a client-supplied `user_id`.

## Setup instructions

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ (developed and tested against PostgreSQL 16)

### PostgreSQL setup

```bash
createdb planora
```

### Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set DATABASE_URL to your local Postgres, and generate a SECRET_KEY:
python -c "import secrets; print(secrets.token_hex(32))"
```

**Environment variables** (`backend/.env`):

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/planora
SECRET_KEY=replace_this_with_a_random_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

**Initialize the database.** A fresh, empty database just needs the tables created:

```bash
python -c "from database import engine, Base; import models; Base.metadata.create_all(bind=engine)"
```

If you're upgrading an existing pre-Planora database instead of starting fresh, run the manual migration script (idempotent — safe to run more than once):

```bash
python migrate_to_planora.py
```

**Run the backend:**

```bash
uvicorn main:app --reload
```

The API is now at `http://localhost:8000` (interactive docs at `/docs`).

Optionally, seed some realistic demo data (a demo user with tasks and ~40 sessions with a deliberate focus pattern, so the ML/recommendation/scheduling pages have something to show immediately):

```bash
python seed_data.py
# login: demo@timewise.ai / demo1234
```

### Frontend setup

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL defaults to http://localhost:8000, which matches the backend above
npm run dev
```

The app is now at `http://localhost:5173`.

### How to run (full stack, quick reference)

```bash
# terminal 1
cd backend && source venv/bin/activate && uvicorn main:app --reload
# terminal 2
cd frontend && npm run dev
```

Then open `http://localhost:5173`, register an account, and go.

### How to test

```bash
cd backend
pip install -r requirements-dev.txt   # pytest, httpx (needed by TestClient)
pytest
```

The suite points at a separate database (`DATABASE_URL_TEST` in `.env`, defaulting to `planora_test`) so it never touches your real data, and creates/drops its own tables automatically. See `backend/tests/README.md` for how the suite is organized and what each file covers.

Frontend: no automated test suite is included. The component surface here is almost entirely "fetch from a well-typed backend endpoint and render it" (see the API overview above) — the kind of thing a snapshot or interaction test would mostly just restate, not verify anything meaningful. The genuinely test-worthy logic (session validation, scoring, scheduling, retraining/promotion) all lives in the backend and is covered there. `npm run build` is confirmed to succeed as part of this project's own verification (see below).

## Known limitations

- **Scheduling** is a single greedy pass, not a globally optimal assignment; a task longer than one window only gets that one window filled per call.
- **30 validated sessions** (initial ML training) and **5 new sessions** (retrain trigger) are prototype safeguards, not statistically derived thresholds.
- **Drift detection** uses a fixed 15-point mean-shift threshold with no significance test — a very noisy user's behavior could occasionally flag as "drift" without a real underlying change.
- **Model comparison**: a candidate and the active model are evaluated on different random test splits, not one shared held-out set, so the MAE comparison has some noise. Only MAE gates promotion; RMSE/R² are recorded but not used for the decision.
- **Model artifacts**: only the currently active model's file is kept on disk. Retired/rejected attempts leave a full audit row in `model_versions` but not a restorable model file.
- **Concurrency**: no per-user retrain lock, and the model file write isn't atomic — two near-simultaneous requests could both enqueue a retrain. `BackgroundTasks` runs in-process, so a queued retrain is lost if the server restarts mid-job.
- **Predictions** only ever cover hours the user has already logged sessions in, and the `predictions` table is append-only with no retention policy yet.
- **Retraining is request-triggered**: a user who never opens the recommendations or suggested-time views never triggers a retrain, however much new data they've logged.
- **Focus Score is a proxy for focus/engagement, not a measure of productivity or output quality** — this is a deliberate design choice, not an oversight.

## Future improvements

- A formal significance-based drift test, and drift-triggered (not just volume-triggered) retraining
- Time-based (chronological) train/test split as the default, not just an available flag
- Shared held-out evaluation set for candidate-vs-active model comparison; incorporate RMSE into the promotion decision
- Versioned, restorable model artifacts (not just metadata) for every `model_versions` row
- Per-user retrain locking and atomic model file writes
- Multi-slot scheduling for tasks longer than one window; an optimal-assignment solver as an alternative to the current greedy one
- Retention/de-duplication policy for the `predictions` table
- Alembic-based migrations instead of the current manual SQL script
- `GET /model/status` and `GET /analytics/focus` endpoints for surfacing model metadata and richer focus analytics directly
