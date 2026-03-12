"""agents.py - LLM planning layer for a more consistent video pipeline."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import google.generativeai as genai

_model = None

STYLE_PRESETS: Dict[str, Dict[str, str]] = {
    "cinematic-history": {
        "label": "Cinematic History",
        "style_lock": "cinematic historical realism, rich environmental detail, dramatic composition, tactile materials, no modern objects, no text, no watermark",
        "negative_lock": "blurry, text, watermark, modern objects, duplicate limbs, deformed face, extra fingers",
    },
    "stylized-anime": {
        "label": "Stylized Anime",
        "style_lock": "high-end anime key visual, dynamic composition, expressive lighting, sharp linework, clean costume detail, no text, no watermark",
        "negative_lock": "photorealistic, ugly anatomy, blurry, text, watermark",
    },
    "flat-cartoon": {
        "label": "Flat Cartoon",
        "style_lock": "2D flat illustration, clean vector lines, bold shapes, limited shading, clear silhouette, no text, no watermark",
        "negative_lock": "photorealistic, 3D render, dark muddy colors, text, watermark",
    },
}


def init(api_key: str, model_name: str = "gemini-2.5-flash") -> None:
    global _model
    genai.configure(api_key=api_key)
    _model = genai.GenerativeModel(model_name)


SYSTEM_PROMPT = """
You are a senior AI video pre-production system.
Return ONLY valid JSON.

Your task:
- Turn a user idea into a coherent short video plan.
- Maintain one consistent main character, one consistent setting logic, and visual continuity.
- Produce scene-by-scene voiceover lines that match the visual of each scene.
- Keep narration punchy and cinematic.
- Default to 8 scenes unless the user requests otherwise.

JSON schema:
{
  "title": "string",
  "working_slug": "string-with-dashes",
  "language": "vi" | "en",
  "format": "youtube-story",
  "aspect_ratio": "16:9" | "9:16",
  "voice_suggestion": "string",
  "style_summary": "string",
  "character_lock": "appearance and wardrobe details reused across all scenes",
  "setting_lock": "world and setting consistency details",
  "thumbnail_prompt": "string",
  "scenes": [
    {
      "scene_id": 1,
      "title": "string",
      "voiceover": "one or two concise narration sentences",
      "image_prompt": "fully specified visual prompt for one still frame",
      "negative_prompt": "negative prompt",
      "shot_type": "close-up | medium | wide | overhead | tracking still",
      "mood": "string",
      "duration_hint_sec": number
    }
  ]
}
""".strip()


def _ensure_model() -> None:
    if _model is None:
        raise RuntimeError("Model not initialized. Set GEMINI_API_KEY first.")


def _call_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_model()
    response = _model.generate_content(
        [SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False)]
    )
    text = response.text.strip()
    return _parse_json(text)


def _parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def build_plan(
    idea: str,
    style_preset: str = "cinematic-history",
    aspect_ratio: str = "16:9",
    requested_voice: str = "vi-VN-HoaiMyNeural",
    target_scene_count: int = 8,
) -> Dict[str, Any]:
    preset = STYLE_PRESETS.get(style_preset, STYLE_PRESETS["cinematic-history"])
    payload = {
        "idea": idea,
        "style_preset": style_preset,
        "style_lock": preset["style_lock"],
        "negative_lock": preset["negative_lock"],
        "aspect_ratio": aspect_ratio,
        "requested_voice": requested_voice,
        "target_scene_count": target_scene_count,
    }
    plan = _call_json(payload)
    return normalize_plan(plan, preset, aspect_ratio, requested_voice, target_scene_count)


def normalize_plan(
    plan: Dict[str, Any],
    preset: Dict[str, str],
    aspect_ratio: str,
    requested_voice: str,
    target_scene_count: int,
) -> Dict[str, Any]:
    scenes_in = plan.get("scenes") or []
    if not scenes_in:
        raise ValueError("LLM did not return any scenes.")

    normalized_scenes: List[Dict[str, Any]] = []
    for idx, raw in enumerate(scenes_in[:target_scene_count], start=1):
        voiceover = str(raw.get("voiceover", "")).strip()
        image_prompt = str(raw.get("image_prompt", "")).strip()
        negative_prompt = str(raw.get("negative_prompt", preset["negative_lock"]))
        if not voiceover or not image_prompt:
            continue
        normalized_scenes.append(
            {
                "scene_id": idx,
                "title": str(raw.get("title", f"Scene {idx}")).strip() or f"Scene {idx}",
                "voiceover": voiceover,
                "image_prompt": image_prompt,
                "negative_prompt": negative_prompt,
                "shot_type": str(raw.get("shot_type", "medium")).strip() or "medium",
                "mood": str(raw.get("mood", "cinematic")).strip() or "cinematic",
                "duration_hint_sec": float(raw.get("duration_hint_sec", 4.0) or 4.0),
            }
        )

    if not normalized_scenes:
        raise ValueError("No usable scenes were returned after normalization.")

    return {
        "title": str(plan.get("title", "AI Video Story")).strip() or "AI Video Story",
        "working_slug": str(plan.get("working_slug", "ai-video-story")).strip() or "ai-video-story",
        "language": str(plan.get("language", "vi")).strip() or "vi",
        "format": "youtube-story",
        "aspect_ratio": aspect_ratio,
        "voice_suggestion": str(plan.get("voice_suggestion", requested_voice)).strip() or requested_voice,
        "style_summary": str(plan.get("style_summary", preset["label"])).strip() or preset["label"],
        "style_lock": preset["style_lock"],
        "negative_lock": preset["negative_lock"],
        "character_lock": str(plan.get("character_lock", "consistent protagonist appearance and wardrobe")).strip(),
        "setting_lock": str(plan.get("setting_lock", "consistent world-building and background continuity")).strip(),
        "thumbnail_prompt": str(plan.get("thumbnail_prompt", "dramatic hero frame for youtube thumbnail")).strip(),
        "scenes": normalized_scenes,
    }


def full_voice_text(plan: Dict[str, Any]) -> str:
    return " ".join(scene["voiceover"].strip() for scene in plan.get("scenes", []) if scene.get("voiceover"))


def to_markdown(plan: Dict[str, Any]) -> str:
    lines = [
        f"# {plan['title']}",
        "",
        f"- Format: {plan['format']}",
        f"- Aspect ratio: {plan['aspect_ratio']}",
        f"- Voice suggestion: {plan['voice_suggestion']}",
        f"- Style summary: {plan['style_summary']}",
        "",
        "## Consistency Locks",
        "",
        f"**Character lock**: {plan['character_lock']}",
        "",
        f"**Setting lock**: {plan['setting_lock']}",
        "",
        f"**Style lock**: {plan['style_lock']}",
        "",
        f"**Thumbnail prompt**: {plan['thumbnail_prompt']}",
        "",
        "## Scenes",
        "",
    ]
    for scene in plan["scenes"]:
        lines.extend(
            [
                f"### Scene {scene['scene_id']:02d} - {scene['title']}",
                f"- Shot: {scene['shot_type']}",
                f"- Mood: {scene['mood']}",
                f"- Duration hint: {scene['duration_hint_sec']} sec",
                f"- Voiceover: {scene['voiceover']}",
                f"- Image prompt: {scene['image_prompt']}",
                f"- Negative prompt: {scene['negative_prompt']}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
