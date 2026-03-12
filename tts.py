"""tts.py - Edge TTS wrapper with safe text cleanup."""
from __future__ import annotations

import asyncio
import os
import re

DEFAULT_RATE = "+2%"
DEFAULT_PITCH = "+0Hz"


async def _generate(text: str, output_path: str, voice: str, rate: str, pitch: str) -> None:
    import edge_tts

    communicator = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicator.save(output_path)


def clean_text(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate_voiceover(
    text: str,
    output_path: str,
    voice: str,
    rate: str = DEFAULT_RATE,
    pitch: str = DEFAULT_PITCH,
    log_fn=print,
) -> bool:
    text = clean_text(text)
    if not text:
        log_fn("voiceover skipped: empty input")
        return False

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        log_fn(f"voiceover: generating {len(text)} chars")
        asyncio.run(_generate(text, output_path, voice, rate, pitch))
        return True
    except Exception as exc:
        log_fn(f"voiceover failed: {exc}")
        return False
