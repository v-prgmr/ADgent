"""Router definitions for the ad-generation FastAPI service."""

import base64
import glob
import json
import mimetypes
import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from google import genai
from google.genai import types as Gtypes
from google.genai.types import GenerateVideosConfig, Image as GImage, VideoGenerationReferenceImage
from openai import AsyncOpenAI
from PIL import Image
from pydantic import BaseModel, Field

from ad_pipeline import AdGenerationRequest, generate_ad_ideas
from ffmpeg_stitched import process_scenes_and_join
from image_service import API_KEY
from tts_service import generate_all_voiceovers

# Core configuration
BASE_DIR = Path(__file__).resolve().parent.parent.parent
IMAGES_BASE = BASE_DIR / "images"
GENERATED_SCENES_BASE = BASE_DIR / "generated_scenes"
STORYBOARD_PATH = IMAGES_BASE / "generated_storyboard_12.json"
nano_banana = "gemini-2.5-flash-image"
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
CHAR_ASSET_PATH = str(IMAGES_BASE)
SCENE_ASSET_PATH = str(IMAGES_BASE)
OUTPUT_PATH = str(GENERATED_SCENES_BASE)

router = APIRouter()


def website_to_slug(website: Optional[str]) -> str:
    """Normalize website URLs into safe directory-friendly slugs."""

    if not website:
        return "default"

    cleaned = re.sub(r"^https?://", "", website.strip().lower())
    cleaned = cleaned.replace("/", "-")
    cleaned = re.sub(r"[^a-z0-9._-]", "-", cleaned)
    cleaned = cleaned.strip("-._")
    return cleaned or "default"


def scene_image_path(slug: str, scene_index: int) -> Path:
    """Return the target path for a generated scene image for a given website slug."""

    return GENERATED_SCENES_BASE / slug / "images" / f"scene{scene_index}.png"


def public_url_for_path(file_path: Path) -> str:
    """Convert an absolute file path into an API-served public URL."""

    try:
        relative_path = file_path.resolve().relative_to(BASE_DIR)
        return "/" + relative_path.as_posix()
    except Exception:
        return str(file_path)


def storyboard_path_for_slug(slug: str) -> Path:
    """Return the storyboard storage path for the given website slug."""

    return IMAGES_BASE / slug / "generated_storyboard.json"


def safe_slug(slug: str) -> str:
    """Sanitize slug inputs to prevent directory traversal."""

    return slug.strip().strip("/\\")

# Serve only the final video file explicitly (and not other root static files)
@router.get("/final_video.mp4")
async def serve_final_video():
    video_path = BASE_DIR / "final_video.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="final_video.mp4 not found")
    return FileResponse(path=str(video_path), media_type="video/mp4", filename="final_video.mp4")
# Allowed image formats
ALLOWED_FORMATS = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# veo3.configure(api_key=os.getenv("GOOGLE_API_KEY"))

@router.post("/generate-ad-ideas")
async def generate_ad_ideas_endpoint(payload: AdGenerationRequest):
    """Scrape the company website and generate creative ad concepts."""
    return await generate_ad_ideas(payload)

IMAGES_DIR = IMAGES_BASE
ASSET_NAME_RE = re.compile(r"^char_asset(\d+)\.(?:png|jpg|jpeg|webp)$", re.IGNORECASE)

# --- Utility: Load uploaded image as PIL.Image ---
async def _load_pil_image(upload_file: UploadFile) -> Image.Image:
    if upload_file.content_type not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail=f"Invalid file format. Allowed: {ALLOWED_FORMATS}")
    data = await upload_file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File size exceeds {MAX_FILE_SIZE / (1024 * 1024)}MB limit")
    try:
        return Image.open(BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load image: {str(e)}")
def _next_char_asset_index() -> int:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    max_idx = 0
    for entry in IMAGES_DIR.iterdir():
        if not entry.is_file():
            continue
        match = ASSET_NAME_RE.match(entry.name)
        if match:
            try:
                idx = int(match.group(1))
                if idx > max_idx:
                    max_idx = idx
            except ValueError:
                continue
    return max_idx + 1

@router.post("/upload-char-asset")
async def upload_char_asset(image: UploadFile = File(...)):
    """
    Upload an image and save it to ./images as char_assetX.png where X increments.
    Returns the saved filename and relative path.
    """
    pil_image = await _load_pil_image(image)
    next_idx = _next_char_asset_index()
    filename = f"char_asset{next_idx}.png"
    file_path = IMAGES_DIR / filename

    try:
        pil_image.save(str(file_path), format="PNG")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image: {e}")

    return {
        "success": True,
        "filename": filename,
        "path": f"images/{filename}",
    }


async def validate_and_load_image(file: UploadFile) -> Image.Image:
    """Validate and load an uploaded image file."""
    # Keep this light wrapper to share the same validation logic as asset uploads.
    return await _load_pil_image(file)


openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# --- Enhanced Character Tracking ---
async def analyze_character_usage(scenes: List[dict]) -> Dict[int, Dict[str, any]]:
    """
    Analyze all scenes to identify characters and which scenes they appear in.
    Returns a mapping of scene_index -> {should_include_char, reference_scenes}
    """

    # First pass: Identify all characters and their mentions across scenes
    character_mentions = await identify_characters_across_scenes(scenes)

    # Second pass: For each scene, determine if character should be included
    # and which previous scenes to reference for consistency
    scene_character_info = {}

    for i, scene in enumerate(scenes):
        scene_description = scene.get("scene_description", "")

        # Check if main character should appear in this scene
        include_main_char = await should_include_character(scene_description)

        # Check for references to previously seen characters
        reference_scenes = await find_character_reference_scenes(
            current_scene_idx=i,
            current_description=scene_description,
            all_scenes=scenes,
            character_mentions=character_mentions
        )

        scene_character_info[i] = {
            "include_main_character": include_main_char,
            "reference_scenes": reference_scenes,  # List of scene indices to use as reference
            "characters_present": character_mentions.get(i, [])
        }

    return scene_character_info


async def identify_characters_across_scenes(scenes: List[dict]) -> Dict[int, List[str]]:
    """
    Identify all characters mentioned across all scenes.
    Returns: {scene_index: [list of characters mentioned]}
    """

    all_descriptions = "\n\n".join([
        f"Scene {i + 1}: {scene.get('scene_description', '')}"
        for i, scene in enumerate(scenes)
    ])

    prompt = f"""Analyze these scene descriptions and identify all characters mentioned.
For each scene, list the characters that appear or are referenced.
Pay special attention to:
- Direct mentions (e.g., "the speaker", "a woman", "the scientist")
- Indirect references (e.g., "cut back to them", "she returns", "he continues")
- Pronouns that refer to previously introduced characters

Respond in JSON format:
{{
  "scenes": [
    {{"scene_number": 1, "characters": ["the speaker", "audience members"]}},
    {{"scene_number": 2, "characters": []}},
    ...
  ],
  "character_tracking": {{
    "the speaker": [1, 4, 7],  // scenes where this character appears
    "the scientist": [2, 3, 5]
  }}
}}

Scenes:
{all_descriptions}"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        # Convert to dict mapping scene_index -> list of characters
        character_mentions = {}
        for scene_info in result.get("scenes", []):
            scene_idx = scene_info["scene_number"] - 1  # Convert to 0-indexed
            character_mentions[scene_idx] = scene_info.get("characters", [])

        return character_mentions

    except Exception as e:
        print(f"⚠️ Error analyzing character usage: {str(e)}")
        # Fallback: return empty dict
        return {}


async def find_character_reference_scenes(
        current_scene_idx: int,
        current_description: str,
        all_scenes: List[dict],
        character_mentions: Dict[int, List[str]]
) -> List[int]:
    """
    For a given scene, find which previous scenes should be used as reference
    to maintain character consistency.
    Returns: List of scene indices (0-based) that should be used as reference images.
    """

    if current_scene_idx == 0:
        return []  # First scene has no previous references

    # Build context of previous scenes
    previous_context = "\n".join([
        f"Scene {i + 1}: {all_scenes[i].get('scene_description', '')} | Characters: {character_mentions.get(i, [])}"
        for i in range(current_scene_idx)
    ])

    current_characters = character_mentions.get(current_scene_idx, [])

    prompt = f"""Given the current scene and previous scenes, identify which PREVIOUS scenes should be used as visual reference to maintain character consistency.

Current Scene (Scene {current_scene_idx + 1}):
Description: {current_description}
Characters present: {current_characters}

Previous Scenes:
{previous_context}

Analyze if the current scene references or shows characters that appeared in previous scenes.
Look for:
1. Explicit callbacks ("cut back to the speaker", "return to the scientist")
2. Same character continuing their action
3. Characters referenced by pronouns

Respond in JSON format with the scene numbers (1-indexed) that should be used as reference:
{{
  "reference_scenes": [1, 4],  // List of scene numbers to reference, or empty list []
  "reasoning": "Scene 4 shows 'the speaker' who first appeared in scene 1"
}}

If no character consistency is needed, return an empty list."""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)
        reference_scene_numbers = result.get("reference_scenes", [])

        # Convert to 0-indexed and ensure they're valid
        reference_indices = [
            num - 1 for num in reference_scene_numbers
            if isinstance(num, int) and 0 < num <= current_scene_idx
        ]

        if reference_indices:
            print(f"📎 Scene {current_scene_idx + 1} references scenes: {[i + 1 for i in reference_indices]}")
            print(f"   Reasoning: {result.get('reasoning', 'N/A')}")

        return reference_indices

    except Exception as e:
        print(f"⚠️ Error finding reference scenes for scene {current_scene_idx + 1}: {str(e)}")
        return []


async def generate_scene_image(
    scene_index: int,
    scene_description: str,
    all_scenes: List[dict],
    scene_character_info: Dict[int, Dict[str, any]],
    slug: str = "default",
):
    """
    Generate scene image with intelligent character consistency tracking.

    Args:
        scene_index: Current scene number (1-indexed)
        scene_description: Description of the scene
        all_scenes: List of all scene objects
        scene_character_info: Character tracking info from analyze_character_usage()
    """
    print(f"\n🎨 [generate_scene_image] Generating image for scene {scene_index}")
    content_parts = []

    # Get character info for this scene (convert to 0-indexed for dict lookup)
    current_scene_info = scene_character_info.get(scene_index - 1, {})
    include_main_char = current_scene_info.get("include_main_character", False)
    reference_scenes = current_scene_info.get("reference_scenes", [])

    print(f"👤 [generate_scene_image] Main character inclusion: {include_main_char}")
    print(f"📎 [generate_scene_image] Character reference scenes: {[i + 1 for i in reference_scenes]}")

    # Add main character assets if needed
    if include_main_char:
        char_paths = glob.glob(os.path.join(CHAR_ASSET_PATH, "char_asset*.png"))
        for char_path in char_paths:
            with Image.open(char_path) as char_img:
                content_parts.append(char_img.copy())
        print(f"✅ [generate_scene_image] Added {len(char_paths)} main character reference images")

    # Add character consistency reference scenes (if any were identified by AI)
    for ref_scene_idx in reference_scenes:
        ref_scene_num = ref_scene_idx + 1  # Convert to 1-indexed
        scene_path = scene_image_path(slug, ref_scene_num)
        if scene_path.exists():
            print(f"📁 [generate_scene_image] Adding character reference: scene{ref_scene_num}.png")
            with Image.open(scene_path) as img:
                content_parts.append(img.copy())
        else:
            print(f"⚠️ [generate_scene_image] Character reference not found: scene{ref_scene_num}.png")

        # 🎯 Limit total reference images to avoid IMAGE_OTHER error
        MAX_REFERENCE_IMAGES = 2  # Adjust this value (2-3 works best)
        total_refs = len(content_parts)

        # Add last two previous scenes for general visual consistency
        recent_scene_indices = [scene_index - 1, scene_index - 2]

        for idx in recent_scene_indices:
            # Check if we've hit the limit
            if total_refs >= MAX_REFERENCE_IMAGES:
                print(
                    f"⚠️ [generate_scene_image] Max reference limit reached ({MAX_REFERENCE_IMAGES}), skipping scene {idx}")
                break

            # Skip if already added as character reference
            if (idx - 1) in reference_scenes:
                print(f"ℹ️ [generate_scene_image] Scene {idx} already added as character reference, skipping duplicate")
                continue

            if idx > 0:
                scene_path = scene_image_path(slug, idx)
                if scene_path.exists():
                    print(f"📁 [generate_scene_image] Adding previous scene for style continuity: scene{idx}.png")
                    with Image.open(scene_path) as img:
                        content_parts.append(img.copy())
                        total_refs += 1  # Increment counter
                else:
                    print(f"ℹ️ [generate_scene_image] No reference found for scene {idx}")

        print(f"📊 [generate_scene_image] Total reference images: {len(content_parts)}")

    # Build enhanced prompt with character consistency instructions
    prompt_parts = [
        "Generate a cinematic 16:9 widescreen PNG image depicting the scene below with consistent lighting and style."
    ]

    if include_main_char:
        prompt_parts.append("Use the main character reference images to maintain character appearance consistency.")

    if reference_scenes:
        ref_scene_nums = [i + 1 for i in reference_scenes]
        prompt_parts.append(
            f"IMPORTANT: Maintain visual consistency with characters from scene(s) {ref_scene_nums}. "
            f"The characters in this scene should match their appearance in the reference images provided."
        )

    prompt_parts.append(
        "Use all reference images for visual style consistency, but create the new image in 16:9 aspect ratio."
    )
    prompt_parts.append(f"Scene description: {scene_description}")

    prompt_intro = " ".join(prompt_parts)

    try:
        print(f"📊 [generate_scene_image] Preparing {len(content_parts)} image references")
        for i, img in enumerate(content_parts):
            print(f"   • Ref[{i}] type={type(img)}, size={getattr(img, 'size', 'unknown')}")

        if content_parts:
            parts = [pil_to_part(img) for img in content_parts]
        else:
            print("ℹ️ [generate_scene_image] No image references provided. Using text-only prompt.")
            parts = []

        print(f"🧠 [generate_scene_image] Sending request to Gemini model: {nano_banana}")

        response = client.models.generate_content(
            model=nano_banana,
            contents=[
                *parts,
                prompt_intro,
            ],
            config=Gtypes.GenerateContentConfig(
                image_config=Gtypes.ImageConfig(
                    aspect_ratio="16:9"
                )
            )
        )
        print(f"📨 [generate_scene_image] Gemini response received successfully")

        if not response.candidates or len(response.candidates) == 0:
            print("❌ [generate_scene_image] No candidates returned from Gemini response")
            raise HTTPException(
                status_code=500,
                detail=f"No candidates in response. Response: {response}"
            )

        candidate = response.candidates[0]

        # Check finish_reason for specific errors
        if candidate.finish_reason and candidate.finish_reason.name != 'STOP':
            finish_reason = candidate.finish_reason.name
            print(f"⚠️ [generate_scene_image] Generation stopped with reason: {finish_reason}")

            if finish_reason == 'IMAGE_OTHER':
                # Try again without reference images
                print(f"🔄 [generate_scene_image] Retrying without reference images...")
                response = client.models.generate_content(
                    model=nano_banana,
                    contents=prompt_intro,
                    config=Gtypes.GenerateContentConfig(
                        image_config=Gtypes.ImageConfig(
                            aspect_ratio="16:9"
                        )
                    )
                )
                if response.candidates and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Image generation failed with reason: {finish_reason}"
                    )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Image generation stopped with reason: {finish_reason}"
                )
                # Check finish_reason for specific errors
        if candidate.finish_reason and candidate.finish_reason.name != 'STOP':
            finish_reason = candidate.finish_reason.name
            print(f"⚠️ [generate_scene_image] Generation stopped with reason: {finish_reason}")

            if finish_reason == 'IMAGE_OTHER':
                # Progressive fallback strategy
                print(f"🔄 [generate_scene_image] Attempting progressive fallback...")

                # Strategy 1: Try with only the most recent scene (no character refs)
                if scene_index > 1:
                    print(f"   Strategy 1: Using only most recent scene (scene{scene_index - 1})")
                    fallback_parts = []
                    recent_scene_path = scene_image_path(slug, scene_index - 1)

                    if recent_scene_path.exists():
                        with Image.open(recent_scene_path) as img:
                            fallback_parts.append(pil_to_part(img.copy()))

                        try:
                            response = client.models.generate_content(
                                model=nano_banana,
                                contents=[*fallback_parts, prompt_intro],
                                config=Gtypes.GenerateContentConfig(
                                    image_config=Gtypes.ImageConfig(aspect_ratio="16:9")
                                )
                            )

                            if response.candidates and len(response.candidates) > 0:
                                candidate = response.candidates[0]
                                if candidate.finish_reason and candidate.finish_reason.name == 'STOP':
                                    print("   ✅ Strategy 1 succeeded!")
                                else:
                                    print(f"   ❌ Strategy 1 failed: {candidate.finish_reason.name}")
                        except Exception as e:
                            print(f"   ❌ Strategy 1 exception: {str(e)}")

                # Strategy 2: Try with only character reference (if available)
                if candidate.finish_reason.name != 'STOP' and reference_scenes:
                    print(f"   Strategy 2: Using only character reference scene")
                    fallback_parts = []
                    char_ref_idx = reference_scenes[0]
                    char_ref_path = scene_image_path(slug, char_ref_idx + 1)

                    if char_ref_path.exists():
                        with Image.open(char_ref_path) as img:
                            fallback_parts.append(pil_to_part(img.copy()))

                        try:
                            response = client.models.generate_content(
                                model=nano_banana,
                                contents=[*fallback_parts, prompt_intro],
                                config=Gtypes.GenerateContentConfig(
                                    image_config=Gtypes.ImageConfig(aspect_ratio="16:9")
                                )
                            )

                            if response.candidates and len(response.candidates) > 0:
                                candidate = response.candidates[0]
                                if candidate.finish_reason and candidate.finish_reason.name == 'STOP':
                                    print("   ✅ Strategy 2 succeeded!")
                                else:
                                    print(f"   ❌ Strategy 2 failed: {candidate.finish_reason.name}")
                        except Exception as e:
                            print(f"   ❌ Strategy 2 exception: {str(e)}")

                # Strategy 3: Last resort - no reference images
                if candidate.finish_reason.name != 'STOP':
                    print(f"   Strategy 3: No reference images (last resort)")
                    try:
                        response = client.models.generate_content(
                            model=nano_banana,
                            contents=prompt_intro,
                            config=Gtypes.GenerateContentConfig(
                                image_config=Gtypes.ImageConfig(aspect_ratio="16:9")
                            )
                        )

                        if response.candidates and len(response.candidates) > 0:
                            candidate = response.candidates[0]
                            if candidate.finish_reason and candidate.finish_reason.name == 'STOP':
                                print("   ✅ Strategy 3 succeeded!")
                            else:
                                print(f"   ❌ Strategy 3 failed: {candidate.finish_reason.name}")
                                raise HTTPException(
                                    status_code=500,
                                    detail=f"All fallback strategies failed. Last reason: {candidate.finish_reason.name}"
                                )
                    except Exception as e:
                        print(f"   ❌ Strategy 3 exception: {str(e)}")
                        raise HTTPException(
                            status_code=500,
                            detail=f"Image generation failed completely: {str(e)}"
                        )
            else:
                # Non-IMAGE_OTHER errors
                raise HTTPException(
                    status_code=500,
                    detail=f"Image generation stopped with reason: {finish_reason}"
                )
        print(f"📄 [generate_scene_image] Extracting content from candidate...")

        if not hasattr(candidate, 'content') or not candidate.content:
            print("❌ [generate_scene_image] No content in candidate")
            raise HTTPException(
                status_code=500,
                detail=f"No content in candidate. Candidate: {candidate}"
            )

        if not hasattr(candidate.content, 'parts') or not candidate.content.parts:
            print("❌ [generate_scene_image] No parts in candidate content")
            raise HTTPException(
                status_code=500,
                detail=f"No parts in content. Content: {candidate.content}"
            )

        image_bytes = None
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                if hasattr(part.inline_data, "data") and part.inline_data.data:
                    image_bytes = part.inline_data.data
                    print(f"✅ [generate_scene_image] Found inline image data in response")
                    break

        if not image_bytes:
            print("❌ [generate_scene_image] No inline image data found in response parts")
            raise HTTPException(
                status_code=500,
                detail=f"No image generated in response. Parts: {candidate.content.parts}"
            )

        out_path = scene_image_path(slug, scene_index)
        scene_path = IMAGES_BASE / slug / "images" / f"scene{scene_index}.png"

        print(f"💾 [generate_scene_image] Saving generated scene to {out_path} and {scene_path}")
        for path in [out_path, scene_path]:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(image_bytes)

        print(f"✅ [generate_scene_image] Scene {scene_index} image saved successfully")

        return {
            "scene_index": scene_index,
            "included_main_char": include_main_char,
            "character_reference_scenes": [i + 1 for i in reference_scenes],
            "output_path": str(out_path),
            "scene_asset_path": str(scene_path)
        }

    except Exception as e:
        print(f"❌ [generate_scene_image] Gemini generation failed for scene {scene_index}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gemini generation failed: {str(e)}")


# --- Updated endpoint to use character consistency ---
@router.post("/generate-storyboard-images")
async def generate_all_storyboard_images():
    """Generate images for all scenes with intelligent character consistency tracking."""

    # Load storyboard JSON
    json_path = STORYBOARD_PATH
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"Storyboard JSON not found: {json_path}")

    try:
        with open(json_path, "r") as f:
            scenes = json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    if not isinstance(scenes, list):
        raise HTTPException(status_code=400, detail="JSON must contain an array of scenes")

    # 🎯 Analyze character usage across ALL scenes first
    print(f"\n🔍 Analyzing character consistency across {len(scenes)} scenes...")
    scene_character_info = await analyze_character_usage(scenes)
    print(f"✅ Character analysis complete\n")

    results = []

    # Generate images for each scene
    for i, scene in enumerate(scenes, start=1):
        try:
            scene_description = scene.get("scene_description", "")

            result = await generate_scene_image(
                scene_index=i,
                scene_description=scene_description,
                all_scenes=scenes,
                scene_character_info=scene_character_info
            )

            results.append({
                "scene": i,
                "status": "success",
                **result
            })

        except Exception as e:
            print(f"❌ Error generating scene {i}: {str(e)}")
            results.append({
                "scene": i,
                "status": "error",
                "message": str(e)
            })

    # Summary
    successful = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "error")

    return JSONResponse(content={
        "total_scenes": len(scenes),
        "successful": successful,
        "failed": failed,
        "results": results,
        "note": "Generated with intelligent character consistency tracking"
    })

# --- Utility: Ask OpenAI whether to include character ---
async def should_include_character(scene_description: str) -> bool:
    """Ask OpenAI whether character should appear in the given scene."""
    prompt = (
        f"Based on this scene description, should the main character appear visually in the scene? "
        f"Respond strictly with 'yes' or 'no'.\n\nScene: {scene_description}"
    )

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        answer = response.choices[0].message.content.strip().lower()
        return answer.startswith("y")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI call failed: {str(e)}")


def pil_to_part(image: Image.Image) -> Gtypes.Part:
    if image is None:
        print("⚠️ [pil_to_part] Received None instead of a valid image!")
        raise ValueError("Cannot convert NoneType to Part")

    buf = BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return Gtypes.Part.from_bytes(data=buf.read(), mime_type="image/png")


async def dup_generate_scene_image(scene_index: int, scene_description: str, slug: str = "default"):
    print(f"\n🎨 [generate_scene_image] Generating image for scene {scene_index}")
    content_parts = []

    include_char = await should_include_character(scene_description)
    print(f"👤 [generate_scene_image] Character inclusion: {include_char}")

    if include_char:
        char_paths = glob.glob(os.path.join(CHAR_ASSET_PATH, "char_asset*.png"))
        for char_path in char_paths:
            with Image.open(char_path) as char_img:
                content_parts.append(char_img.copy())

    # ⭐ Add last two previous scenes as references
    recent_scene_indices = [scene_index - 1, scene_index - 2]

    for idx in recent_scene_indices:
        if idx > 0:
            scene_path = scene_image_path(slug, idx)
            if scene_path.exists():
                print(f"📁 [generate_scene_image] Adding previous scene reference: scene{idx}.png")
                with Image.open(scene_path) as img:
                    content_parts.append(img.copy())
            else:
                print(f"ℹ️ [generate_scene_image] No reference found for scene {idx}")

    prompt_intro = (
        "Generate a cinematic 16:9 widescreen PNG image depicting the scene below with consistent lighting and style. "
        "Use the reference images for character consistency and visual style, but create the image in 16:9 aspect ratio.\n"
        f"Scene description: {scene_description}"
    )

    try:
        print(f"📊 [generate_scene_image] Preparing {len(content_parts)} image references")
        for i, img in enumerate(content_parts):
            print(f"   • Ref[{i}] type={type(img)}, size={getattr(img, 'size', 'unknown')}")

        if content_parts:
            parts = [pil_to_part(img) for img in content_parts]
        else:
            print("ℹ️ [generate_scene_image] No image references provided. Using text-only prompt.")
            parts = []

        print(f"🧠 [generate_scene_image] Sending request to Gemini model: {nano_banana}")

        response = client.models.generate_content(
            model=nano_banana,
            contents=[
                *parts,
                prompt_intro,
            ],
            config=Gtypes.GenerateContentConfig(
                image_config=Gtypes.ImageConfig(
                    aspect_ratio="16:9"
                )
            )
        )
        print(f"📨 [generate_scene_image] Gemini response received successfully")

        if not response.candidates or len(response.candidates) == 0:
            print("❌ [generate_scene_image] No candidates returned from Gemini response")
            raise HTTPException(
                status_code=500,
                detail=f"No candidates in response. Response: {response}"
            )

        candidate = response.candidates[0]

        # Check finish_reason for specific errors
        if candidate.finish_reason and candidate.finish_reason.name != 'STOP':
            finish_reason = candidate.finish_reason.name
            print(f"⚠️ [generate_scene_image] Generation stopped with reason: {finish_reason}")

            if finish_reason == 'IMAGE_OTHER':
                # Try again without reference images
                print(f"🔄 [generate_scene_image] Retrying without reference images...")
                response = client.models.generate_content(
                    model=nano_banana,
                    contents=prompt_intro,
                    config=Gtypes.GenerateContentConfig(
                        image_config=Gtypes.ImageConfig(
                            aspect_ratio="16:9"
                        )
                    )
                )
                if response.candidates and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Image generation failed with reason: {finish_reason}"
                    )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Image generation stopped with reason: {finish_reason}"
                )

        print(f"📄 [generate_scene_image] Extracting content from candidate...")

        if not hasattr(candidate, 'content') or not candidate.content:
            print("❌ [generate_scene_image] No content in candidate")
            raise HTTPException(
                status_code=500,
                detail=f"No content in candidate. Candidate: {candidate}"
            )

        if not hasattr(candidate.content, 'parts') or not candidate.content.parts:
            print("❌ [generate_scene_image] No parts in candidate content")
            raise HTTPException(
                status_code=500,
                detail=f"No parts in content. Content: {candidate.content}"
            )

        image_bytes = None
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                if hasattr(part.inline_data, "data") and part.inline_data.data:
                    image_bytes = part.inline_data.data
                    print(f"✅ [generate_scene_image] Found inline image data in response")
                    break

        if not image_bytes:
            print("❌ [generate_scene_image] No inline image data found in response parts")
            raise HTTPException(
                status_code=500,
                detail=f"No image generated in response. Parts: {candidate.content.parts}"
            )

        out_path = scene_image_path(slug, scene_index)
        scene_path = IMAGES_BASE / slug / "images" / f"scene{scene_index}.png"

        print(f"💾 [generate_scene_image] Saving generated scene to {out_path} and {scene_path}")
        for path in [out_path, scene_path]:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(image_bytes)

        print(f"✅ [generate_scene_image] Scene {scene_index} image saved successfully")

        return {
            "scene_index": scene_index,
            "included_char": include_char,
            "output_path": str(out_path),
            "scene_asset_path": str(scene_path)
        }

    except Exception as e:
        print(f"❌ [generate_scene_image] Gemini generation failed for scene {scene_index}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gemini generation failed: {str(e)}")

# --- Endpoint ---
class GenerateScenesRequest(BaseModel):
    storyboard: Optional[List[dict]] = None


@router.post("/generate-scenes")
async def generate_scenes(
    payload: GenerateScenesRequest,
    website: Optional[str] = Query(None, description="Website URL used to scope assets"),
):
    """
    Process a storyboard JSON and generate corresponding scene images.
    JSON should be an array of:
    [
        {"scene_description": "...", "voice_over_text": "..."},
        ...
    ]
    """
    print("🟢 [generate_scenes] Called /generate-scenes endpoint")

    try:
        slug = website_to_slug(website)

        if payload.storyboard:
            data = payload.storyboard
            print(f"📝 [generate_scenes] Using storyboard provided in request body for slug '{slug}'")
            target_storyboard_path = storyboard_path_for_slug(slug)
            target_storyboard_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_storyboard_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            candidate_paths = [storyboard_path_for_slug(slug), STORYBOARD_PATH]
            json_path = next((path for path in candidate_paths if path.exists()), None)
            if not json_path:
                raise FileNotFoundError("Storyboard JSON not found for generation")

            print(f"📂 [generate_scenes] Attempting to open storyboard JSON at: {json_path}")
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"✅ [generate_scenes] Successfully loaded JSON file with {len(data)} entries")

        if not isinstance(data, list):
            raise ValueError("JSON root must be an array")

        # 🎯 Analyze character usage across ALL scenes first
        print(f"\n🔍 Analyzing character consistency across {len(data)} scenes...")
        scene_character_info = await analyze_character_usage(data)
        print(f"✅ Character analysis complete\n")

        results = []
        print("🔄 [generate_scenes] Starting scene generation loop")

        for i, entry in enumerate(data, start=1):
            print(f"🎬 [generate_scenes] Processing scene index: {i}")
            scene_desc = entry.get("scene_description")

            if not scene_desc:
                print(f"⚠️ [generate_scenes] Skipping scene {i}: Missing 'scene_description'")
                continue

            print(f"📝 [generate_scenes] Scene {i} description: {scene_desc[:100]}...")

            result = await generate_scene_image(
                scene_index=i,
                scene_description=scene_desc,
                all_scenes=data,
                scene_character_info=scene_character_info,
                slug=slug,
            )

            print(f"✅ [generate_scenes] Scene {i} generation completed: {result}")
            results.append(result)

        print(f"🏁 [generate_scenes] All scenes processed. Total generated: {len(results)}")

        return {"success": True, "scenes_generated": len(results), "details": results}

    except Exception as e:
        print(f"❌ [generate_scenes] Exception occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Storyboard processing failed: {str(e)}")


@router.post("/regenerate-scene")
async def regenerate_scene(payload: dict, website: Optional[str] = Query(None)):
    """
    Regenerate a single scene image with a custom prompt.
    Expected JSON body: { "scene_index": number, "prompt": string }
    """
    try:
        scene_index = int(payload.get("scene_index"))
        prompt = str(payload.get("prompt") or "").strip()
        if scene_index <= 0:
            raise ValueError("scene_index must be >= 1")
        if not prompt:
            raise ValueError("prompt is required")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # Load all scenes for character consistency analysis
    try:
        slug = website_to_slug(website)
        json_path = storyboard_path_for_slug(slug)
        if not json_path.exists():
            json_path = STORYBOARD_PATH
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Analyze character usage
        scene_character_info = await analyze_character_usage(data)

        result = await generate_scene_image(
            scene_index=scene_index,
            scene_description=prompt,
            all_scenes=data,
            scene_character_info=scene_character_info,
            slug=slug,
        )

        return {"success": True, "detail": result}

    except FileNotFoundError:
        # Fallback: Use dup_generate_scene_image if storyboard doesn't exist
        print(f"⚠️ Storyboard not found, using fallback generation without character tracking")
        result = await dup_generate_scene_image(scene_index, prompt, slug=slug)
        return {"success": True, "detail": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scene regeneration failed: {str(e)}")


@router.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Nano Banana Image Generator",
        "model": MODEL_NAME
    }


@router.get("/health")
async def health_check():
    """Detailed health check."""
    try:
        # Verify API key is set
        has_api_key = bool(API_KEY)
        return {
            "status": "healthy",
            "api_key_configured": has_api_key,
            "model": MODEL_NAME
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@router.post("/generate-story-board")
async def generate_storyboard(
        selected_idea: str = Query(..., description="Story summary or idea to inject into the prompt"),
        website: Optional[str] = Query(None, description="Website URL used to scope assets"),

):
    """
    Generate storyboard for scenes using OpenAI API.

    - **prompt**: Text prompt for generation
    """
    try:
        from openai import OpenAI
        with open("generate_story_board_prompt.txt", encoding="utf-8") as f:
            prompt = f.read()

        prompt = prompt.replace("{insert story summary here}", selected_idea)

        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        generated_text = response.choices[0].message.content
        # Parse output as JSON
        try:
            storyboard_data = json.loads(generated_text)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Model output is not valid JSON: {str(e)}"
            )

        # Save parsed JSON (pretty-printed)
        slug = website_to_slug(website)
        slugged_path = storyboard_path_for_slug(slug)
        slugged_path.parent.mkdir(parents=True, exist_ok=True)

        with open(slugged_path, "w", encoding="utf-8") as f:
            json.dump(storyboard_data, f, indent=2, ensure_ascii=False)

        # Maintain legacy default path for backward compatibility
        STORYBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STORYBOARD_PATH, "w", encoding="utf-8") as f:
            json.dump(storyboard_data, f, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "prompt": prompt,
            "generated_text": generated_text,
            "model": "gpt-4o"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Text generation failed: {str(e)}"
        )

# Create video output directory
VIDEO_DIR = GENERATED_SCENES_BASE
VIDEO_DIR.mkdir(exist_ok=True)


def existing_scene_videos(slug: str) -> List[dict]:
    """Return metadata for any locally stored scene videos for the slug."""

    videos: List[dict] = []
    video_root = VIDEO_DIR / slug / "video"
    if not video_root.exists():
        return videos

    for video_file in sorted(video_root.glob("scene*.mp4")):
        scene_match = re.match(r"scene(\d+)", video_file.stem)
        scene_num = int(scene_match.group(1)) if scene_match else None

        videos.append({
            "scene": scene_num,
            "status": "existing",
            "output_path": str(video_file),
            "public_url": public_url_for_path(video_file),
            "description": "Existing scene video",
            "voice_over": "",
        })

    return videos


class GenerateRequest(BaseModel):
    """Payload specifying the storyboard file path used for generation."""

    json_file: str = str(STORYBOARD_PATH)


@router.post("/generate-videos")
async def generate_veo3_videos(
    website: Optional[str] = Query(None, description="Website URL used to scope assets"),
):
    """Generate Veo 3 videos for all storyboard scenes."""

    slug = website_to_slug(website)

    # Load storyboard JSON
    json_path = storyboard_path_for_slug(slug)
    if not json_path.exists():
        json_path = STORYBOARD_PATH
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"Storyboard JSON not found: {json_path}")

    try:
        with open(json_path, "r") as f:
            scenes = json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    if not isinstance(scenes, list):
        raise HTTPException(status_code=400, detail="JSON must contain an array of scenes")

    results: List[dict] = []
    fallback_existing = existing_scene_videos(slug)

    try:
        # Loop through scenes
        for i, scene in enumerate(scenes, start=1):
            try:
                print(f"\n{'=' * 60}")
                print(f"Processing Scene {i}/{len(scenes)}")
                print(f"{'=' * 60}")

                if "scene_description" not in scene:
                    results.append({"scene": i, "status": "error", "message": "Missing scene_description"})
                    continue

                image_path = scene_image_path(slug, i)
                if not image_path.exists():
                    results.append({"scene": i, "status": "error", "message": f"Missing image: {image_path}"})
                    continue

                print(f"Loading reference image: {image_path}")

                # --- Load image as bytes ---
                with open(image_path, "rb") as img_file:
                    image_bytes = img_file.read()

                mime_type, _ = mimetypes.guess_type(str(image_path))
                if not mime_type:
                    mime_type = "image/png"

                # ✅ Correctly create reference image
                reference_image = VideoGenerationReferenceImage(
                    image=GImage(
                        image_bytes=image_bytes,
                        mime_type=mime_type
                    ),
                    reference_type="asset"
                )

                prompt_text = scene["scene_description"]
                print(f"🎬 Generating video with prompt: {prompt_text[:100]}...")

                # --- Generate video ---
                operation = client.models.generate_videos(
                    model="veo-3.1-generate-preview",
                    prompt="generate a video from the reference image following the prompt: " + prompt_text,
                    config=GenerateVideosConfig(
                        reference_images=[reference_image],
                        aspect_ratio="16:9",
                        # output_gcs_uri=output_gcs_uri,
                    ),
                )

                # --- Poll until completion ---
                print("⌛ Waiting for video generation to complete...")
                while not operation.done:
                    time.sleep(10)
                    operation = client.operations.get(operation)
                    print("Still processing...")

                print("📥 Downloading video...")
                video = operation.response.generated_videos[0]
                client.files.download(file=video.video)

                output_path = VIDEO_DIR / slug / "video" / f"scene{i}.mp4"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                video.video.save(str(output_path))

                print(f"✅ Video saved to {output_path}")

                results.append({
                    "scene": i,
                    "status": "success",
                    "output_path": str(output_path),
                    "public_url": public_url_for_path(output_path),
                    "description": prompt_text[:100] + "..." if len(prompt_text) > 100 else prompt_text,
                    "voice_over": scene.get("voice_over_text", "")
                })

            except Exception as e:
                print(f"✗ Error processing scene {i}: {str(e)}")
                results.append({"scene": i, "status": "error", "message": str(e)})
    except Exception as exc:
        if fallback_existing:
            results = fallback_existing
        else:
            raise HTTPException(status_code=500, detail=f"Video generation failed: {exc}")

    playable_results = [r for r in results if r.get("status") in {"success", "existing"}]
    if not playable_results and fallback_existing:
        results = fallback_existing
        playable_results = fallback_existing

    existing_count = sum(1 for r in results if r.get("status") == "existing")
    return JSONResponse(content={
        "total_scenes": len(scenes),
        "successful": sum(1 for r in results if r["status"] == "success") + existing_count,
        "existing": existing_count,
        "failed": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    })

@router.post("/generate_final_video")
def generate_final_video(website: Optional[str] = Query(None, description="Website URL used to scope assets")):
    """Combine generated scene videos with any available voiceovers into a single file."""
    slug = website_to_slug(website)
    slug_dir = Path(OUTPUT_PATH) / slug
    video_dir = slug_dir / "video"
    audio_dir = slug_dir / "audio"

    final_video_path = slug_dir / "final_video.mp4"
    final_video_path.parent.mkdir(parents=True, exist_ok=True)

    # Fallback to default slug assets only if the requested slug has no content
    if not video_dir.exists() or not any(video_dir.glob("scene*.mp4")):
        default_dir = Path(OUTPUT_PATH) / "default" / "video"
        if slug != "default" and default_dir.exists() and any(default_dir.glob("scene*.mp4")):
            video_dir = default_dir
            audio_dir = Path(OUTPUT_PATH) / "default" / "audio"
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No generated videos found for slug '{slug}'"
            )

    try:
        process_scenes_and_join(
            video_dir=str(video_dir),
            audio_dir=str(audio_dir),
            final_output=str(final_video_path)
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        raise HTTPException(
            status_code=500,
            detail=f"Failed to combine scenes into final video: {exc}"
        )

    if not final_video_path.exists():
        raise HTTPException(
            status_code=500,
            detail="Final video was not created. Check server logs for details."
        )

    relative_path = final_video_path.relative_to(Path.cwd())
    return {
        "success": True,
        "final_video": str(relative_path),
        "video_dir": str(video_dir.relative_to(Path.cwd())),
        "audio_dir": str(audio_dir.relative_to(Path.cwd())),
    }


@router.get("/")
async def root():
    return {
        "message": "Veo 3.1 Video Generation API",
        "endpoint": "/generate-videos",
        "method": "POST"
    }

@router.post("/generate-voiceovers")
async def generate_voiceovers_endpoint(
    voice_id: Optional[str] = None,
    website: Optional[str] = Query(None, description="Website URL used to scope assets"),
):
    """
    Generate voiceover audio files for all scenes in the storyboard using ElevenLabs TTS.

    - **voice_id**: Optional ElevenLabs voice ID (defaults to Rachel)
    """
    print("🟢 [generate_voiceovers] Called /generate-voiceovers endpoint")

    try:
        slug = website_to_slug(website)
        json_path = storyboard_path_for_slug(slug)
        if not json_path.exists():
            json_path = STORYBOARD_PATH

        print(f"📂 [generate_voiceovers] Loading storyboard from: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            storyboard_data = json.load(f)
            print(f"✅ [generate_voiceovers] Loaded {len(storyboard_data)} storyboard entries")

        if not isinstance(storyboard_data, list):
            raise ValueError("Storyboard JSON must be an array")

        audio_dir = GENERATED_SCENES_BASE / slug / "audio"
        video_dir = GENERATED_SCENES_BASE / slug / "video"

        # Generate voiceovers for all scenes
        results = await generate_all_voiceovers(
            storyboard_data,
            voice_id=voice_id,
            output_dir=audio_dir,
            video_dir=video_dir,
        )

        successful = sum(1 for r in results if r.get("success"))
        failed = len(results) - successful

        print(f"🏁 [generate_voiceovers] Completed: {successful} successful, {failed} failed")

        return {
            "success": True,
            "total_scenes": len(results),
            "successful": successful,
            "failed": failed,
            "details": results
        }

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Storyboard file not found. Please generate storyboard first."
        )
    except Exception as e:
        print(f"❌ [generate_voiceovers] Exception: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Voiceover generation failed: {str(e)}"
        )


class DraftSummary(BaseModel):
    slug: str
    has_storyboard: bool
    scenes: int
    voiceovers: int
    videos: int
    final_video: Optional[str] = None


class DraftDetail(DraftSummary):
    storyboard: Optional[list] = None
    scene_images: List[str] = Field(default_factory=list)
    voiceover_files: List[str] = Field(default_factory=list)
    video_files: List[str] = Field(default_factory=list)


def _public_urls_for_glob(target_dir: Path, pattern: str) -> List[str]:
    if not target_dir.exists():
        return []
    return [public_url_for_path(path) for path in sorted(target_dir.glob(pattern))]


def _summarize_draft(slug: str) -> DraftSummary:
    safe = safe_slug(slug)
    draft_root = GENERATED_SCENES_BASE / safe
    storyboard_file = storyboard_path_for_slug(safe)

    scenes = _public_urls_for_glob(draft_root / "images", "scene*.png")
    voiceovers = _public_urls_for_glob(draft_root / "audio", "*.mp3")
    videos = _public_urls_for_glob(draft_root / "video", "scene*.mp4")
    final_video_path = draft_root / "final_video.mp4"

    summary = DraftSummary(
        slug=safe,
        has_storyboard=storyboard_file.exists(),
        scenes=len(scenes),
        voiceovers=len(voiceovers),
        videos=len(videos),
        final_video=public_url_for_path(final_video_path) if final_video_path.exists() else None,
    )
    return summary


def _load_draft(slug: str) -> DraftDetail:
    summary = _summarize_draft(slug)
    safe = safe_slug(slug)
    draft_root = GENERATED_SCENES_BASE / safe
    storyboard_file = storyboard_path_for_slug(safe)

    storyboard_data = None
    if storyboard_file.exists():
        try:
            with open(storyboard_file, "r", encoding="utf-8") as f:
                storyboard_data = json.load(f)
        except Exception:
            storyboard_data = None

    scene_images = _public_urls_for_glob(draft_root / "images", "scene*.png")
    voiceover_files = _public_urls_for_glob(draft_root / "audio", "*.mp3")
    video_files = _public_urls_for_glob(draft_root / "video", "scene*.mp4")

    return DraftDetail(
        **summary.model_dump(),
        storyboard=storyboard_data if isinstance(storyboard_data, list) else None,
        scene_images=scene_images,
        voiceover_files=voiceover_files,
        video_files=video_files,
    )


@router.get("/drafts")
def list_drafts() -> dict:
    """Return a summary of all drafts discovered under generated_scenes."""

    if not GENERATED_SCENES_BASE.exists():
        return {"drafts": []}

    drafts: List[DraftSummary] = []
    for entry in sorted(GENERATED_SCENES_BASE.iterdir()):
        if entry.is_dir():
            drafts.append(_summarize_draft(entry.name))

    return {"drafts": [d.model_dump() for d in drafts]}


class SaveDraftRequest(BaseModel):
    website: Optional[str] = None
    slug: Optional[str] = None


@router.post("/drafts/save")
def save_draft(payload: SaveDraftRequest):
    """Ensure a draft directory exists for the provided slug or website."""

    slug = safe_slug(payload.slug or "") or website_to_slug(payload.website)
    if not slug:
        raise HTTPException(status_code=400, detail="A slug or website is required to save a draft")

    draft_root = GENERATED_SCENES_BASE / slug
    draft_root.mkdir(parents=True, exist_ok=True)

    return {"success": True, "slug": slug, "path": str(draft_root.relative_to(BASE_DIR))}


@router.get("/drafts/{slug}")
def get_draft(slug: str):
    """Return storyboard, scenes, videos, and voiceovers for a specific draft slug."""

    safe = safe_slug(slug)
    draft_root = GENERATED_SCENES_BASE / safe
    if not draft_root.exists():
        raise HTTPException(status_code=404, detail=f"Draft '{safe}' not found")

    detail = _load_draft(safe)
    return detail.model_dump()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
