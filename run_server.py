"""Convenience runner to start the FastAPI service from any location."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

ROOT_DIR = Path(__file__).resolve().parent


def main() -> None:
    """Launch the Uvicorn server targeting ``main:app``.

    This wrapper sets the application directory to the repository root so the
    module can be imported even when the script is executed from another
    working directory.
    """

    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the Nano Banana API server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "ERROR: OPENAI_API_KEY is not set. Create a .env file or export the variable before running."
        )
        sys.exit(1)

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload, app_dir=str(ROOT_DIR))


if __name__ == "__main__":
    main()
