"""Utilities for generating text-to-speech voiceovers for storyboard scenes."""

import os
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv
import ffmpeg
from elevenlabs.client import ElevenLabs

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not API_KEY:
    raise ValueError("ELEVENLABS_API_KEY environment variable not set")

DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "L1aJrPa7pLJEyYlh3Ilq")
AUDIO_OUTPUT_PATH = Path("generated_scenes") / "default" / "audio"

_client = ElevenLabs(api_key=API_KEY)


def _get_media_duration(path: Union[str, Path]) -> Optional[float]:
    """Return media duration in seconds using ffmpeg.probe, if available."""
    try:
        probe = ffmpeg.probe(str(path))
        return float(probe["format"].get("duration"))
    except Exception:
        return None


async def generate_voiceover(
    text: str,
    scene_index: int,
    voice_id: str = None,
    output_dir: Optional[Union[str, os.PathLike]] = None,
    max_duration: Optional[float] = None,
) -> dict:
    """Generate voiceover audio using ElevenLabs TTS."""
    if not text or not text.strip():
        raise ValueError(f"Empty voiceover text for scene {scene_index}")

    voice_id = voice_id or DEFAULT_VOICE_ID

    audio = _client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
    )

    audio_root = Path(output_dir or AUDIO_OUTPUT_PATH)
    audio_root.mkdir(parents=True, exist_ok=True)

    output_filename = f"scene{scene_index}_voiceover.mp3"
    output_path = audio_root / output_filename

    with open(output_path, "wb") as f:
        for chunk in audio:
            f.write(chunk)

    audio_duration = _get_media_duration(output_path)
    clipped = False

    if max_duration and audio_duration and audio_duration > max_duration:
        clipped = True
        trimmed_path = output_path.with_suffix(".tmp.mp3")
        (
            ffmpeg
            .input(str(output_path))
            .output(str(trimmed_path), t=max_duration, acodec="mp3")
            .overwrite_output()
            .run(quiet=True)
        )
        trimmed_path.replace(output_path)
        audio_duration = _get_media_duration(output_path) or max_duration

    return {
        "success": True,
        "scene_index": scene_index,
        "audio_path": str(output_path),
        "text_length": len(text),
        "voice_id": voice_id,
        "duration_seconds": audio_duration,
        "clipped_to_video": clipped,
        "max_duration_seconds": max_duration,
    }


async def generate_all_voiceovers(
    storyboard_data: list,
    voice_id: str = None,
    output_dir: Optional[Union[str, os.PathLike]] = None,
    video_dir: Optional[Union[str, os.PathLike]] = None,
) -> list:
    """Generate voiceovers for all scenes in the storyboard."""
    results = []

    for i, entry in enumerate(storyboard_data, start=1):
        voice_text = entry.get("voice_over_text")

        if not voice_text:
            continue

        max_duration = None
        if video_dir:
            scene_video = Path(video_dir) / f"scene{i}.mp4"
            if scene_video.exists():
                max_duration = _get_media_duration(scene_video)

        try:
            result = await generate_voiceover(
                voice_text,
                i,
                voice_id,
                output_dir,
                max_duration,
            )
            results.append(result)
        except Exception as e:
            results.append({
                "success": False,
                "scene_index": i,
                "error": str(e),
            })

    return results


__all__ = ["API_KEY", "DEFAULT_VOICE_ID", "generate_voiceover", "generate_all_voiceovers"]
