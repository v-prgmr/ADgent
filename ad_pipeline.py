"""End-to-end pipeline for scraping a site and generating ad ideas with images."""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, HttpUrl

import openai_chat
from image_service import generate_image_base64_from_prompt

SCRAPER_SCRIPT = (
    Path(__file__).resolve().parent / "lightpanda-scraper" / "hybrid-scraper.js"
)
SCRAPER_TIMEOUT_SECONDS = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "75"))
AD_IDEA_COUNT = int(os.getenv("DEFAULT_AD_IDEA_COUNT", "3"))
OPENAI_AD_MODEL = os.getenv("OPENAI_AD_MODEL")


class AdGenerationRequest(BaseModel):
    company_url: HttpUrl = Field(
        ...,
        description="Public company website to scrape for marketing context.",
        examples=["https://techeurope.io"],
    )
    additional_context: Optional[str] = Field(
        None,
        description="Any extra notes about goals, audience, offers, or constraints.",
    )


def _truncate_text(text: Optional[str], limit: int = 2500) -> str:
    if not text:
        return ""
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed
    truncated = trimmed[:limit]
    last_space = truncated.rfind(" ")
    if last_space > 200:
        truncated = truncated[:last_space]
    return truncated.strip() + " ..."


def _extract_json_blob(raw_output: str) -> str:
    candidates: list[str] = []
    depth = 0
    start_index: Optional[int] = None
    for index, char in enumerate(raw_output):
        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0 and start_index is not None:
                    candidates.append(raw_output[start_index : index + 1])
                    start_index = None

    for candidate in reversed(candidates):
        snippet = candidate.strip()
        try:
            json.loads(snippet)
            return snippet
        except json.JSONDecodeError:
            continue

    raise ValueError("Could not locate JSON payload in scraper output.")


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, count=1).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


async def _run_lightpanda_scraper(url: str) -> Dict[str, Any]:
    if not SCRAPER_SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail="Lightpanda scraper is not available on the server.",
        )

    process = await asyncio.create_subprocess_exec(
        "node",
        str(SCRAPER_SCRIPT),
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(SCRAPER_SCRIPT.parent),
        env=os.environ.copy(),
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=SCRAPER_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        raise HTTPException(
            status_code=504,
            detail="Lightpanda scraper timed out before completing.",
        )

    stdout_text = stdout.decode("utf-8", errors="ignore")
    stderr_text = stderr.decode("utf-8", errors="ignore").strip()

    if process.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=(
                "Lightpanda scraper failed."
                + (f" Details: {stderr_text}" if stderr_text else "")
            ),
        )

    try:
        json_blob = _extract_json_blob(stdout_text)
        return json.loads(json_blob)
    except (ValueError, json.JSONDecodeError) as exc:
        message = "Scraper output could not be parsed as JSON."
        if stderr_text:
            message += f" Scraper stderr: {stderr_text}"
        raise HTTPException(status_code=500, detail=f"{message} ({exc})") from exc


async def _generate_from_context(
    context: Dict[str, Any], payload: AdGenerationRequest
) -> Dict[str, Any]:
    text_excerpt = _truncate_text(context.get("textContent"))
    system_prompt = (
        "You are a senior creative strategist crafting marketing campaigns. "
        "Create distinct ad concepts tailored to the company information provided. "
        "Always respond with valid JSON matching the requested schema. "
        "Do not include Markdown, code fences, or commentary outside of the JSON response."
    )
    user_prompt = (
        f"Company URL: {context.get('sourceUrl') or str(payload.company_url)}\n"
        f"Website Title: {context.get('title') or 'Unknown'}\n"
        f"Primary website excerpt:\n{text_excerpt}\n\n"
        f"Additional context from requester:\n"
        f"{payload.additional_context or 'None provided.'}\n\n"
        f"Generate {AD_IDEA_COUNT} distinct, imaginative ad concepts. "
        "Return JSON with exactly this structure:\n"
        "{\n"
        '  "ideas": [\n'
        "    {\n"
        '      "title": "≤12 word hook capturing the concept.",\n'
        '      "description": "2-3 sentences describing the creative idea and how it ties to the company.",\n'
        '      "image_prompt": "Detailed visual direction for an illustrative hero image."\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Make each idea unique, concrete, and rooted in the supplied context."
    )

    loop = asyncio.get_running_loop()

    try:
        raw_response = await loop.run_in_executor(
            None,
            lambda: openai_chat.responses(
                user_prompt,
                system=system_prompt,
                model=OPENAI_AD_MODEL,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"OpenAI ad generation failed: {exc}"
        ) from exc

    cleaned = _strip_code_fence(raw_response)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="OpenAI returned a response that was not valid JSON.",
        ) from exc


async def generate_ad_ideas(payload: AdGenerationRequest) -> List[Dict[str, str]]:
    scraped_context = await _run_lightpanda_scraper(str(payload.company_url))
    ad_response = await _generate_from_context(scraped_context, payload)

    ad_ideas = ad_response.get("ideas")
    if not isinstance(ad_ideas, list) or not ad_ideas:
        raise HTTPException(
            status_code=502,
            detail="OpenAI response did not include any ad ideas.",
        )

    if len(ad_ideas) < AD_IDEA_COUNT:
        raise HTTPException(
            status_code=502,
            detail=f"Expected at least {AD_IDEA_COUNT} ad ideas from OpenAI.",
        )

    loop = asyncio.get_running_loop()
    results: List[Dict[str, str]] = []

    for idea in ad_ideas[:AD_IDEA_COUNT]:
        title = str(idea.get("title", "")).strip()
        description = str(idea.get("description", "")).strip()
        image_prompt = str(idea.get("image_prompt", "")).strip()

        if not (title and description and image_prompt):
            raise HTTPException(
                status_code=502,
                detail="OpenAI returned an idea missing required fields.",
            )

        try:
            image_base64 = await loop.run_in_executor(
                None, generate_image_base64_from_prompt, image_prompt
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500,
                detail=f"Image generation failed for idea '{title}': {exc}",
            ) from exc

        results.append(
            {
                "title": title,
                "description": description,
                "image": image_base64,
            }
        )

    return results


__all__ = ["AdGenerationRequest", "generate_ad_ideas"]

