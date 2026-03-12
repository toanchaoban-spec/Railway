# Video Pipeline Refactor Bundle

This bundle upgrades the original repo toward a more Railway-friendly, more consistent pipeline.

## What changed

- Unified runtime around `GEMINI_API_KEY`
- Moved startup to `gunicorn`
- Added `OUTPUT_DIR` support for Railway volumes
- Replaced loose markdown planning with structured JSON planning
- Added scene-level consistency locks: `character_lock`, `setting_lock`, `style_lock`
- Added multi-candidate image generation and strict failure mode
- Removed placeholder-image behavior from the happy path
- Added scene-proportional durations for better image/voice matching
- Added SRT subtitle output
- Replaced inline HTML UI with template + static assets
- Persisted job status to JSON files under `OUTPUT_DIR/jobs`

## Railway env vars

- `GEMINI_API_KEY`
- `OUTPUT_DIR=/app/data/output`
- `IMAGE_CANDIDATES=3`
- `STRICT_IMAGE_GENERATION=1`
- `DEFAULT_ASPECT_RATIO=16:9`
- `DEFAULT_STYLE_PRESET=cinematic-history`

## Recommended deployment setup

1. Mount a Railway volume at `/app/data`
2. Commit these files over the matching files in the repo
3. Redeploy
4. Open `/healthz` to confirm runtime output path

## Important limitation

This refactor improves consistency and alignment, but image perfection still depends on the external image model. If you need true character consistency across scenes, upgrade the image backend to one that supports reference images or character conditioning.
