import os
import re
import uuid
import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from google import genai as google_genai
from google.genai import types as genai_types

from api.models import JobCreate, JobOut, ClipOut, JobStatus, RerenderRequest, MetadataRequest
from api.database import create_job, get_job, get_job_by_video_id, update_job, get_redis
from api.worker import process_video, rerender_clip
from services.video_cutter import extract_thumbnail

app = FastAPI(
    title="ClipForge AI",
    description="Telugu video repurposing pipeline API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path("storage/outputs")
UPLOAD_DIR = Path("storage/uploads")

app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")


# ── Serve thumbnails ──────────────────────────────────────────

@app.get("/thumbnails/{filename}")
async def serve_thumbnail(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(str(path), media_type="image/jpeg")


# ── Health check ──────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "ClipForge AI"}


# ── Submit a job ──────────────────────────────────────────────

@app.post("/jobs", response_model=JobOut)
def create_job_endpoint(payload: JobCreate):
    """
    Submit a YouTube URL for processing.
    Priority:
      1. Redis cache hit (done job already in Redis) → return instantly
      2. Storage hit (clips JSON + output files exist) → recover into Redis, return instantly
      3. Full pipeline run
    """
    video_id = _extract_video_id(payload.url)

    if video_id:
        # ── 1. Redis cache hit ────────────────────────────────
        existing = get_job_by_video_id(video_id)
        if existing:
            print(f"  [API] Redis hit — returning existing job for {video_id}")
            return _job_to_out(existing)

        # ── 2. Storage hit — recover without pipeline ─────────
        recovered = _recover_from_storage(video_id)
        if recovered:
            print(f"  [API] Storage hit — recovered job for {video_id}")
            return _job_to_out(recovered)

    # ── 3. Full pipeline ──────────────────────────────────────
    job_id = str(uuid.uuid4())
    create_job(job_id, url=payload.url, language=payload.language)
    if payload.email:
        update_job(job_id, email=payload.email)
    process_video.delay(job_id, payload.url, payload.language)
    return _job_to_out(get_job(job_id))


@app.post("/jobs/upload", response_model=JobOut)
async def create_job_upload(
    file: UploadFile = File(...),
    language: str = Form("te"),
):
    """Submit an MP4 upload for processing."""
    job_id   = str(uuid.uuid4())
    video_id = job_id[:8]
    save_path = UPLOAD_DIR / f"{video_id}.mp4"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    create_job(job_id, url=str(save_path), language=language)
    process_video.delay(job_id, str(save_path), language)
    return _job_to_out(get_job(job_id))


# ── Recover job from storage (dev utility) ───────────────────

@app.post("/jobs/recover/{video_id}", response_model=JobOut)
def recover_job(video_id: str):
    """
    Rebuild a Redis job from existing storage files.
    Use this when Redis was flushed but clips already exist in storage/outputs/.
    e.g. POST /jobs/recover/-OetXsp7xdI
    """
    clips_path = UPLOAD_DIR / f"{video_id}_audio_clips.json"
    if not clips_path.exists():
        raise HTTPException(status_code=404, detail=f"No clips JSON found for video {video_id}")

    # Don't recover a "done" job if the clips were never actually cut/captioned —
    # that produces a job with empty vertical_path/captioned_path that looks done
    # but has nothing playable.
    captioned = list(OUTPUT_DIR.glob(f"{video_id}_clip*_captioned.mp4"))
    if not captioned:
        raise HTTPException(
            status_code=404,
            detail=f"Clips were selected for {video_id} but never cut/captioned — "
                   f"run the cutting pipeline before recovering this job."
        )

    with open(clips_path, "r", encoding="utf-8") as f:
        clips_data = json.load(f)

    output_clips = []
    for i, clip in enumerate(clips_data.get("clips", []), 1):
        captioned_files = list(OUTPUT_DIR.glob(f"{video_id}_clip{i}_*_captioned.mp4"))
        vertical_files  = list(OUTPUT_DIR.glob(f"{video_id}_clip{i}_*_vertical.mp4"))
        # Raw = no _vertical, no _captioned, no _captions suffix
        raw_files = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{i}_*.mp4")
                     if "_vertical" not in f.name and "_captioned" not in f.name and "_captions" not in f.name]

        thumb_base = str(raw_files[0]) if raw_files else (str(captioned_files[0]) if captioned_files else None)
        thumb_path = thumb_base.replace('.mp4', '_thumb.jpg') if thumb_base else None
        if thumb_base and thumb_path and not os.path.exists(thumb_path):
            try:
                extract_thumbnail(thumb_base)
            except Exception as e:
                print(f"  ⚠ Thumbnail generation failed (non-fatal): {e}")
        output_clips.append({
            "clip_id":         clip.get("clip_id", f"{video_id}_c{i}"),
            "rank":            clip.get("confidence_rank", i),
            "why":             clip.get("why", ""),
            "hook_text":       clip.get("hook_text", ""),
            "virality_score":  clip.get("virality_score", 0),
            "engagement_type": clip.get("engagement_type", ""),
            "start":           clip.get("start", 0),
            "end":             clip.get("end", 0),
            "duration":        clip.get("duration", 0),
            "segments":        clip.get("segments", []),
            "raw_path":        str(raw_files[0])       if raw_files       else "",
            "captioned_path":  str(captioned_files[0]) if captioned_files else "",
            "vertical_path":   str(vertical_files[0])  if vertical_files  else "",
            "thumbnail_path":  thumb_path if thumb_path and os.path.exists(thumb_path) else None,
        })

    # Create a fresh done job in Redis
    job_id = str(uuid.uuid4())
    from api.database import set_job_clips
    create_job(job_id, url=f"recovered:{video_id}", language="te")
    from api.database import update_job
    update_job(job_id, status="done", progress=100, current_stage="Complete", video_id=video_id)
    set_job_clips(job_id, output_clips)

    print(f"  [API] Recovered job {job_id} for video {video_id} with {len(output_clips)} clips")
    return _job_to_out(get_job(job_id))


# ── Poll job status ───────────────────────────────────────────

@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job_endpoint(job_id: str):
    """Get job status and progress."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_out(job)


@app.patch("/jobs/{job_id}")
def update_job_endpoint(job_id: str, body: dict):
    """Update job fields, e.g. notification email."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if "email" in body:
        update_job(job_id, email=body["email"])
    return {"ok": True}


# ── Re-render a clip (new style / format) ────────────────────

@app.post("/jobs/{job_id}/clips/{clip_index}/rerender")
def rerender_clip_endpoint(job_id: str, clip_index: int, payload: RerenderRequest):
    """
    Re-render a single clip with a new caption style and/or export format.
    Returns a rerender_job_id to poll at /jobs/<rerender_job_id>.
    When done, job will have captioned_path and vertical_path set.
    """
    source_job = get_job(job_id)
    if not source_job:
        raise HTTPException(status_code=404, detail="Source job not found")

    clips = source_job.get("clips", [])
    if clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip index out of range")

    video_id = source_job.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400, detail="No video_id on source job")

    rerender_job_id = str(uuid.uuid4())
    create_job(rerender_job_id, url=f"rerender:{job_id}:{clip_index}", language="te")

    rerender_clip.delay(
        rerender_job_id=rerender_job_id,
        source_job_id=job_id,
        clip_index=clip_index,
        style=payload.style,
        fmt=payload.format,
        background=payload.background,
        bg_color=payload.bg_color,
        use_autocrop=payload.use_autocrop,
        trim_start=payload.trim_start,
        trim_end=payload.trim_end,
        video_id=video_id,
        transcript_edits=payload.transcript_edits.model_dump() if payload.transcript_edits else None,
        crop_box=payload.crop_box,
        selected_subject=payload.selected_subject,
        crop_mode=payload.crop_mode,
        elements=payload.elements,
        caption_font=payload.caption_font,
        caption_x=payload.caption_x,
        caption_y=payload.caption_y,
    )

    return {"rerender_job_id": rerender_job_id}


# ── Draft save / restore ──────────────────────────────────────

@app.patch("/jobs/{job_id}/clips/{clip_id}/draft")
def save_draft(job_id: str, clip_id: str, payload: dict = Body(...)):
    """Persist editor draft state for a clip. Stored in Redis with a 7-day TTL."""
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    get_redis().set(f"draft:{job_id}:{clip_id}", json.dumps(payload), ex=7 * 86400)
    return {"ok": True}


@app.get("/jobs/{job_id}/clips/{clip_id}/draft")
def load_draft(job_id: str, clip_id: str):
    """Return the persisted draft for a clip, or null if none has been saved yet."""
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    raw = get_redis().get(f"draft:{job_id}:{clip_id}")
    return {"draft": json.loads(raw) if raw else None}


# ── Get transcript for caption overlay ───────────────────────

@app.get("/transcript/{video_id}")
def get_transcript(video_id: str):
    """Return word timestamps for canvas caption overlay."""
    path = UPLOAD_DIR / f"{video_id}_audio_transcript.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Generate clip metadata (title / description / hashtags) ──

@app.post("/jobs/{job_id}/clips/{clip_index}/metadata")
def generate_clip_metadata(job_id: str, clip_index: int, payload: MetadataRequest):
    """Generate AI title, description, and hashtags for a clip via Gemini."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    prompt = f"""You are a social media expert for Telugu content creators posting on Instagram Reels and YouTube Shorts.

Given the following clip transcript, generate metadata in JSON format.

Transcript:
{payload.transcript_text}

Return ONLY a JSON object with these exact fields:
{{
  "title": "punchy curiosity-driven title under 60 characters, can be English or Tenglish (Telugu + English mix)",
  "description": "hook + value statement under 150 characters, no emojis, platform-neutral",
  "hashtags": ["array", "of", "6", "to", "8", "tags", "without", "hash", "symbol", "mix Telugu niche and broad reach tags"]
}}

Rules:
- title: under 60 chars, curiosity gap or surprising fact style, can mix Telugu words with English
- description: under 150 chars, start with a hook, no emojis
- hashtags: 6-8 items, mix Telugu-niche tags (e.g. teluguhealth, telugumotivation) with broad tags (e.g. shorts, reels), no # prefix"""

    try:
        client = google_genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)
        return {
            "title":       str(data.get("title", "")),
            "description": str(data.get("description", "")),
            "hashtags":    [str(h).lstrip("#") for h in data.get("hashtags", [])],
        }
    except Exception as e:
        print(f"  [metadata] Gemini error: {e}")
        raise HTTPException(status_code=500, detail="Metadata generation failed")


# ── Download a clip ───────────────────────────────────────────

@app.get("/clips/download")
def download_clip(path: str):
    """Download a single clip by file path."""
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=file_path.name,
    )


# ── Helpers ───────────────────────────────────────────────────

def _recover_from_storage(video_id: str) -> Optional[dict]:
    """
    If clips JSON and output files already exist in storage,
    rebuild a done Redis job without running the pipeline.
    Returns the job dict if recovered, None if files don't exist.
    """
    clips_path = UPLOAD_DIR / f"{video_id}_audio_clips.json"
    if not clips_path.exists():
        return None

    # Check at least one captioned clip exists
    captioned = list(OUTPUT_DIR.glob(f"{video_id}_clip*_captioned.mp4"))
    if not captioned:
        return None

    with open(clips_path, "r", encoding="utf-8") as f:
        clips_data = json.load(f)

    from api.database import update_job, set_job_clips

    output_clips = []
    for i, clip in enumerate(clips_data.get("clips", []), 1):
        captioned_files = list(OUTPUT_DIR.glob(f"{video_id}_clip{i}_*_captioned.mp4"))
        vertical_files  = list(OUTPUT_DIR.glob(f"{video_id}_clip{i}_*_vertical.mp4"))
        raw_files = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{i}_*.mp4")
                     if "_vertical" not in f.name and "_captioned" not in f.name and "_captions" not in f.name]

        thumb_base = str(raw_files[0]) if raw_files else (str(captioned_files[0]) if captioned_files else None)
        thumb_path = thumb_base.replace('.mp4', '_thumb.jpg') if thumb_base else None
        if thumb_base and thumb_path and not os.path.exists(thumb_path):
            try:
                extract_thumbnail(thumb_base)
            except Exception as e:
                print(f"  ⚠ Thumbnail generation failed (non-fatal): {e}")
        output_clips.append({
            "clip_id":         clip.get("clip_id", f"{video_id}_c{i}"),
            "rank":            clip.get("confidence_rank", i),
            "why":             clip.get("why", ""),
            "hook_text":       clip.get("hook_text", ""),
            "virality_score":  clip.get("virality_score", 0),
            "engagement_type": clip.get("engagement_type", ""),
            "start":           clip.get("start", 0),
            "end":             clip.get("end", 0),
            "duration":        clip.get("duration", 0),
            "segments":        clip.get("segments", []),
            "raw_path":        str(raw_files[0])       if raw_files       else "",
            "captioned_path":  str(captioned_files[0]) if captioned_files else "",
            "vertical_path":   str(vertical_files[0])  if vertical_files  else "",
            "thumbnail_path":  thumb_path if thumb_path and os.path.exists(thumb_path) else None,
        })

    job_id = str(uuid.uuid4())
    create_job(job_id, url=f"recovered:{video_id}", language="te")
    update_job(job_id, status="done", progress=100, current_stage="Complete", video_id=video_id)
    set_job_clips(job_id, output_clips)

    return get_job(job_id)


def _extract_video_id(url: str) -> Optional[str]:
    """
    Extract YouTube video ID from any common URL format:
      https://www.youtube.com/watch?v=CC8V0PwlQ4o
      https://youtu.be/CC8V0PwlQ4o
      https://youtube.com/shorts/CC8V0PwlQ4o
    Returns None if not a recognisable YouTube URL.
    """
    try:
        parsed = urlparse(url)
        # youtu.be/<id>
        if parsed.netloc in ("youtu.be",):
            return parsed.path.lstrip("/").split("/")[0] or None
        # youtube.com/watch?v=<id>
        if "youtube.com" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "v" in qs:
                return qs["v"][0]
            # youtube.com/shorts/<id>  or  youtube.com/embed/<id>
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "v"):
                return parts[1]
    except Exception:
        pass
    return None


def _job_to_out(job: dict) -> JobOut:
    clips = []
    for c in job.get("clips", []):
        clips.append(ClipOut(
            clip_id         = c.get("clip_id", ""),
            rank            = c.get("rank", 0),
            why             = c.get("why", ""),
            hook_text       = c.get("hook_text", ""),
            virality_score  = c.get("virality_score", 0),
            engagement_type = c.get("engagement_type", ""),
            start           = c.get("start", 0),
            end             = c.get("end", 0),
            duration        = c.get("duration", 0),
            segments        = c.get("segments", []),
            raw_path        = c.get("raw_path", ""),
            captioned_path  = c.get("captioned_path", ""),
            vertical_path   = c.get("vertical_path", ""),
            thumbnail_path  = c.get("thumbnail_path") or None,
        ))

    _raw_warnings = job.get("warnings")
    _warnings = json.loads(_raw_warnings) if isinstance(_raw_warnings, str) else _raw_warnings

    return JobOut(
        job_id         = job["job_id"],
        status         = JobStatus(job["status"]),
        progress       = int(job.get("progress", 0)),
        current_stage  = job.get("current_stage", ""),
        video_id       = job.get("video_id") or None,
        error          = job.get("error") or None,
        clips          = clips if clips else None,
        captioned_path = job.get("captioned_path") or None,
        vertical_path  = job.get("vertical_path") or None,
        warnings       = _warnings or None,
    )