"""pipeline.py - Production-leaning orchestration for Railway."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

import agents
import image_gen
import tts
import video_builder

StatusCallback = Optional[Callable[[str, int, str], None]]


def _safe_slug(text: str, limit: int = 42) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:limit] or "video-story"


def _log(status_callback: StatusCallback, step: str, pct: int, message: str) -> None:
    print(f"[{pct:03d}%] {step}: {message}")
    if status_callback:
        status_callback(step, pct, message)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run(
    idea: str,
    output_base: str,
    gemini_key: str,
    voice: str,
    style_preset: str = "cinematic-history",
    aspect_ratio: str = "16:9",
    image_candidates: int = 3,
    strict_images: bool = True,
    status_callback: StatusCallback = None,
) -> Dict:
    if not gemini_key:
        raise ValueError("Missing GEMINI_API_KEY")

    agents.init(gemini_key)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    working_slug = _safe_slug(idea)
    project_dir = Path(output_base) / f"{ts}_{working_slug}"
    docs_dir = project_dir / "docs"
    assets_dir = project_dir / "assets"
    images_dir = assets_dir / "images"
    audio_dir = assets_dir / "audio"
    video_dir = project_dir / "video"

    for d in [docs_dir, images_dir, audio_dir, video_dir]:
        d.mkdir(parents=True, exist_ok=True)

    result = {
        "idea": idea,
        "project_dir": str(project_dir),
        "plan": None,
        "images": [],
        "audio": None,
        "video": None,
        "subtitles": None,
    }

    _log(status_callback, "PLAN", 8, "Building structured plan and scene map")
    plan = agents.build_plan(
        idea=idea,
        style_preset=style_preset,
        aspect_ratio=aspect_ratio,
        requested_voice=voice,
        target_scene_count=8,
    )
    result["plan"] = plan
    _write_json(docs_dir / "plan.json", plan)
    _write_text(docs_dir / "plan.md", agents.to_markdown(plan))

    _log(status_callback, "IMAGE_GEN", 35, "Generating scene-consistent images")
    chosen_images = image_gen.generate_all(
        plan=plan,
        output_dir=str(images_dir),
        candidates=image_candidates,
        strict=strict_images,
        log_fn=lambda m: _log(status_callback, "IMAGE_GEN", 45, m),
    )
    result["images"] = chosen_images
    if len(chosen_images) != len(plan["scenes"]):
        raise RuntimeError("Not all scene images were generated successfully")

    _log(status_callback, "TTS", 70, "Rendering voiceover")
    voice_text = agents.full_voice_text(plan)
    audio_path = audio_dir / "voiceover.mp3"
    tts_ok = tts.generate_voiceover(
        text=voice_text,
        output_path=str(audio_path),
        voice=voice,
        log_fn=lambda m: _log(status_callback, "TTS", 78, m),
    )
    if not tts_ok:
        raise RuntimeError("Voiceover generation failed")
    result["audio"] = str(audio_path)

    _log(status_callback, "SUBTITLES", 82, "Writing subtitles")
    audio_duration = video_builder.get_duration(str(audio_path))
    durations = video_builder.allocate_scene_durations(plan["scenes"], audio_duration)
    subtitle_path = video_dir / "captions.srt"
    video_builder.write_srt(plan["scenes"], durations, str(subtitle_path))
    result["subtitles"] = str(subtitle_path)

    _log(status_callback, "VIDEO", 88, "Assembling final video")
    video_path = video_dir / "output.mp4"
    built_video = video_builder.build_video(
        scenes=plan["scenes"],
        image_paths=chosen_images,
        audio_path=str(audio_path),
        output_path=str(video_path),
        aspect_ratio=aspect_ratio,
        subtitle_path=str(subtitle_path),
        log_fn=lambda m: _log(status_callback, "VIDEO", 94, m),
    )
    result["video"] = built_video

    summary = {
        "title": plan["title"],
        "idea": idea,
        "voice": voice,
        "style_preset": style_preset,
        "aspect_ratio": aspect_ratio,
        "images": [Path(p).name for p in chosen_images],
        "video": str(video_path),
        "audio": str(audio_path),
        "subtitles": str(subtitle_path),
    }
    _write_json(project_dir / "SUMMARY.json", summary)

    _log(status_callback, "DONE", 100, f"Finished: {project_dir}")
    return result
