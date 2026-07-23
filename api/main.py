import os
import re
import uuid
import json
import hashlib
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from google import genai as google_genai
from google.genai import types as genai_types

from api.models import (
    JobCreate, JobOut, ClipOut, JobStatus, RerenderRequest, MetadataRequest,
    TransliterateRequest, TransliterateResponse,
    TanglishRequest, TanglishResponse,
    RealignLineRequest, RealignLineResponse, RealignedWord,
    BillingStatusOut, SubscriptionCreateOut, PlanInfo,
)
from api.database import (
    create_job, get_job, get_job_by_video_id, update_job, get_redis, delete_job,
    list_jobs_by_owner, video_owned_by, video_lock_held,
    get_user_billing, set_user_billing, set_subscription_owner, get_subscription_owner,
    get_user_caption_template, set_user_caption_template,
    claim_billing_event, release_billing_event,
    get_subscription_event_ts, set_subscription_event_ts,
    acquire_billing_create_lock, release_billing_create_lock,
)
from services.youtube_utils import extract_video_id
from api.auth import AuthUser, get_current_user, user_owns_job, log_auth_startup
from api import billing
from api.worker import process_video, rerender_clip, read_default_crop_box
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

log_auth_startup()

# KNOWN GAP (deploy phase, not this build): /outputs and /thumbnails serve
# media to <video>/<img> tags, which cannot send Authorization headers —
# they stay unauthenticated until signed URLs land. Job METADATA (what exists,
# whose it is) is fully scoped below; media FILES are guessable only by
# video id. Flagged in SETUP_AUTH.md.
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")


def _tier_ttl(user_id: str) -> Optional[int]:
    """Feature #20 — the published-clip TTL (seconds) for a user's tier, or
    None for a no-expiry tier. Free = 24h; paid = longer/none."""
    from api import tiers
    hours = tiers.expiry_hours(get_user_billing(user_id).get("plan", tiers.FREE))
    return int(hours * 3600) if hours else None


def _get_owned_job(job_id: str, user: AuthUser) -> dict:
    """Fetch a job the caller owns, or 404. Not-found and not-yours are the
    SAME 404 on purpose — existence of other users' jobs must not leak."""
    job = get_job(job_id)
    if not job or not user_owns_job(job, user):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _require_video_access(video_id: str, user: AuthUser):
    """404 unless the caller owns some job over this video_id. Guards
    video-id-keyed resources (transcript, clip downloads)."""
    if not video_owned_by(video_id, user.id, include_ownerless=user.is_dev):
        raise HTTPException(status_code=404, detail="Not found")


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
def create_job_endpoint(payload: JobCreate, user: AuthUser = Depends(get_current_user)):
    """
    Submit a YouTube URL for processing.
    Priority:
      1. Redis cache hit (done job already in Redis, owned by the caller) → return instantly
      2. Storage hit (clips JSON + output files exist) → recover into Redis, return instantly
      3. Full pipeline run
    Cache/recover are scoped to the caller: another user's job for the same
    video is never returned — the stranger gets their OWN job record (the
    storage artifacts underneath are shared per video_id by design).

    Only genuine YouTube URLs are accepted. Local filesystem paths go through
    POST /jobs/upload exclusively — accepting them here let any authenticated
    user submit another user's storage/uploads path and process a private
    upload as their own (ownership bypass).
    """
    video_id = _extract_video_id(payload.url)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="Not a recognisable YouTube URL. Paste a youtube.com or "
                   "youtu.be link, or use the file upload for local videos.",
        )

    if video_id:
        # ── 1. Redis cache hit (caller's own job only) ────────
        existing = get_job_by_video_id(video_id, owner=user.id,
                                       include_ownerless=user.is_dev)
        if existing:
            missing = _missing_artifacts(video_id, existing)
            if not missing:
                print(f"  [API] Redis hit — all artifacts present, returning existing job for {video_id}")
                return _job_to_out(existing)

            # Stale cache: the record says 'done' but files it references were
            # deleted from storage/outputs. Returning it would 404 the frontend
            # forever with nothing ever re-rendering. Regenerate only what's
            # missing, REUSING surviving checkpoints (crucially the transcript —
            # re-transcribing costs external API credits).
            stages = _regeneration_stages(video_id)
            print(f"  [API] Redis hit but STALE for {video_id} — missing artifacts "
                  f"{sorted(set(missing))}; re-running stages {stages} "
                  f"(reusing any surviving download/transcript/clip-selection checkpoints)")
            # A pipeline already running on this video would corrupt/duplicate
            # the regeneration — reject rather than run concurrently. (The
            # worker's per-video lock is the authoritative guard; this is the
            # friendly fast path.)
            if video_lock_held(video_id):
                raise HTTPException(
                    status_code=409,
                    detail="This video is already being processed. "
                           "Wait for the current job to finish.",
                )
            # Drop the dead record so a future video-id scan doesn't re-find it.
            delete_job(existing["job_id"])
            job_id = str(uuid.uuid4())
            create_job(job_id, url=payload.url, language=payload.language, owner=user.id, ttl_seconds=_tier_ttl(user.id))
            if payload.email:
                update_job(job_id, email=payload.email)
            process_video.delay(job_id, payload.url, payload.language, known_video_id=video_id)
            return _job_to_out(get_job(job_id))

        # ── 2. Storage hit — recover without pipeline ─────────
        recovered = _recover_from_storage(video_id, owner=user.id)
        if recovered:
            print(f"  [API] Storage hit — recovered job for {video_id}")
            return _job_to_out(recovered)

    # ── 3. Full pipeline ──────────────────────────────────────
    if video_lock_held(video_id):
        raise HTTPException(
            status_code=409,
            detail="This video is already being processed. "
                   "Wait for the current job to finish.",
        )
    job_id = str(uuid.uuid4())
    create_job(job_id, url=payload.url, language=payload.language, owner=user.id, ttl_seconds=_tier_ttl(user.id))
    if payload.email:
        update_job(job_id, email=payload.email)
    process_video.delay(job_id, payload.url, payload.language)
    return _job_to_out(get_job(job_id))


@app.post("/jobs/upload", response_model=JobOut)
async def create_job_upload(
    file: UploadFile = File(...),
    language: str = Form("te"),
    user: AuthUser = Depends(get_current_user),
):
    """Submit an MP4 upload for processing."""
    job_id   = str(uuid.uuid4())
    video_id = job_id[:8]
    save_path = UPLOAD_DIR / f"{video_id}.mp4"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    create_job(job_id, url=str(save_path), language=language, owner=user.id, ttl_seconds=_tier_ttl(user.id))
    # is_upload=True: the ONLY way the worker treats a task's url as a local
    # file — set exclusively here, for a path this route itself just wrote.
    process_video.delay(job_id, str(save_path), language, is_upload=True)
    return _job_to_out(get_job(job_id))


# ── User overlay images (editor "add any image") ──────────────

# 5 MB is generous for a watermark/sticker-sized overlay PNG and keeps a
# hostile upload from filling the outputs volume.
_OVERLAY_IMAGE_MAX_BYTES = 5 * 1024 * 1024


@app.post("/jobs/{job_id}/overlay-images")
async def upload_overlay_image(job_id: str, file: UploadFile = File(...),
                               user: AuthUser = Depends(get_current_user)):
    """Upload an image the editor can composite as an overlay element.

    Ownership follows the job (same 404-not-403 guard as every job route);
    the stored file is named {video_id}_useroverlay_{8 hex}.{png|jpg} in
    storage/outputs, so it is (a) previewable through the existing static
    /outputs mount like every other clip asset, (b) skipped by pipeline
    cleanup via the _useroverlay marker, and (c) resolvable at burn time
    ONLY by a job over the same video (services/overlay_renderer.py ::
    resolve_image_overlays pins the id to the rendering job's video_id).
    The bytes are sniffed with PIL — the client's declared content type is
    never trusted; anything that doesn't parse as a real PNG/JPEG is 422.
    """
    job = _get_owned_job(job_id, user)
    video_id = job.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400,
                            detail="This job has no video yet — upload after processing starts")

    content = await file.read()
    if len(content) > _OVERLAY_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 5 MB)")
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")

    import io
    from PIL import Image as PILImage, UnidentifiedImageError
    try:
        probe = PILImage.open(io.BytesIO(content))
        probe.verify()  # parse-level integrity check, no full decode
        fmt = probe.format
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=422, detail="Not a valid image file")
    if fmt not in ("PNG", "JPEG"):
        raise HTTPException(status_code=422, detail="Only PNG and JPEG images are supported")

    ext = ".png" if fmt == "PNG" else ".jpg"
    image_id = f"{video_id}_useroverlay_{uuid.uuid4().hex[:8]}{ext}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_path = OUTPUT_DIR / image_id
    save_path.write_bytes(content)
    return {"image_id": image_id, "path": str(save_path)}


# ── Recover job from storage (dev utility) ───────────────────

@app.post("/jobs/recover/{video_id}", response_model=JobOut)
def recover_job(video_id: str, user: AuthUser = Depends(get_current_user)):
    """
    Rebuild a Redis job from existing storage files.
    Use this when Redis was flushed but clips already exist in storage/outputs/.
    e.g. POST /jobs/recover/-OetXsp7xdI
    The recovered job belongs to the caller.
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
            "refined_start":   clip.get("refined_start"),
            "refined_end":     clip.get("refined_end"),
            "refined_segments": clip.get("refined_segments", []),
            "emphasis_indices": clip.get("emphasis_indices", []),
            "raw_path":        str(raw_files[0])       if raw_files       else "",
            "captioned_path":  str(captioned_files[0]) if captioned_files else "",
            "vertical_path":   str(vertical_files[0])  if vertical_files  else "",
            "thumbnail_path":  thumb_path if thumb_path and os.path.exists(thumb_path) else None,
            "default_crop_box": read_default_crop_box(OUTPUT_DIR, video_id, i),
        })

    # Create a fresh done job in Redis
    job_id = str(uuid.uuid4())
    from api.database import set_job_clips
    create_job(job_id, url=f"recovered:{video_id}", language="te", owner=user.id, ttl_seconds=_tier_ttl(user.id))
    from api.database import update_job
    update_job(job_id, status="done", progress=100, current_stage="Complete", video_id=video_id)
    set_job_clips(job_id, output_clips)

    print(f"  [API] Recovered job {job_id} for video {video_id} with {len(output_clips)} clips")
    return _job_to_out(get_job(job_id))


# ── List the caller's jobs ────────────────────────────────────

@app.get("/jobs", response_model=List[JobOut])
def list_jobs_endpoint(user: AuthUser = Depends(get_current_user)):
    """All pipeline jobs owned by the caller, newest first. Backend-enforced:
    this is the only population the frontend job list displays."""
    return [_job_to_out(j) for j in
            list_jobs_by_owner(user.id, include_ownerless=user.is_dev)]


# ── Poll job status ───────────────────────────────────────────

@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job_endpoint(job_id: str, user: AuthUser = Depends(get_current_user)):
    """Get job status and progress."""
    return _job_to_out(_get_owned_job(job_id, user))


@app.patch("/jobs/{job_id}")
def update_job_endpoint(job_id: str, body: dict, user: AuthUser = Depends(get_current_user)):
    """Update job fields, e.g. notification email."""
    _get_owned_job(job_id, user)
    if "email" in body:
        update_job(job_id, email=body["email"])
    return {"ok": True}


# ── Re-render a clip (new style / format) ────────────────────

@app.post("/jobs/{job_id}/clips/{clip_index}/rerender")
def rerender_clip_endpoint(job_id: str, clip_index: int, payload: RerenderRequest,
                           user: AuthUser = Depends(get_current_user)):
    """
    Re-render a single clip with a new caption style and/or export format.
    Returns a rerender_job_id to poll at /jobs/<rerender_job_id>.
    When done, job will have captioned_path and vertical_path set.
    """
    source_job = _get_owned_job(job_id, user)

    clips = source_job.get("clips", [])
    if clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip index out of range")

    video_id = source_job.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400, detail="No video_id on source job")

    # Image overlay elements may only reference overlay images minted for
    # THIS job's video (fast 422 here; the worker-side resolver re-checks and
    # drops rather than errors — defense in depth, same stance both places).
    from services.overlay_renderer import valid_overlay_image_id
    for el in (payload.elements or []):
        if isinstance(el, dict) and el.get("type") == "image":
            image_id = (el.get("props") or {}).get("image_id")
            if not valid_overlay_image_id(image_id, video_id):
                raise HTTPException(
                    status_code=422,
                    detail="elements: image overlay references an image that "
                           "does not belong to this clip",
                )

    # ── Tier gates (features #17/#18/#21) ─────────────────────────────────────
    # Resolve the caller's plan → entitlements ONCE, at the authenticated API
    # boundary; the worker never does billing lookups (it only receives the
    # resolved `watermark` flag).
    from api import tiers
    from api.database import (
        get_render_minutes_used, get_render_minutes_pack, add_render_minutes,
    )
    plan = get_user_billing(user.id).get("plan", tiers.FREE)

    # #21 — premium presets are export-gated for free tiers (the gallery still
    # shows them; only the export is blocked, nudging an upgrade).
    if tiers.is_premium_preset(payload.style) and not tiers.can_use_premium_presets(plan):
        raise HTTPException(
            status_code=402,
            detail="This caption preset is a paid feature. Upgrade to Creator "
                   "or Studio to export with it.",
        )

    # #18 — render-minute metering. Charge the clip's output minutes against
    # the monthly budget (+ any ₹99 top-up pack); block when exhausted.
    clip_dur = float(clips[clip_index].get("duration") or 0)
    clip_minutes = round(clip_dur / 60.0, 3)
    budget = tiers.render_minutes_budget(plan) + get_render_minutes_pack(user.id)
    used = get_render_minutes_used(user.id)
    if clip_minutes > 0 and used + clip_minutes > budget + 1e-6:
        raise HTTPException(
            status_code=402,
            detail=f"You've used {used:.0f} of {budget:.0f} render minutes this "
                   f"month. Upgrade your plan or buy a top-up pack to export more.",
        )
    add_render_minutes(user.id, clip_minutes)

    # #17 — free tiers get a burned-in watermark; paid tiers pass False.
    watermark = tiers.has_watermark(plan)

    rerender_job_id = str(uuid.uuid4())
    # Owner travels via the job record in Redis, never via the Celery task —
    # the worker only receives ids the API resolved from the verified token.
    create_job(rerender_job_id, url=f"rerender:{job_id}:{clip_index}", language="te",
               owner=user.id)

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
        caption_font_size=payload.caption_font_size,
        caption_pill=payload.caption_pill,
        caption_script=payload.caption_script,
        emphasis_indices=payload.emphasis_indices,
        crop_keyframes=payload.crop_keyframes,
        cut_spans=payload.cut_spans,
        caption_animation=payload.caption_animation,
        watermark=watermark,
    )

    return {"rerender_job_id": rerender_job_id}


# ── Draft save / restore ──────────────────────────────────────

@app.patch("/jobs/{job_id}/clips/{clip_id}/draft")
def save_draft(job_id: str, clip_id: str, payload: dict = Body(...),
               user: AuthUser = Depends(get_current_user)):
    """Persist editor draft state for a clip. Stored in Redis with a 7-day TTL."""
    _get_owned_job(job_id, user)
    get_redis().set(f"draft:{job_id}:{clip_id}", json.dumps(payload), ex=7 * 86400)
    return {"ok": True}


@app.get("/jobs/{job_id}/clips/{clip_id}/draft")
def load_draft(job_id: str, clip_id: str,
               user: AuthUser = Depends(get_current_user)):
    """Return the persisted draft for a clip, or null if none has been saved yet."""
    _get_owned_job(job_id, user)
    raw = get_redis().get(f"draft:{job_id}:{clip_id}")
    return {"draft": json.loads(raw) if raw else None}


# ── Saved caption template ("My Style") ──────────────────────
# ONE named caption style per user, applied by the editor to clips that have
# no draft yet. Stored on the no-TTL user:{id} hash (same layer as billing —
# a saved style must survive job expiry). The payload is opaque editor state,
# validated only for shape and size.

_CAPTION_TEMPLATE_MAX_BYTES = 8192


@app.get("/users/me/caption-template")
def get_caption_template_endpoint(user: AuthUser = Depends(get_current_user)):
    """The caller's saved caption template, or null if none was saved."""
    return {"template": get_user_caption_template(user.id)}


@app.put("/users/me/caption-template")
def put_caption_template_endpoint(payload: dict = Body(...),
                                  user: AuthUser = Depends(get_current_user)):
    """Save (template: object) or delete (template: null) the caller's style."""
    template = payload.get("template")
    if template is not None:
        if not isinstance(template, dict):
            raise HTTPException(status_code=422,
                                detail="template must be an object or null")
        if len(json.dumps(template)) > _CAPTION_TEMPLATE_MAX_BYTES:
            raise HTTPException(status_code=413, detail="template too large")
    set_user_caption_template(user.id, template)
    return {"template": get_user_caption_template(user.id)}


# ── Get transcript for caption overlay ───────────────────────

@app.get("/transcript/{video_id}")
def get_transcript(video_id: str, user: AuthUser = Depends(get_current_user)):
    """Return word timestamps for canvas caption overlay.

    Ownership is by video, not job: storage artifacts are shared per
    video_id, so owning ANY job over this video grants transcript access.

    Tanglish backfill for OLD clips: transcripts saved before the Telugu ⇄
    Tanglish toggle have no `word_tanglish`. Derive it here at serve time
    (deterministic, offline — services/tanglish.py) and persist back to the
    JSON so the cost is paid once per old transcript, not per request. New
    transcriptions already carry it (save_transcript derives at write time).
    Persist failure is non-fatal: the response still carries the derived
    values; we just re-derive next time.
    """
    _require_video_access(video_id, user)
    path = UPLOAD_DIR / f"{video_id}_audio_transcript.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")
    with open(path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    from services.tanglish import ensure_word_tanglish
    if ensure_word_tanglish(transcript):
        try:
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(transcript, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as e:
            print(f"  [Tanglish] Backfill persist failed for {video_id} (serving derived values anyway): {e}")

    return transcript


# ── Transliteration (editable-transcript phonetic typing) ────

@app.post("/transliterate", response_model=TransliterateResponse)
def transliterate(payload: TransliterateRequest,
                  user: AuthUser = Depends(get_current_user)):
    """
    Latin token → Telugu candidate list for the editable transcript's
    phonetic typing (frontend api/transliterate.js adapter).

    Proxies the AI4Bharat IndicXlit sidecar (indicxlit/ container, isolated
    from the ASR env — its fairseq deps must never share this process).
    Same contract as always: ({text, lang} → {suggestions: [...]}).

    GRACEFUL DEGRADE is load-bearing: if the sidecar is down, slow, or
    returns garbage, this endpoint returns {suggestions: []} exactly like
    the old stub — the frontend shows an empty dropdown and typed text
    still commits. Editing must never crash or block on this service.
    """
    import requests

    url = os.getenv("INDICXLIT_URL", "http://localhost:8010").rstrip("/") + "/transliterate"
    try:
        r = requests.post(
            url,
            json={"text": payload.text, "lang": payload.lang},
            timeout=(1.5, 5),  # (connect, read) — a dead sidecar fails fast
        )
        r.raise_for_status()
        raw = r.json().get("suggestions", [])
        suggestions = [s for s in raw if isinstance(s, str) and s.strip()] if isinstance(raw, list) else []
    except Exception:
        suggestions = []
    return TransliterateResponse(suggestions=suggestions)


# ── Telugu → Tanglish derivation (caption toggle edit seam) ──

@app.post("/tanglish", response_model=TanglishResponse)
def tanglish(payload: TanglishRequest,
             user: AuthUser = Depends(get_current_user)):
    """
    Batch Telugu → casual-romanized Tanglish. Deterministic, offline, fast
    (services/tanglish.py — pure rules, no model, no network). The OPPOSITE
    direction from /transliterate above; do not confuse the two.

    Called by the frontend when a word-fix commits new Telugu text, so the
    Tanglish view never shows stale romanization. If this endpoint is
    unreachable the frontend keeps text_tanglish null and falls back to the
    word's stored word_tanglish — editing must never break.
    """
    from services.tanglish import telugu_to_tanglish
    return TanglishResponse(tanglish=[telugu_to_tanglish(w or "") for w in payload.words])


# ── Line-level caption re-alignment (Descript-style line edit) ──

@app.post("/jobs/{job_id}/clips/{clip_index}/realign-line",
          response_model=RealignLineResponse)
def realign_line(job_id: str, clip_index: int, payload: RealignLineRequest,
                 user: AuthUser = Depends(get_current_user)):
    """
    Re-derive per-word karaoke timestamps for ONE caption line whose word
    count changed in the editable transcript. Runs the EXISTING MMS CTC
    forced aligner (services/transcriber.py — the engine that produced the
    original word timing) on just the line's audio span with the new words.

    Contract:
      - line_start/line_end (clip-relative) are the line's FIXED span —
        boundaries never move; timestamps come back inside that span.
      - The user's TEXT is never lost: aligner failure, missing audio, or
        implausible output (zero-length words, count mismatch) degrade to an
        even distribution of the span, flagged approximate=true. This
        endpoint 5xxs only on genuinely broken requests, never on alignment
        trouble — the editor must keep working.
      - word_tanglish is re-derived server-side (same deterministic
        services/tanglish.py path as everywhere else) so the Telugu ⇄
        Tanglish toggle stays correct for realigned lines.
    """
    source_job = _get_owned_job(job_id, user)
    video_id = source_job.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400, detail="No video_id on source job")

    words = [w.strip() for w in payload.words if isinstance(w, str) and w.strip()]
    if not words:
        raise HTTPException(status_code=422,
                            detail="words must contain at least one non-empty token")
    if payload.line_end <= payload.line_start:
        raise HTTPException(status_code=422, detail="line_end must be after line_start")

    # Clip lookup: prefer the pipeline clips JSON (it carries `segments`, which
    # the Redis job clip dict does not — see rerender's warning check); fall
    # back to the job store so a missing file still realigns single-segment.
    clip = None
    clips_path = UPLOAD_DIR / f"{video_id}_audio_clips.json"
    try:
        with open(clips_path, "r", encoding="utf-8") as f:
            clip = json.load(f)["clips"][clip_index]
    except (OSError, KeyError, IndexError, ValueError):
        clips = source_job.get("clips") or []
        if clip_index >= len(clips):
            raise HTTPException(status_code=404, detail="Clip index out of range")
        clip = clips[clip_index]

    # Multi-segment clips stack output time; map the span back to the original
    # video timeline for audio extraction (sentences resolve the segment ids).
    sentences = []
    if len(clip.get("segments") or []) > 1:
        t_path = UPLOAD_DIR / f"{video_id}_audio_transcript.json"
        try:
            with open(t_path, "r", encoding="utf-8") as f:
                sentences = json.load(f).get("sentences", [])
        except (OSError, ValueError):
            sentences = []

    from services.realign_line import realign_line_words, output_time_to_absolute
    abs_start = output_time_to_absolute(payload.line_start, clip, sentences)
    abs_end   = output_time_to_absolute(payload.line_end,   clip, sentences)

    audio_path = UPLOAD_DIR / f"{video_id}_audio.wav"
    aligned, approximate = realign_line_words(
        audio_path, abs_start, abs_end,
        payload.line_start, payload.line_end, words,
    )

    from services.tanglish import telugu_to_tanglish
    return RealignLineResponse(
        words=[RealignedWord(**w, word_tanglish=telugu_to_tanglish(w["word"]))
               for w in aligned],
        approximate=approximate,
    )


# ── Generate clip metadata (title / description / hashtags) ──

@app.post("/jobs/{job_id}/clips/{clip_index}/metadata")
def generate_clip_metadata(job_id: str, clip_index: int, payload: MetadataRequest,
                           user: AuthUser = Depends(get_current_user)):
    """Generate AI title, description, and hashtags for a clip via Gemini."""
    _get_owned_job(job_id, user)
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
def download_clip(path: str, user: AuthUser = Depends(get_current_user)):
    """Download a single clip by file path.

    Ownership: output filenames are `{video_id}_clipN_...`, so the video id
    parsed from the requested basename must belong to a job the caller owns
    (same by-video rule as /transcript). Unparseable names 404 for real
    users; the DEV_MODE identity may fetch anything inside OUTPUT_DIR.

    BUG-002 fix: confine the served path to OUTPUT_DIR. The endpoint takes
    a user-controlled `path` query param (that used to be passed straight to
    FileResponse), so without a containment check any readable file on the
    container could be exfiltrated — including backend/.env with third-party
    API keys. We resolve() both the request path and OUTPUT_DIR (which
    canonicalises `..` and follows symlinks) and require the request to sit
    strictly under the outputs directory. On breach we return 403, not 404,
    so the caller can distinguish "not there" from "you may not touch that".
    """
    try:
        requested = Path(path).resolve()
        base = OUTPUT_DIR.resolve()
    except (OSError, RuntimeError, ValueError):
        # OSError: permission / IO failure while resolving.
        # RuntimeError: pathlib raises for infinite symlink loops.
        # ValueError: pathlib rejects paths with embedded null bytes.
        raise HTTPException(status_code=400, detail="Invalid clip path")

    try:
        requested.relative_to(base)
    except ValueError:
        # requested is not inside base — traversal / absolute-escape attempt.
        raise HTTPException(status_code=403, detail="Path outside outputs directory")

    if not requested.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")

    if not user.is_dev:
        name = requested.name
        file_video_id = name.split("_clip")[0] if "_clip" in name else ""
        _require_video_access(file_video_id, user)

    return FileResponse(
        path=str(requested),
        media_type="video/mp4",
        filename=requested.name,
    )


# ── Helpers ───────────────────────────────────────────────────

def _missing_artifacts(video_id: str, job: dict) -> list:
    """Which artifacts a 'done' job record references but are NOT on disk.

    A cache hit is only safe to return if the files it points at still exist.
    We check the transcript (the editor fetches it to build caption timing) and
    every clip's captioned output file. Returns a list of tokens describing
    what's gone (empty list = everything present → safe to return the cache):
      'transcript'    — the word-timestamp JSON is missing
      'clips'         — the job record carries no clips at all
      'clip_outputs'  — at least one clip's captioned_path file is missing
    """
    missing = []

    transcript_path = UPLOAD_DIR / f"{video_id}_audio_transcript.json"
    if not transcript_path.exists():
        missing.append("transcript")

    clips = job.get("clips", []) or []
    if not clips:
        missing.append("clips")
    else:
        for c in clips:
            captioned = c.get("captioned_path") or ""
            if not captioned or not Path(captioned).exists():
                missing.append("clip_outputs")
                break

    return missing


def _regeneration_stages(video_id: str) -> list:
    """Pipeline stages that must re-run to rebuild missing outputs, given which
    checkpoint files survive on disk. Mirrors process_video's own checkpoint
    guards so the log reflects what the worker will actually do — the whole
    point is to NOT re-run expensive stages whose outputs still exist:

      - download     : only if the source .mp4 is gone
      - transcribe   : only if the transcript JSON is gone (external API credits)
      - select_clips : if the clips JSON is gone, OR we had to re-transcribe
                       (a fresh transcript can renumber sentence ids)
      - cut/crop/caption : always — they're local ffmpeg (no external cost) and
                       we only reach here because some output file is missing.
    """
    transcript_path = UPLOAD_DIR / f"{video_id}_audio_transcript.json"
    clips_json      = UPLOAD_DIR / f"{video_id}_audio_clips.json"
    video_file      = UPLOAD_DIR / f"{video_id}.mp4"

    transcript_missing = not transcript_path.exists()
    clips_missing      = not clips_json.exists()

    stages = []
    if not video_file.exists():
        stages.append("download")
    if transcript_missing:
        stages.append("transcribe")
    if transcript_missing or clips_missing:
        stages.append("select_clips")
    stages += ["cut", "crop", "caption"]
    return stages


def _recover_from_storage(video_id: str, owner: str = "") -> Optional[dict]:
    """
    If clips JSON and output files already exist in storage,
    rebuild a done Redis job without running the pipeline.
    Returns the job dict if recovered, None if files don't exist.
    The recovered job is stamped with `owner` (the caller).
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
            "refined_start":   clip.get("refined_start"),
            "refined_end":     clip.get("refined_end"),
            "refined_segments": clip.get("refined_segments", []),
            "emphasis_indices": clip.get("emphasis_indices", []),
            "raw_path":        str(raw_files[0])       if raw_files       else "",
            "captioned_path":  str(captioned_files[0]) if captioned_files else "",
            "vertical_path":   str(vertical_files[0])  if vertical_files  else "",
            "thumbnail_path":  thumb_path if thumb_path and os.path.exists(thumb_path) else None,
            "default_crop_box": read_default_crop_box(OUTPUT_DIR, video_id, i),
        })

    job_id = str(uuid.uuid4())
    create_job(job_id, url=f"recovered:{video_id}", language="te", owner=owner, ttl_seconds=_tier_ttl(owner))
    update_job(job_id, status="done", progress=100, current_stage="Complete", video_id=video_id)
    set_job_clips(job_id, output_clips)

    return get_job(job_id)


def _extract_video_id(url: str) -> Optional[str]:
    """YouTube URL → video id, or None. Shared with the worker (which keys the
    per-video pipeline lock on it) via services/youtube_utils.py; frontend's
    lib/youtubeUrl.js mirrors the accepted formats."""
    return extract_video_id(url)


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
            refined_start   = c.get("refined_start"),
            refined_end     = c.get("refined_end"),
            refined_segments = c.get("refined_segments", []) or [],
            emphasis_indices = c.get("emphasis_indices", []) or [],
            raw_path        = c.get("raw_path", ""),
            captioned_path  = c.get("captioned_path", ""),
            vertical_path   = c.get("vertical_path", ""),
            thumbnail_path  = c.get("thumbnail_path") or None,
            default_crop_box = c.get("default_crop_box") or None,
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


# ── Billing (PHASE 2 BUILD 2) ─────────────────────────────────
# Razorpay Studio Plan subscriptions. Every user-facing billing route requires
# the SAME auth guard as job routes (get_current_user); the webhook is the one
# exception — Razorpay calls it server-to-server, authenticated by an HMAC
# signature over the raw body instead of a bearer token. See api/billing.py and
# SETUP_BILLING.md. NOTE: no feature is gated here — this only records who is
# paid so a FUTURE feature can check `plan == 'studio'`.

def _billing_status_payload(user: AuthUser) -> BillingStatusOut:
    from api import tiers
    from api.database import get_render_minutes_used, get_render_minutes_pack
    b = get_user_billing(user.id)
    configured = billing.billing_configured()
    plan = b.get("plan", tiers.FREE)
    return BillingStatusOut(
        plan                = plan,
        subscription_status = b.get("subscription_status", ""),
        subscription_id     = b.get("subscription_id", ""),
        configured          = configured,
        plan_info           = PlanInfo(**billing.public_plan_info()) if configured else None,
        # Tier entitlements + live usage (features #17–20).
        watermark             = tiers.has_watermark(plan),
        render_minutes_used   = round(get_render_minutes_used(user.id), 1),
        render_minutes_budget = tiers.render_minutes_budget(plan) + get_render_minutes_pack(user.id),
        expiry_hours          = tiers.expiry_hours(plan),
    )


@app.get("/billing/status", response_model=BillingStatusOut)
def billing_status(user: AuthUser = Depends(get_current_user)):
    """Current plan state for the signed-in user. `configured=False` tells the
    UI to show a 'billing not set up' state instead of an upgrade button."""
    return _billing_status_payload(user)


@app.post("/billing/subscription", response_model=SubscriptionCreateOut)
def create_subscription_endpoint(user: AuthUser = Depends(get_current_user)):
    """Create a Razorpay subscription for the Studio Plan and hand the frontend
    what Checkout.js needs. Records the subscription against the user (and a
    reverse index) so the activation webhook can flip them to paid."""
    if not billing.billing_configured():
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured on this server. See SETUP_BILLING.md.",
        )
    # Serialize create per user: the "already active" guard below is
    # check-then-act, so two concurrent upgrade clicks could both pass it and
    # create two LIVE Razorpay subscriptions — the unstored one keeps charging
    # invisibly. The lock makes the second click fail fast instead.
    if not acquire_billing_create_lock(user.id):
        raise HTTPException(
            status_code=409,
            detail="A subscription request is already in progress. "
                   "Please wait a moment and check your plan status.",
        )
    try:
        # Idempotency: a user with an already-active subscription shouldn't stack a
        # second one. Send them nothing to pay for; the UI reads /billing/status.
        existing = get_user_billing(user.id)
        if existing.get("plan") == billing.STUDIO_PLAN_KEY and existing.get("subscription_status") == "active":
            raise HTTPException(status_code=409, detail="You already have an active Studio Plan subscription.")
        try:
            out = billing.create_studio_subscription(user.id, email=user.email)
        except billing.BillingNotConfigured:
            raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
        except Exception as e:
            print(f"[billing] subscription create failed for {user.id}: {type(e).__name__}: {e}", flush=True)
            raise HTTPException(status_code=502, detail="Could not create the subscription. Please try again.")

        sub_id = out["subscription_id"]
        set_user_billing(user.id, subscription_id=sub_id, subscription_status="created")
        set_subscription_owner(sub_id, user.id)
        return SubscriptionCreateOut(**out)
    finally:
        release_billing_create_lock(user.id)


@app.post("/billing/cancel")
def cancel_subscription_endpoint(user: AuthUser = Depends(get_current_user)):
    """Request cancellation of the user's subscription. The status flip back to
    'free' is confirmed by the subscription.cancelled webhook — this only asks
    Razorpay to cancel."""
    if not billing.billing_configured():
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
    b = get_user_billing(user.id)
    sub_id = b.get("subscription_id")
    if not sub_id or b.get("plan") != billing.STUDIO_PLAN_KEY:
        raise HTTPException(status_code=404, detail="No active subscription to cancel.")
    try:
        billing.cancel_subscription(sub_id)
    except billing.BillingNotConfigured:
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
    except Exception as e:
        print(f"[billing] cancel failed for {user.id} ({sub_id}): {type(e).__name__}: {e}", flush=True)
        raise HTTPException(status_code=502, detail="Could not cancel the subscription. Please try again.")
    # Optimistic local hint; the webhook is authoritative and will confirm.
    set_user_billing(user.id, subscription_status="cancelling")
    return {"ok": True, "subscription_id": sub_id}


@app.post("/billing/webhook")
async def billing_webhook(request: Request):
    """Razorpay subscription webhook. Authenticated by HMAC signature over the
    RAW body (no bearer token). Unsigned/invalid → 400, so a forged call can
    never move plan status. Verified events update the matched user's plan:
      subscription.activated / .charged  → studio / active
      subscription.cancelled              → free / cancelled
      subscription.halted                 → free / halted
    The user is matched by the reverse index (subscription_id → user_id), with
    the subscription's notes.user_id as a fallback.

    Replay/ordering guards (Razorpay retries delivery for up to 24h, and
    delivery is UNORDERED — real money depends on these):
      - event ledger: each x-razorpay-event-id is applied at most once
        (body-hash fallback when the header is absent, since retries resend
        the identical body);
      - created_at high-water mark per subscription: an event older than the
        newest one already applied is acknowledged but changes nothing, so a
        delayed .activated/.charged can't flip a cancelled user back to paid."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not billing.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Malformed webhook body")

    event = payload.get("event", "")
    mapping = billing.plan_state_for_event(event)
    if mapping is None:
        # A subscribed event we don't act on (or an unknown one): acknowledge so
        # Razorpay doesn't retry, but change nothing.
        return {"ok": True, "ignored": event}

    sub_entity = (
        payload.get("payload", {})
        .get("subscription", {})
        .get("entity", {})
    )
    sub_id = sub_entity.get("id", "")
    if not sub_id:
        raise HTTPException(status_code=400, detail="Webhook missing subscription id")

    user_id = get_subscription_owner(sub_id) or (sub_entity.get("notes") or {}).get("user_id")
    if not user_id:
        # We can't match this subscription to a user — acknowledge (so Razorpay
        # stops retrying) but log it; nothing to update.
        print(f"[billing] webhook {event} for unknown subscription {sub_id}", flush=True)
        return {"ok": True, "unmatched": sub_id}

    # ── Replay guard: each event id is applied at most once ──────────────
    event_key = request.headers.get("x-razorpay-event-id", "") \
        or hashlib.sha256(body).hexdigest()
    if not claim_billing_event(event_key):
        print(f"[billing] duplicate webhook {event} ({event_key}) — ignored", flush=True)
        return {"ok": True, "duplicate": event_key}

    try:
        # ── Ordering guard: only apply if not older than the newest applied ──
        created_at = payload.get("created_at")
        last_ts = get_subscription_event_ts(sub_id)
        if created_at is not None and last_ts is not None and int(created_at) < last_ts:
            print(f"[billing] stale webhook {event} for {sub_id} "
                  f"(created_at {created_at} < applied {last_ts}) — ignored", flush=True)
            return {"ok": True, "stale": event}

        plan, status = mapping
        set_user_billing(user_id, plan=plan, subscription_status=status, subscription_id=sub_id)
        # Keep the reverse index fresh (e.g. if only notes matched this time).
        set_subscription_owner(sub_id, user_id)
        if created_at is not None:
            set_subscription_event_ts(sub_id, int(created_at))
        print(f"[billing] {event} → user {user_id} is now {plan}/{status}", flush=True)
        return {"ok": True, "event": event, "plan": plan}
    except HTTPException:
        raise
    except Exception:
        # Processing failed after claiming the event id — un-claim so
        # Razorpay's retry of this same event isn't swallowed as a duplicate.
        release_billing_event(event_key)
        raise