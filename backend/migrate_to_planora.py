"""
migrate_to_planora.py
----------------------
One-off manual migration for the TimeWise AI -> Planora upgrade.

We're intentionally NOT introducing Alembic for this prototype (per
project decision) -- this script is the whole migration story. It's
idempotent: every statement uses IF NOT EXISTS, so running it twice
(or against a fresh DB that already has the new schema) is a no-op,
not an error.

What it does:
    1. Adds the new columns to `tasks` and `focus_sessions`.
    2. Backfills sensible defaults for existing rows (so old data
       doesn't end up with NULLs where the app expects a string/int).
    3. Creates the new `predictions` and `model_versions` tables.
    4. Creates the (user_id) / (user_id, start_time) indexes.

Run it once, after pulling the new code and before starting the
backend, against whatever DATABASE_URL your .env already points at:

    cd backend
    python migrate_to_planora.py

For a brand-new database (nothing deployed yet), you don't need this
at all -- `Base.metadata.create_all()` in main.py already creates the
full Planora schema from models.py directly. This script exists only
to upgrade a database that already has the old TimeWise AI tables.
"""

from sqlalchemy import text
from database import engine

# Each entry: (SQL to run, human-readable description)
STATEMENTS = [
    # ---------- tasks ----------
    (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS difficulty VARCHAR DEFAULT 'medium';",
        "tasks.difficulty",
    ),
    (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS remaining_duration INTEGER;",
        "tasks.remaining_duration",
    ),
    (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending';",
        "tasks.status",
    ),
    (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;",
        "tasks.updated_at",
    ),
    # Backfill: remaining_duration starts equal to estimated_duration for
    # any task that doesn't have it set yet (new tasks get this at creation
    # time in crud.py going forward).
    (
        "UPDATE tasks SET remaining_duration = estimated_duration WHERE remaining_duration IS NULL;",
        "backfill tasks.remaining_duration",
    ),
    # Backfill: status should reflect the existing `completed` boolean for
    # rows that predate the status column.
    (
        "UPDATE tasks SET status = 'completed' WHERE completed = TRUE AND status = 'pending';",
        "backfill tasks.status from completed",
    ),
    (
        "UPDATE tasks SET updated_at = created_at WHERE updated_at IS NULL;",
        "backfill tasks.updated_at",
    ),

    # ---------- focus_sessions ----------
    (
        "ALTER TABLE focus_sessions ALTER COLUMN end_time DROP NOT NULL;",
        "focus_sessions.end_time now nullable (in-progress sessions)",
    ),
    (
        "ALTER TABLE focus_sessions ALTER COLUMN duration_minutes DROP NOT NULL;",
        "focus_sessions.duration_minutes now nullable (in-progress sessions)",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS active_duration INTEGER;",
        "focus_sessions.active_duration",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS idle_duration INTEGER;",
        "focus_sessions.idle_duration",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS pause_count INTEGER DEFAULT 0;",
        "focus_sessions.pause_count",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS focus_rating INTEGER;",
        "focus_sessions.focus_rating",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS engagement_rating INTEGER;",
        "focus_sessions.engagement_rating",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS goal_status VARCHAR;",
        "focus_sessions.goal_status",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS task_difficulty VARCHAR;",
        "focus_sessions.task_difficulty",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS interrupted BOOLEAN DEFAULT FALSE;",
        "focus_sessions.interrupted",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS interruption_reason VARCHAR;",
        "focus_sessions.interruption_reason",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS idle_reclassified BOOLEAN DEFAULT FALSE;",
        "focus_sessions.idle_reclassified",
    ),
    (
        "ALTER TABLE focus_sessions ADD COLUMN IF NOT EXISTS validation_status VARCHAR DEFAULT 'pending';",
        "focus_sessions.validation_status",
    ),
    # Backfill: every pre-existing session was saved only when a Pomodoro
    # block finished, with no feedback form -- but it DOES already have a
    # focus_score computed by the old scoring.py formula. We mark these
    # historical rows "valid" so existing users don't lose their history
    # for analytics/ML purposes, while all NEW sessions go through the
    # real validation flow and start "pending".
    (
        "UPDATE focus_sessions SET validation_status = 'valid' "
        "WHERE validation_status = 'pending' AND focus_score IS NOT NULL AND end_time IS NOT NULL;",
        "backfill focus_sessions.validation_status for pre-existing scored sessions",
    ),

    # ---------- predictions ----------
    (
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            task_id INTEGER REFERENCES tasks(id),
            window_start TIMESTAMP NOT NULL,
            window_end TIMESTAMP NOT NULL,
            predicted_focus_score FLOAT NOT NULL,
            source VARCHAR DEFAULT 'fallback',
            model_version INTEGER,
            created_at TIMESTAMP
        );
        """,
        "create table predictions",
    ),

    # ---------- model_versions ----------
    (
        """
        CREATE TABLE IF NOT EXISTS model_versions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            model_version INTEGER NOT NULL,
            trained_at TIMESTAMP,
            training_sample_count INTEGER NOT NULL,
            validation_metric FLOAT,
            model_status VARCHAR DEFAULT 'candidate',
            feature_version VARCHAR DEFAULT 'v1'
        );
        """,
        "create table model_versions",
    ),

    # ---------- indexes ----------
    (
        "CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks (user_id);",
        "index tasks(user_id)",
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_focus_sessions_user_id ON focus_sessions (user_id);",
        "index focus_sessions(user_id)",
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_focus_sessions_user_start ON focus_sessions (user_id, start_time);",
        "index focus_sessions(user_id, start_time)",
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_predictions_user_id ON predictions (user_id);",
        "index predictions(user_id)",
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_model_versions_user_id ON model_versions (user_id);",
        "index model_versions(user_id)",
    ),
]


def run_migration():
    with engine.begin() as conn:
        for sql, description in STATEMENTS:
            print(f"-> {description}")
            conn.execute(text(sql))
    print("\nMigration complete: TimeWise AI schema upgraded to Planora.")


if __name__ == "__main__":
    run_migration()
