"""video_builder.py - Scene-based slideshow assembly with exact durations and subtitles."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

ASPECT_SIZES = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def get_duration(file_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0.0
    data = json.loads(result.stdout or "{}")
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


def _run(cmd: List[str], log_fn=print) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg command failed")
    if result.stderr.strip():
        log_fn(result.stderr.strip())


def allocate_scene_durations(scenes: List[Dict], total_audio_sec: float) -> List[float]:
    weights = []
    for scene in scenes:
        words = max(1, len(scene.get("voiceover", "").split()))
        hinted = max(2.5, float(scene.get("duration_hint_sec", 4.0) or 4.0))
        weights.append(max(words / 5.0, hinted))
    total_weight = sum(weights) or len(scenes)
    budget = max(total_audio_sec + 0.75, len(scenes) * 3.0)
    durations = [round((w / total_weight) * budget, 2) for w in weights]
    return durations


def write_srt(scenes: List[Dict], durations: List[float], output_path: str) -> str:
    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h = ms // 3600000
        ms %= 3600000
        m = ms // 60000
        ms %= 60000
        s = ms // 1000
        ms %= 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    current = 0.0
    lines: List[str] = []
    for idx, (scene, dur) in enumerate(zip(scenes, durations), start=1):
        start = current
        end = current + dur
        lines.extend([
            str(idx),
            f"{stamp(start)} --> {stamp(end)}",
            scene["voiceover"].strip(),
            "",
        ])
        current = end
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return output_path


def build_video(
    scenes: List[Dict],
    image_paths: List[str],
    audio_path: str,
    output_path: str,
    aspect_ratio: str = "16:9",
    subtitle_path: str | None = None,
    log_fn=print,
) -> str:
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg/ffprobe is not available in runtime")
    if len(scenes) != len(image_paths):
        raise ValueError("Scene count does not match image count")

    width, height = ASPECT_SIZES.get(aspect_ratio, ASPECT_SIZES["16:9"])
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    tmp_dir = Path(output_path).parent / "_tmp"
    clips_dir = tmp_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    try:
        audio_duration = get_duration(audio_path)
        durations = allocate_scene_durations(scenes, audio_duration)
        concat_list = tmp_dir / "concat.txt"

        with concat_list.open("w", encoding="utf-8") as concat:
            for idx, (scene, img_path, dur) in enumerate(zip(scenes, image_paths, durations), start=1):
                clip_path = clips_dir / f"scene_{idx:02d}.mp4"
                zoom = "zoompan=z='min(zoom+0.0008,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1"
                vf = (
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},{zoom},fps=30,format=yuv420p"
                )
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-t",
                    str(dur),
                    "-i",
                    img_path,
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "30",
                    str(clip_path),
                    "-loglevel",
                    "error",
                ]
                _run(cmd, log_fn)
                concat.write(f"file '{clip_path.resolve()}'\n")

        slideshow_path = tmp_dir / "slideshow.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(slideshow_path),
                "-loglevel",
                "error",
            ],
            log_fn,
        )

        final_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(slideshow_path),
            "-i",
            audio_path,
        ]
        if subtitle_path and os.path.exists(subtitle_path):
            subtitle_filter = f"subtitles={subtitle_path}"
            final_cmd.extend(["-vf", subtitle_filter])
        final_cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                output_path,
                "-loglevel",
                "error",
            ]
        )
        _run(final_cmd, log_fn)
        return output_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
