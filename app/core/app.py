"""Application factory for the FastAPI service."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import routes

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Nano Banana Image Generator",
        description="Generate and edit images using Google's Gemini 2.5 Flash Image model",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # consider restricting in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for mount_path in ("images", "generated_scenes"):
        try:
            app.mount(
                f"/{mount_path}",
                StaticFiles(directory=str(BASE_DIR / mount_path)),
                name=mount_path,
            )
        except Exception:
            # Keep parity with previous behavior of skipping missing directories.
            pass

    app.include_router(routes.router)
    return app
