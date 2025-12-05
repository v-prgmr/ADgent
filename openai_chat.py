#!/usr/bin/env python3
"""
Tiny OpenAI helper.

Import the functions you need:

    from openai_chat import chat, responses, embed
    print(chat("Tell me a joke."))

You can also run it directly:

    python openai_chat.py "Tell me a joke."
    python openai_chat.py --mode responses "Summarise this text."
    python openai_chat.py --mode embeddings "vectorise this"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable, Sequence

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError(
        "OPENAI_API_KEY environment variable not set. "
        "Export it or add it to your .env file."
    )

# One global client and a few defaults that other modules can reuse.
CLIENT = OpenAI(api_key=api_key)
DEFAULT_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-5-chat-latest")
DEFAULT_RESPONSES_MODEL = os.environ.get("OPENAI_RESPONSES_MODEL", "gpt-5-chat-latest")
DEFAULT_EMBEDDINGS_MODEL = os.environ.get("OPENAI_EMBEDDINGS_MODEL", "gpt-5-chat-latest")


def chat(prompt: str, *, system: str | None = None, model: str | None = None) -> str:
    """Send a prompt to the Chat Completions endpoint."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    result = CLIENT.chat.completions.create(
        model=model or DEFAULT_CHAT_MODEL,
        messages=messages,
    )
    return (result.choices[0].message.content or "").strip()


def responses(
    prompt: str | Iterable[dict[str, str]] | Iterable[str],
    *,
    system: str | None = None,
    model: str | None = None,
) -> str:
    """Call the Responses API and return plain text."""
    # Build message-style payload; prepend system if provided.
    if isinstance(prompt, str):
        base_messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    else:
        # Convert any iterable to a concrete list so we can prefix the system message.
        base_messages = list(prompt)  # type: ignore[arg-type]

    if system:
        payload: list[dict[str, str]] = [{"role": "system", "content": system}, *base_messages]
    else:
        payload = base_messages

    result = CLIENT.responses.create(
        model=model or DEFAULT_RESPONSES_MODEL,
        input=payload,
    )

    if hasattr(result, "output_text") and result.output_text:
        return result.output_text.strip()

    chunks: list[str] = []
    for item in getattr(result, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text and getattr(text, "value", None):
                chunks.append(text.value)
    return "\n".join(chunks).strip()


def embed(text: str | Sequence[str], *, model: str | None = None):
    """Return embeddings for a string or list of strings."""
    result = CLIENT.embeddings.create(
        model=model or DEFAULT_EMBEDDINGS_MODEL,
        input=text,
    )
    vectors = [data.embedding for data in result.data]
    if isinstance(text, str):
        return vectors[0]
    return vectors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Super simple OpenAI helper CLI.")
    parser.add_argument("prompt", nargs="*", help="Prompt text.")
    parser.add_argument(
        "--mode",
        choices=("chat", "responses", "embeddings"),
        default="chat",
        help="Which helper to call.",
    )
    parser.add_argument("--model", help="Model override.")
    parser.add_argument("--system", help="System prompt (chat/responses only).")
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.prompt:
        parser.error("You must supply a prompt.")

    text = " ".join(args.prompt)
    if args.mode == "embeddings":
        result = embed(text, model=args.model)
        print(json.dumps(result))
    elif args.mode == "responses":
        result = responses(text, model=args.model, system=args.system)
        print(result)
    else:
        result = chat(text, model=args.model, system=args.system)
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

