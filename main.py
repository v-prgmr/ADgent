"""FastAPI entrypoint wiring application configuration and routes."""

from app.core.app import create_app

app = create_app()
