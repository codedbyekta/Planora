"""
tests/conftest.py
-------------------
Shared pytest fixtures for the whole suite.

CRITICAL ORDERING: DATABASE_URL must be pointed at the TEST database
BEFORE anything imports `database.py` (directly or transitively via
`main`, `crud`, `ml.train_model`, etc.) -- those modules build a
module-level SQLAlchemy engine/SessionLocal at import time, bound to
whatever DATABASE_URL is set at that moment. `database.py` calls
python-dotenv's load_dotenv(), which never overrides an already-set
environment variable, so setting os.environ["DATABASE_URL"] here first
guarantees every module in the app -- including ml/retrain_monitor.py,
which opens its OWN database session directly rather than going through
the get_db() dependency -- talks to the test database, not a real one.

The test database defaults to postgresql://postgres:postgres@localhost:5432/planora_test
and can be overridden with DATABASE_URL_TEST in your environment or .env.
It must be a REAL, separate Postgres database (created once, e.g.
`createdb planora_test`) -- this suite creates/drops tables in it but
does not create the database itself.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()  # picks up DATABASE_URL_TEST etc. if present in backend/.env

TEST_DB_URL = os.environ.get(
    "DATABASE_URL_TEST", "postgresql://postgres:postgres@localhost:5432/planora_test"
)
os.environ["DATABASE_URL"] = TEST_DB_URL  # must happen before any app import below

import pytest
from fastapi.testclient import TestClient

import database  # noqa: E402  (import order is load-bearing, see above)
import models  # noqa: E402
import main  # noqa: E402  (this also runs Base.metadata.create_all at import time)


@pytest.fixture(scope="session", autouse=True)
def _fresh_schema():
    """Drop and recreate every table once per test run, so the suite
    always starts from a known-empty state regardless of what a
    previous run left behind. Also clears any leftover per-user model
    artifacts on disk (ml/models/*.pkl, *.json) -- those live outside
    the database and are keyed by user_id, so a stale file from a
    previous run could otherwise be silently "adopted" by a new user
    who happens to get recycled the same integer id."""
    import glob
    model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "models")
    for pattern in ("model_user_*.pkl", "model_user_*_meta.json"):
        for f in glob.glob(os.path.join(model_dir, pattern)):
            os.remove(f)

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    yield


@pytest.fixture()
def db():
    """A raw SQLAlchemy session for tests that need to assert on the
    database directly (e.g. model_versions rows) or seed data that has
    no corresponding API endpoint (synthetic historical sessions)."""
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    return TestClient(main.app)


@pytest.fixture()
def make_authed_user(client):
    """Registers + logs in a fresh user with a unique email, returns
    (user_id, auth_headers). A counter keeps emails unique across the
    many calls a single test file makes without every test needing to
    invent its own unique email."""
    counter = {"n": 0}

    def _make(prefix="user"):
        counter["n"] += 1
        email = f"{prefix}_{os.getpid()}_{counter['n']}@example.com"
        password = "testpass123"
        r = client.post("/auth/register", json={"name": prefix, "email": email, "password": password})
        assert r.status_code == 201, r.text
        user_id = r.json()["id"]
        r = client.post("/auth/login", data={"username": email, "password": password})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        return user_id, {"Authorization": f"Bearer {token}"}

    return _make
