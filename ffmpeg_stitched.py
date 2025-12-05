"""Helpers to mix and stitch together video scenes using ffmpeg."""

import os
from typing import Iterable, List, Optional, Tuple

import ffmpeg


def combine_video_audio(video_file: str, audio_file: str, output_file: str, keep_original_audio: bool = True):
    """Combine a video file with an audio file."""
    video = ffmpeg.input(video_file)
    audio_track = ffmpeg.input(audio_file)

    if keep_original_audio:
        # Mix original video audio with new audio track
        original_audio = video.audio
        mixed_audio = ffmpeg.filter(
            [original_audio, audio_track],
            'amix',
            inputs=2,
            duration='first',
            weights='1 1'
        )
        output = ffmpeg.output(video.video, mixed_audio, output_file,
                               vcodec='libx264', acodec='aac', shortest=None)
    else:
        # Replace original audio with new audio track
        output = ffmpeg.output(video.video, audio_track, output_file,
                               vcodec='libx264', acodec='aac', shortest=None)

    ffmpeg.run(output, overwrite_output=True, quiet=True)
    print(f"✓ Combined: {output_file}")


def join_videos(video_files: Iterable[str], output_file: str) -> None:
    """Join multiple MP4 videos into one output file."""
    concat_file = 'temp_filelist.txt'

    try:
        # Write video files to concat list
        with open(concat_file, 'w') as f:
            for video in video_files:
                abs_path = os.path.abspath(video)
                f.write(f"file '{abs_path}'\n")

        # Concatenate videos
        concat_input = ffmpeg.input(concat_file, format='concat', safe=0)
        output = ffmpeg.output(
            concat_input,
            output_file,
            vcodec='libx264',
            acodec='aac'
        )

        ffmpeg.run(output, overwrite_output=True, quiet=True)
        print(f"✓ Successfully created final video: {output_file}")

    finally:
        if os.path.exists(concat_file):
            os.remove(concat_file)


def process_scenes_and_join(
    scenes: Optional[List[Tuple[str, Optional[str]]]] = None,
    final_output: str = 'final_video.mp4',
    keep_original_audio: bool = True,
    cleanup_temp: bool = True,
    video_dir: Optional[str] = None,
    audio_dir: Optional[str] = None,
):
    """Process multiple scenes (video + audio pairs) and join them into final video."""
    # Auto-detect scenes from directories if provided
    if video_dir and audio_dir and scenes is None:
        scenes = []
        video_files = sorted([f for f in os.listdir(video_dir) if f.endswith('.mp4')])

        print(f"Found {len(video_files)} video(s) in {video_dir}")

        for video_file in video_files:
            # Extract scene name (e.g., 'scene1' from 'scene1.mp4')
            scene_name = os.path.splitext(video_file)[0]
            audio_file = f'{scene_name}_voiceover.mp3'

            video_path = os.path.join(video_dir, video_file)
            audio_path = os.path.join(audio_dir, audio_file)

            # Only process videos that exist, with or without matching audio
            if os.path.exists(audio_path):
                scenes.append((video_path, audio_path))
                print(f"  ✓ Paired: {video_file} + {audio_file}")
            else:
                # Video exists but no matching audio - use video without voiceover
                scenes.append((video_path, None))
                print(f"  ⚠ No voiceover for {video_file} - using video only")

        if not scenes:
            print("Error: No videos found in video directory!")
            return

    if not scenes:
        print("Error: No scenes provided!")
        return
    temp_videos = []

    print("\nStep 1: Combining videos with audio tracks...")
    for i, scene in enumerate(scenes, 1):
        video_file = scene[0]
        audio_file = scene[1] if len(scene) > 1 else None

        temp_output = f'temp_scene_{i}.mp4'
        print(f"  Processing scene {i}/{len(scenes)}...")

        if audio_file:
            # Always REPLACE embedded scene audio with voiceover
            combine_video_audio(video_file, audio_file, temp_output, keep_original_audio=False)
        else:
            # No audio file - just copy the video
            import shutil
            shutil.copy(video_file, temp_output)
            print(f"  ✓ Copied video (no voiceover): {temp_output}")

        temp_videos.append(temp_output)

    print("\nStep 2: Joining all scenes into final video...")
    join_videos(temp_videos, final_output)

    if cleanup_temp:
        print("\nStep 3: Cleaning up temporary files...")
        for temp_file in temp_videos:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                print(f"  Removed: {temp_file}")

    print(f"\n✓ Complete! Final video: {final_output}")


# Example usage
if __name__ == "__main__":
    # Method 1: Using directories (auto-detects matching pairs)
    process_scenes_and_join(
        video_dir='videos',
        audio_dir='audio',
        final_output='final_video.mp4',
        keep_original_audio=True
    )

    # Method 2: Manual scene list
    # scenes = [
    #     ('scene1.mp4', 'scene1_voiceover.mp3'),
    #     ('scene2.mp4', 'scene2_voiceover.mp3'),
    #     ('scene3.mp4', 'scene3_voiceover.mp3'),
    # ]
    # process_scenes_and_join(scenes, 'final_video.mp4', keep_original_audio=True)

    # Replace original audio completely with voiceover
    # process_scenes_and_join(
    #     video_dir='videos', audio_dir='audio',
    #     final_output='final_video.mp4', keep_original_audio=False,
    # )