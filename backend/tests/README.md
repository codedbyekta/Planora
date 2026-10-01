# Backend test suite

Ported from the ad-hoc verification scripts used while building Steps
5-11, reorganized into proper pytest test modules.

## Setup

```bash
createdb planora_test   # once, a real separate Postgres database
pip install -r requirements-dev.txt
```

By default the suite connects to `postgresql://postgres:postgres@localhost:5432/planora_test`.
Override with `DATABASE_URL_TEST` in your environment or `.env` if your
local Postgres uses different credentials.

## Run

```bash
pytest            # whole suite
pytest -k rf      # just the Random Forest tests, etc.
pytest -x -v      # stop on first failure, verbose
```

The suite drops and recreates every table once per run (`conftest.py`,
session-scoped `_fresh_schema` fixture) so it always starts from a
known-empty state -- it is completely separate from your development
database and never touches it.

## Files

| File | Covers |
|---|---|
| `conftest.py` | Test-DB wiring, `TestClient`, `make_authed_user` fixture |
| `helpers.py` | Synthetic validated-session seeding (for RF/retraining tests that need 30+ sessions) |
| `test_session_lifecycle.py` | Start/pause/resume/interrupt/complete/feedback, validation, legacy endpoint, idle reclassification, interruption not auto-penalized |
| `test_baseline_fallback.py` | Historical-average fallback: validated-only filtering, exact average, multi-window predictions |
| `test_random_forest.py` | Training threshold, feature set, MAE/RMSE/baseline comparison, per-user isolation |
| `test_predictions_and_schedule.py` | `/predictions` never trains, difficulty↔focus-tier matching, urgent/deadline overrides, task-progress adaptivity, cross-user isolation |
| `test_retraining_promotion.py` | Retrain trigger, drift detection, candidate promotion/rejection, audit history, isolation |

## A note on synthetic data

Random Forest and retraining tests seed 30-45 sessions with a
deliberately injected time-of-day pattern (`helpers.seed_validated_sessions`)
because a test run obviously can't wait for real historical data to
accumulate. This proves the pipeline works end to end; it is not a claim
about how the model performs on real, noisier user data.
