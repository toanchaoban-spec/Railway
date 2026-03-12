"""image_gen.py - More reliable Pollinations image generation with consistency locks."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote

import requests
from PIL import Image

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
DEFAULT_TIMEOUT = 90

ASPECT_SIZES = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}


def _dimensions(aspect_ratio: str) -> tuple[int, int]:
    return ASPECT_SIZES.get(aspect_ratio, ASPECT_SIZES["16:9"])


def _build_prompt(scene: Dict, plan: Dict, variation_index: int) -> str:
    seed_hint = f"variation {variation_index + 1}"
    parts = [
        scene["image_prompt"],
        f"main character consistency: {plan['character_lock']}",
        f"world consistency: {plan['setting_lock']}",
        f"global style lock: {plan['style_lock']}",
        f"camera framing: {scene['shot_type']}",
        f"mood: {scene['mood']}",
        seed_hint,
    ]
    return ", ".join(part.strip() for part in parts if part and str(part).strip())


def _build_negative(scene: Dict, plan: Dict) -> str:
    scene_negative = scene.get("negative_prompt", "")
    plan_negative = plan.get("negative_lock", "")
    return ", ".join(part.strip() for part in [scene_negative, plan_negative] if part and str(part).strip())


def _request_image(prompt: str, aspect_ratio: str, seed: int) -> bytes:
    width, height = _dimensions(aspect_ratio)
    encoded = quote(prompt)
    url = (
        f"{POLLINATIONS_URL.format(prompt=encoded)}"
        f"?width={width}&height={height}&nologo=true&enhance=true&seed={seed}"
    )
    response = requests.get(url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    if not response.headers.get("content-type", "").startswith("image"):
        raise ValueError(f"Unexpected content type: {response.headers.get('content-type')}")
    return response.content


def _stable_seed(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return int(digest, 16)


def _validate_image(path: str, aspect_ratio: str) -> float:
    width_expected, height_expected = _dimensions(aspect_ratio)
    with Image.open(path) as img:
        img.verify()
    with Image.open(path) as img:
        width, height = img.size
    pixels = width * height
    expected = width_expected * height_expected
    return min(1.0, pixels / expected)


def generate_scene_candidates(
    scene: Dict,
    plan: Dict,
    output_dir: str,
    candidates: int = 3,
    retries: int = 2,
    log_fn=print,
) -> List[str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    aspect_ratio = plan.get("aspect_ratio", "16:9")

    for variation_index in range(candidates):
        prompt = _build_prompt(scene, plan, variation_index)
        negative = _build_negative(scene, plan)
        final_prompt = f"{prompt}. Negative prompt guidance: {negative}"
        seed = _stable_seed(f"{plan['working_slug']}-{scene['scene_id']}-{variation_index}")
        out = os.path.join(output_dir, f"scene_{scene['scene_id']:02d}_v{variation_index + 1}.png")

        for attempt in range(retries):
            try:
                image_bytes = _request_image(final_prompt, aspect_ratio, seed + attempt)
                with open(out, "wb") as f:
                    f.write(image_bytes)
                score = _validate_image(out, aspect_ratio)
                if score < 0.4:
                    raise ValueError("Generated image failed quality threshold.")
                saved.append(out)
                log_fn(f"scene {scene['scene_id']:02d}: saved candidate {variation_index + 1}/{candidates}")
                break
            except Exception as exc:
                log_fn(f"scene {scene['scene_id']:02d}: candidate {variation_index + 1} retry {attempt + 1} failed - {exc}")
                time.sleep(1.5)
        time.sleep(0.6)
    return saved


def choose_best_candidate(paths: List[str], aspect_ratio: str) -> str:
    if not paths:
        raise ValueError("No valid image candidates generated.")
    scored = [(path, _validate_image(path, aspect_ratio)) for path in paths]
    scored.sort(key=lambda item: (item[1], os.path.getsize(item[0])), reverse=True)
    return scored[0][0]


def generate_all(
    plan: Dict,
    output_dir: str,
    candidates: int = 3,
    strict: bool = True,
    log_fn=print,
) -> List[str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    chosen: List[str] = []
    aspect_ratio = plan.get("aspect_ratio", "16:9")

    for scene in plan["scenes"]:
        candidates_dir = os.path.join(output_dir, f"scene_{scene['scene_id']:02d}")
        paths = generate_scene_candidates(
            scene=scene,
            plan=plan,
            output_dir=candidates_dir,
            candidates=candidates,
            log_fn=log_fn,
        )
        if not paths and strict:
            raise RuntimeError(f"Failed to generate image for scene {scene['scene_id']:02d}")
        if not paths:
            continue
        best = choose_best_candidate(paths, aspect_ratio)
        final_path = os.path.join(output_dir, f"scene_{scene['scene_id']:02d}.png")
        Image.open(best).save(final_path)
        chosen.append(final_path)
        log_fn(f"scene {scene['scene_id']:02d}: locked best image")
    return chosen
