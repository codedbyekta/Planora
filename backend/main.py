"""
main.py
-------
Entry point for the FastAPI application.

- Creates the database tables on startup (if they don't exist).
- Sets up CORS so the React frontend (running on a different port)
  can call this API.
- Registers route modules.
- Includes a simple protected /me route to test that JWT auth works
  end-to-end before we build anything else on top of it.
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base
import models
import schemas
from auth import get_current_user
from routes import auth as auth_routes
from routes import tasks as tasks_routes
from routes import sessions as sessions_routes
from routes import dashboard as dashboard_routes
from routes import analytics as analytics_routes
from routes import recommendations as recommendations_routes
from routes import predictions as predictions_routes
from routes import schedule as schedule_routes
from routes import weekly_report as weekly_report_routes

# Create all tables defined in models.py if they don't already exist.
# (For a student project this is fine. In a bigger production app
#  you'd use a migration tool like Alembic instead.)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Planora API", description="Plan Tomorrow Around You")

# Allow the Vite dev server (default port 5173) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "https://planora-phi-orpin.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(tasks_routes.router)
app.include_router(sessions_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(analytics_routes.router)
app.include_router(recommendations_routes.router)
app.include_router(predictions_routes.router)
app.include_router(schedule_routes.router)
app.include_router(weekly_report_routes.router)


@app.get("/")
def root():
    return {"message": "Planora backend is running."}


@app.get("/me", response_model=schemas.UserOut)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    """
    Simple protected route: if you can hit this and get your
    own user data back, JWT auth is working correctly.
    """
    return current_user
