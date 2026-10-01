"""
database.py
------------
Sets up the connection to PostgreSQL using SQLAlchemy.

How it works:
1. We read the DATABASE_URL from the .env file.
2. `engine` is the object that actually talks to PostgreSQL.
3. `SessionLocal` is a factory that creates a new database session
   for every request (each request gets its own session, used, then closed).
4. `Base` is the parent class that all our models (tables) inherit from.
5. `get_db()` is a FastAPI dependency — every route that needs DB access
   will call this function to get a session, and it auto-closes when done.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Load variables from .env file into the environment
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env and fill in your PostgreSQL details."
    )

# The engine manages the actual connection pool to PostgreSQL
engine = create_engine(DATABASE_URL)

# SessionLocal is used to create individual database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class that all SQLAlchemy models will inherit from
Base = declarative_base()


def get_db():
    """
    FastAPI dependency function.
    Opens a new DB session for a request, gives it to the route,
    and closes it automatically once the request is done —
    even if an error occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
