"""Thin wrapper around the Gemini image API used by the ad generator."""

import base64
import os
from typing import Iterable, Union

from dotenv import load_dotenv
from google import genai
from PIL import Image

load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set")

MODEL_NAME = os.getenv("GOOGLE_IMAGE_MODEL", "gemini-2.5-flash-image-preview")

_client = genai.Client(api_key=API_KEY)


def generate_image_bytes(contents: Iterable[Union[str, Image.Image]]) -> bytes:
    """Call Gemini image model with provided contents and return raw PNG bytes."""
    response = _client.models.generate_content(
        model=MODEL_NAME,
        contents=list(contents),
    )

    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data

    raise RuntimeError("No image generated in response.")


def generate_image_base64_from_prompt(prompt: str) -> str:
    """Generate image bytes from a prompt and return them as a base64-encoded PNG string."""
    image_bytes = generate_image_bytes([prompt])
    return base64.b64encode(image_bytes).decode("utf-8")


__all__ = ["API_KEY", "MODEL_NAME", "generate_image_bytes", "generate_image_base64_from_prompt"]

