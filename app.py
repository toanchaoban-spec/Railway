from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict

from flask import Flask, jsonify, render_template, request, send_file

import pipeline
from agents import STYLE_PRESETS

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(BASE_DIR / "output")))
JOBS_DIR = OUTPUT_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
EXECUTOR = ThreadPoolExecutor(max_workers=1)

app = Flask(__name__, template_folder="templates", static_folder="static")


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write_job(job_id: str, data: Dict) -> None:
    _job_path(job_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_job(job_id: str) -> Dict:
    path = _job_path(job_id)
    if not path.exists():
        return {"status": "not_found"}
    return json.loads(path.read_text(encoding="utf-8"))


def _update_job(job_id: str, **patch) -> None:
    data = _read_job(job_id)
    data.update(patch)
    _write_job(job_id, data)


@app.route("/")
def index():
    voices = [
        ("vi-VN-HoaiMyNeural", "Vietnamese - Female (Hoai My)"),
        ("vi-VN-NamMinhNeural", "Vietnamese - Male (Nam Minh)"),
        ("en-US-JennyNeural", "English - Female (Jenny)"),
        ("en-US-GuyNeural", "English - Male (Guy)"),
    ]
    return render_template("index.html", voices=voices, style_presets=STYLE_PRESETS)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "output_dir": str(OUTPUT_DIR)})


@app.route("/start", methods=["POST"])
def start():
    payload = request.get_json(force=True)
    idea = str(payload.get("idea", "")).strip()
    if not idea:
        return jsonify({"error": "Idea is required"}), 400

    voice = str(payload.get("voice", "vi-VN-HoaiMyNeural"))
    style_preset = str(payload.get("style_preset", os.environ.get("DEFAULT_STYLE_PRESET", "cinematic-history")))
    aspect_ratio = str(payload.get("aspect_ratio", os.environ.get("DEFAULT_ASPECT_RATIO", "16:9")))
    image_candidates = int(os.environ.get("IMAGE_CANDIDATES", "3"))
    strict_images = os.environ.get("STRICT_IMAGE_GENERATION", "1") == "1"

    job_id = uuid.uuid4().hex[:10]
    _write_job(
        job_id,
        {
            "status": "running",
            "step": "PLAN",
            "progress": 1,
            "message": "Queued",
            "error": None,
            "result": None,
        },
    )

    def status_cb(step: str, progress: int, message: str) -> None:
        _update_job(job_id, step=step, progress=progress, message=message)

    def worker() -> None:
        try:
            result = pipeline.run(
                idea=idea,
                output_base=str(OUTPUT_DIR),
                gemini_key=os.environ.get("GEMINI_API_KEY", ""),
                voice=voice,
                style_preset=style_preset,
                aspect_ratio=aspect_ratio,
                image_candidates=image_candidates,
                strict_images=strict_images,
                status_callback=status_cb,
            )
            _update_job(
                job_id,
                status="done",
                progress=100,
                message="Completed",
                result=result,
                project_dir=result.get("project_dir"),
            )
        except Exception as exc:
            _update_job(job_id, status="error", error=str(exc), message=str(exc))

    EXECUTOR.submit(worker)
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    return jsonify(_read_job(job_id))


@app.route("/download/<job_id>/<file_key>")
def download(job_id: str, file_key: str):
    job = _read_job(job_id)
    project_dir = job.get("project_dir")
    if not project_dir:
        return "Job not found", 404
    base = Path(project_dir)
    file_map = {
        "video": base / "video" / "output.mp4",
        "audio": base / "assets" / "audio" / "voiceover.mp3",
        "plan": base / "docs" / "plan.md",
        "plan_json": base / "docs" / "plan.json",
        "subtitles": base / "video" / "captions.srt",
        "summary": base / "SUMMARY.json",
    }
    target = file_map.get(file_key)
    if not target or not target.exists():
        return "File not found", 404
    return send_file(str(target), as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
