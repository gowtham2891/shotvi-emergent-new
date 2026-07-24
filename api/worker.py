"""
ClipForge AI — Celery Worker
"""

import os
import re
import sys
import json
import uuid
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.database import (
    get_job, update_job, set_job_clips,
    acquire_video_lock, release_video_lock,
)
from services.youtube_utils import extract_video_id

REDIS_URL  = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("clipforge", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json", result_serializer="json",
    accept_content=["json"], task_track_started=True, worker_prefetch_multiplier=1,
)

UPLOAD_DIR = Path("storage/uploads")
OUTPUT_DIR = Path("storage/outputs")

FORMAT_CONFIG = {
    "9:16":  {"width": 1080, "height": 1920},
    "1:1":   {"width": 1080, "height": 1080},
    "16:9":  {"width": 1920, "height": 1080},
}

BACKGROUND_OPTIONS = ["blur", "black", "white", "color"]

# Filename tokens that only rerender/export artifacts carry (worker.py rerender
# path: *_canvas.mp4, *_overlays.mp4, *_prepared.mp4 and the captioned outputs
# derived from those stems), plus user-uploaded overlay images
# (*_useroverlay_*.png/jpg from POST /jobs/{id}/overlay-images). Pipeline
# cleanup and pipeline output collection must both skip anything carrying one
# of these — a fresh pipeline run may never delete or adopt a user's previous
# export, and may never delete a user's uploaded overlay image.
_RERENDER_MARKERS = ("_canvas", "_overlays", "_prepared", "_useroverlay")


def _is_rerender_artifact(name: str) -> bool:
    return any(m in name for m in _RERENDER_MARKERS)


def read_default_crop_box(output_dir: Path, video_id: str, clip_num: int):
    """Sprint 4: the vertical cropper persists its AI framing as a fractional
    window over the 16:9 master ({x,y,w,h}, 0–1) in a *_vertical.cropbox.json
    sidecar. Adopt it onto the clip record as default_crop_box; None when the
    sidecar is missing (pre-Sprint-4 outputs) or unreadable."""
    sidecars = [f for f in output_dir.glob(f"{video_id}_clip{clip_num}_*_vertical.cropbox.json")
                if not _is_rerender_artifact(f.name)]
    if not sidecars:
        return None
    try:
        box = json.loads(sidecars[0].read_text(encoding="utf-8"))
        if (isinstance(box, dict)
                and all(isinstance(box.get(k), (int, float)) for k in ("x", "y", "w", "h"))):
            return {k: float(box[k]) for k in ("x", "y", "w", "h")}
    except (OSError, ValueError) as e:
        print(f"  [crop_box] ⚠ unreadable sidecar {sidecars[0].name}: {e}")
    return None


# ══════════════════════════════════════════════════════════════
# Full pipeline task
# ══════════════════════════════════════════════════════════════

@celery_app.task(bind=True, name="process_video")
def process_video(self, job_id: str, url: str, language: str = "te", known_video_id: str = None,
                  is_upload: bool = False):
    """Full pipeline. Checkpoint-based: each stage's output on disk lets a
    re-run skip it. This is what makes stale-cache regeneration cheap — when
    POST /jobs finds a 'done' job whose output files were deleted, it re-runs
    this task with known_video_id so surviving checkpoints (crucially the
    transcript, which costs external API credits, and the Gemini clip
    selection) are REUSED and only the missing local ffmpeg stages re-run.

    known_video_id: when set and the source .mp4 is still on disk, the
    download+transcribe+select stages are skipped where their outputs survive.
    None (the normal first-run path) → download derives the id as before.

    is_upload: True ONLY when enqueued by POST /jobs/upload with a path the
    API itself just wrote under storage/uploads. The worker never infers
    "local file" from disk existence — an attacker-supplied path that happens
    to exist must not be treated as the caller's upload.
    """
    # ── Per-video lock ────────────────────────────────────────────────────
    # Storage artifacts are keyed by video_id and shared between runs, so two
    # concurrent pipelines over the same video corrupt each other (cleanup
    # unlinks files the other run is still writing). Held for the whole run;
    # a second submission while in flight fails fast with a clear error.
    lock_video_id = known_video_id or (
        Path(url).stem if is_upload else extract_video_id(url)
    )
    if lock_video_id and not acquire_video_lock(lock_video_id, job_id):
        update_job(job_id, status="failed", current_stage="Failed",
                   error="This video is already being processed by another job. "
                         "Wait for it to finish, then try again.")
        return
    try:
        from services.video_downloader import download_youtube
        from services.transcriber import transcribe_audio, save_transcript
        from services.clip_selector import select_clips
        from services.video_cutter import cut_all_clips
        from services.vertical_cropper import crop_all_clips
        from services.caption_renderer import render_all_captions

        update_job(job_id, status="downloading", progress=5, current_stage="Downloading video")
        # ── Download (or reuse a surviving source) ────────────────────────────
        # Regeneration checkpoint: if the original source .mp4 is still on disk
        # for known_video_id, skip the (network) download entirely. Re-extract
        # the audio only if it too was deleted (cheap local ffmpeg) and only
        # when a later stage will actually need it (transcription).
        reuse_source = None
        if known_video_id and (UPLOAD_DIR / f"{known_video_id}.mp4").exists():
            reuse_source = str(UPLOAD_DIR / f"{known_video_id}.mp4")

        if reuse_source:
            video_id   = known_video_id
            video_path = reuse_source
            audio_path = str(UPLOAD_DIR / f"{video_id}_audio.wav")
            print(f"  [Resume] Reusing downloaded source for {video_id} — skipping download", flush=True)
        elif is_upload:
            # Local file from POST /jobs/upload — FastAPI and this worker share the
            # filesystem (both run from the repo root on one machine), so the saved
            # path resolves here. Trust the explicit flag, never bare existence,
            # and require the path to actually live under storage/uploads so a
            # forged task payload can't read arbitrary server files.
            upload_path = Path(url).resolve()
            if (not upload_path.is_file()
                    or UPLOAD_DIR.resolve() not in upload_path.parents):
                raise ValueError("Upload source path is missing or outside storage/uploads")
            from services.video_downloader import handle_upload
            update_job(job_id, current_stage="Preparing upload")
            result = handle_upload(str(upload_path), filename=upload_path.stem)
            video_id   = result["video_id"]
            video_path = result["video_path"]
            audio_path = result["audio_path"]
        else:
            result = download_youtube(url)
            video_id   = result["video_id"]
            video_path = result["video_path"]
            audio_path = result["audio_path"]
        update_job(job_id, video_id=video_id, progress=15)

        update_job(job_id, status="transcribing", progress=20, current_stage="Transcribing audio")
        transcript_path = str(UPLOAD_DIR / f"{video_id}_audio_transcript.json")
        # Transcription checkpoint: reuse an existing transcript (external API
        # credits) rather than re-transcribing. did_transcribe drives whether we
        # must also re-select clips below (a fresh transcript can renumber
        # sentence ids, invalidating an old clip selection).
        did_transcribe = False
        if not Path(transcript_path).exists():
            if not Path(audio_path).exists():
                from services.video_downloader import extract_audio
                update_job(job_id, current_stage="Re-extracting audio")
                extract_audio(video_path, audio_path)
            transcript = transcribe_audio(audio_path, language=language)
            save_transcript(transcript, transcript_path)
            did_transcribe = True
        else:
            print(f"  [Resume] Reusing existing transcript for {video_id} — skipping transcription", flush=True)
        update_job(job_id, progress=40)

        update_job(job_id, status="selecting", progress=45, current_stage="Selecting best moments")
        clips_path = str(UPLOAD_DIR / f"{video_id}_audio_clips.json")
        # Clip-selection checkpoint: reuse an existing clip selection (Gemini
        # credits) UNLESS we just re-transcribed (which can shift sentence ids).
        if did_transcribe or not Path(clips_path).exists():
            select_clips(transcript_path)
        else:
            print(f"  [Resume] Reusing existing clip selection for {video_id} — skipping selection", flush=True)
        update_job(job_id, progress=60)

        update_job(job_id, status="cutting", progress=65, current_stage="Cutting clips")
        # Scoped cleanup: only THIS video's pipeline artifacts (raw cuts,
        # verticals, pipeline captions/thumbs — everything the stages below
        # regenerate). The old bare `startswith(video_id)` glob also deleted
        # rerender exports and, worse, other videos whose id shares a prefix.
        # `{video_id}_clip` scopes to pipeline naming; rerender artifacts are
        # excluded by marker. Safe against concurrent runs because we hold the
        # per-video lock for the whole pipeline.
        if OUTPUT_DIR.exists() and video_id:
            for f in OUTPUT_DIR.iterdir():
                if (f.is_file()
                        and f.name.startswith(f"{video_id}_clip")
                        and not _is_rerender_artifact(f.name)):
                    f.unlink()
                    print(f"  [Cleanup] Removed old file: {f.name}")
        cut_all_clips(clips_path, video_path, str(OUTPUT_DIR))
        update_job(job_id, progress=75)

        update_job(job_id, status="cropping", progress=80, current_stage="Cropping to 9:16")
        crop_all_clips(str(OUTPUT_DIR), video_id=video_id)
        update_job(job_id, progress=90)

        update_job(job_id, status="captioning", progress=92, current_stage="Burning captions")
        render_all_captions(
            transcript_path=transcript_path,
            clips_path=clips_path,
            clips_dir=str(OUTPUT_DIR),
        )

        with open(clips_path, "r", encoding="utf-8") as f:
            clips_data = json.load(f)

        output_clips = []
        for i, clip in enumerate(clips_data.get("clips", []), 1):
            # Raw cut clip (no crop, no captions) — source for re-renders.
            # Rerender exports now SURVIVE cleanup, so every glob here must
            # exclude them or a previous export gets adopted as this run's output.
            raw_files      = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{i}_*.mp4")
                              if "_vertical" not in f.name and "_captioned" not in f.name
                              and "_captions" not in f.name and not _is_rerender_artifact(f.name)]
            captioned_file = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{i}_*bold-yellow_captioned.mp4")
                              if not _is_rerender_artifact(f.name)]
            if not captioned_file:
                captioned_file = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{i}_*captioned.mp4")
                                  if not _is_rerender_artifact(f.name)]
            vertical_file  = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{i}_*_vertical.mp4")
                              if not _is_rerender_artifact(f.name)]

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
                "emoji_suggestions": clip.get("emoji_suggestions", []),
                "raw_path":        str(raw_files[0])      if raw_files      else "",
                "vertical_path":   str(vertical_file[0])  if vertical_file  else "",
                "captioned_path":  str(captioned_file[0]) if captioned_file else "",
                "default_crop_box": read_default_crop_box(OUTPUT_DIR, video_id, i),
            })

        set_job_clips(job_id, output_clips)
        update_job(job_id, status="done", progress=100, current_stage="Complete")

        job = get_job(job_id)
        if job and job.get("email"):
            try:
                from api.email import send_clips_ready_email
                send_clips_ready_email(
                    to_email=job["email"],
                    job_id=job_id,
                    clip_count=len(output_clips),
                )
            except Exception as e:
                print(f"[email] Failed to send completion email: {e}")

    except Exception as e:
        update_job(job_id, status="failed", error=str(e), current_stage="Failed")
        raise
    finally:
        if lock_video_id:
            release_video_lock(lock_video_id, job_id)


def select_rerender_source(clip: dict, use_autocrop: bool, crop_mode: str, crop_box):
    """Sprint 4 source selection — THE byte-identical guarantee lives here.

    A manual crop window (crop_mode='manual' + crop_box) renders from the
    16:9 master (raw_path): crop_box is a fractional window over the master
    and _prepare_source applies it upstream of _apply_canvas. Everything
    else — crucially the untouched-crop 9:16 default, whose payload carries
    crop_mode='auto' and no crop_box exactly as before this sprint — keeps
    reading the SAME pre-baked vertical_path through the same chain, so its
    output stays byte-identical. Falls back to vertical when a legacy clip
    record has no raw_path (crop_box fractions then apply to the vertical;
    the frontend previews over the same file, so both sides still agree).
    """
    if crop_mode == "manual" and crop_box:
        return clip.get("raw_path", "") or clip.get("vertical_path", "")
    if use_autocrop:
        return clip.get("vertical_path", "")
    return clip.get("raw_path", "")


# ══════════════════════════════════════════════════════════════
# Export task — canvas background + captions
# ══════════════════════════════════════════════════════════════

@celery_app.task(bind=True, name="rerender_clip")
def rerender_clip(self, rerender_job_id: str, source_job_id: str, clip_index: int,
                  style: str, fmt: str, background: str, bg_color: str,
                  use_autocrop: bool, trim_start: float, trim_end: float, video_id: str,
                  transcript_edits=None, crop_box=None, selected_subject=None,
                  crop_mode: str = "auto", elements=None, caption_font=None,
                  caption_x=None, caption_y=None,
                  caption_font_size=None, caption_pill=None,
                  caption_script: str = "telugu", emphasis_indices=None,
                  crop_keyframes=None, cut_spans=None,
                  caption_animation: str = "karaoke", watermark: bool = False):
    """
    Export a single clip with:
    - Source: auto-cropped vertical OR original cut
    - Format: 9:16 / 1:1 / 16:9
    - Background: blur / black / white / color (for letterbox)
    - Caption style: any of 11 styles
    - Trim: start/end offsets
    - transcript_edits: {mergedGroups, lineSplits, wordEdits} applied before caption render
    - crop_box: {x,y,w,h} fractions applied when crop_mode='manual' regardless of format
    - selected_subject: informational only (face re-tracking on pre-cropped source not implemented)
    - elements: EditDocument overlay elements (progress bar, logo, headline) burned
      in their own pass before captions; None/[] renders exactly as before this existed.
      Unknown/retired types (e.g. an old draft's sticker) are skipped with a warning.
    - caption_font: bundled Telugu caption font (Noto Sans Telugu default, Ramabhadra/Mandali
      selectable); None → default. Resolved deterministically via fontsdir, not host fonts.
    - caption_font_size (BUG-001 partial): 0-1 fraction of video height; None → the preset
      default (byte-identical to today). Multiplied on top of the calibrated per-font k-values;
      the calibration itself is spec (Noto 0.495, Ramabhadra/Mandali 0.660).
    - caption_pill (BUG-001 partial): {enabled, color '#rrggbb', opacity, padding, radius}.
      None or enabled=False → the preset's own back_color renders; a set pill overrides
      the ASS BorderStyle+BackColour combo for the current burn.
    - caption_script: 'telugu' (default) or 'tanglish' — which script the caption text
      renders in. Tanglish burns word_tanglish through the SAME ASS path (fonts,
      k-values, \\an5\\pos, timing all unchanged); anything else falls back to telugu.
    - emphasis_indices (feature #6): clip-local word indices to emphasize in the
      burn. None (old payloads) → the clip's own Gemini-tagged set; an explicit
      list — including [] — is the editor's final say.
    - crop_keyframes (feature #13): [{time,x,y,w,h}] centered-zoom keyframes for
      animated punch-ins. None/[] → no zoom stage, byte-identical to before.
    - cut_spans (feature #14): [[start,end], ...] clip-local seconds to remove
      (filler/silence). Applied FIRST; trim/zoom/caption timings remap onto the
      shortened timeline. None/[] → no cuts, byte-identical to before.
    """
    try:
        from services.caption_renderer import render_captions_for_clip, STYLES, DEFAULT_STYLE
        from services.overlay_renderer import render_elements
        import subprocess

        if selected_subject:
            print(f"  [Export] selected_subject={selected_subject!r} noted; "
                  f"face re-tracking not applied to pre-cropped source")

        update_job(rerender_job_id, status="cropping", progress=10,
                   current_stage="Preparing canvas")

        source_job = get_job(source_job_id)
        clips      = source_job.get("clips", [])
        clip       = clips[clip_index]

        transcript_path = str(UPLOAD_DIR / f"{video_id}_audio_transcript.json")
        clips_path      = str(UPLOAD_DIR / f"{video_id}_audio_clips.json")

        # ── Choose source clip ────────────────────────────────
        source_path = select_rerender_source(clip, use_autocrop, crop_mode, crop_box)

        if not source_path or not Path(source_path).exists():
            # Fallback — find any base clip
            clip_num   = clip_index + 1
            candidates = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{clip_num}_*.mp4")
                         if "_captioned" not in f.name and "_captions" not in f.name]
            if not candidates:
                raise FileNotFoundError(f"No source clip found for clip {clip_num}")
            source_path = str(candidates[0])

        print(f"  [Export] Source: {source_path}")
        print(f"  [Export] Format: {fmt}, BG: {background}, Style: {style}, "
              f"CropMode: {crop_mode}, AutoCrop: {use_autocrop}")

        # ── Filler/silence removal (feature #14) — FIRST transformation ───────
        # Cuts are clip-local [start,end] spans; dropping them shortens the
        # timeline, so every OTHER time-based input (trim handles, auto-zoom
        # keyframes, caption words) must be remapped onto the post-cut timeline.
        # The cut file becomes the new source for the rest of the chain.
        if cut_spans:
            from services.filler_removal import remap_time_after_cuts
            _clip_dur = _get_duration(source_path)
            _cut_stem = Path(source_path).stem
            cut_out = str(OUTPUT_DIR / f"{_cut_stem}_{rerender_job_id[:8]}_cut.mp4")
            new_source = _apply_cuts(source_path, cut_out, cut_spans, _clip_dur)
            if new_source != source_path:
                source_path = new_source
                # Remap trim handles + zoom keyframe times through the cuts.
                if trim_start and trim_start > 0:
                    trim_start = remap_time_after_cuts(trim_start, cut_spans)
                if trim_end and trim_end > 0:
                    trim_end = remap_time_after_cuts(trim_end, cut_spans)
                if crop_keyframes:
                    crop_keyframes = [
                        {**k, "time": remap_time_after_cuts(k.get("time", 0), cut_spans)}
                        for k in crop_keyframes
                    ]
                print(f"  [Export] Source after cuts: {source_path}")

        safe_style = style.replace(":", "_")
        safe_fmt   = fmt.replace(":", "_")
        safe_bg    = background.replace("#", "")
        out_stem   = Path(source_path).stem
        # Output filenames are otherwise derived purely from export settings,
        # so re-exporting with identical settings overwrote the same path —
        # this suffix makes every rerender's output unique on disk, not just
        # cache-busted client-side.
        job_suffix = rerender_job_id[:8]

        # ── Prepare source: crop + trim in a single FFmpeg pass ───────────────
        # crop_mode='manual' triggers crop regardless of format or use_autocrop.
        needs_crop = (crop_mode == "manual" and crop_box is not None)
        # trim_end < 0 sentinel means "no trim / to end of clip". When we know
        # the duration, we further clamp `trim_end > 0 and trim_end < duration`
        # to avoid an FFmpeg failure on an out-of-range -t. If duration is None
        # (ffprobe failed — BUG-004), we treat it as "duration unknown" and
        # opt to NOT clamp (previous behaviour: 0.0 collapsed every trim to
        # zero length). This preserves the user's intent when the source is
        # trimmable and skips silently only on the safest edge case.
        _dur = _get_duration(source_path)
        if _dur is None:
            print(f"  [Export] duration unknown for {source_path!r}; skipping "
                  f"the trim_end clamp (BUG-004: better to over-trim and hit "
                  f"an FFmpeg error than to silently drop the entire clip)",
                  flush=True)
            needs_trim = trim_start > 0 or trim_end > 0
        else:
            needs_trim = trim_start > 0 or (trim_end > 0 and trim_end < _dur)

        if needs_crop or needs_trim:
            # job_suffix like every other rerender artifact — without it, two
            # concurrent re-exports of the same clip collide on this file.
            prepared_path = str(OUTPUT_DIR / f"{out_stem}_{job_suffix}_prepared.mp4")
            _prepare_source(
                source_path, prepared_path,
                crop_box=crop_box if needs_crop else None,
                trim_start=trim_start if needs_trim else 0,
                trim_end=trim_end    if needs_trim else -1,
            )
            working_path = prepared_path
        else:
            working_path = source_path

        # ── Auto-zoom / punch-ins (feature #13) ───────────────────────────────
        # Animated crop on the reframed source, BEFORE the canvas stage so the
        # zoom happens on the content and the bg/letterbox wraps the result.
        # No-op passthrough (returns working_path unchanged) when there are no
        # keyframes — a zoom-free export is byte-identical to before.
        if crop_keyframes:
            update_job(rerender_job_id, progress=25, current_stage="Applying auto-zoom")
            zoom_out = str(OUTPUT_DIR / f"{out_stem}_{job_suffix}_zoom.mp4")
            working_path = _apply_crop_keyframes(working_path, zoom_out, crop_keyframes)

        update_job(rerender_job_id, progress=30, current_stage="Applying canvas")

        # ── Apply canvas (format + background) ───────────────
        fmt_cfg   = FORMAT_CONFIG.get(fmt, FORMAT_CONFIG["9:16"])
        target_w  = fmt_cfg["width"]
        target_h  = fmt_cfg["height"]

        canvas_out = str(OUTPUT_DIR / f"{out_stem}_{safe_fmt}_{safe_bg}_{job_suffix}_canvas.mp4")
        _apply_canvas(working_path, canvas_out, target_w, target_h, background, bg_color)

        # ── Burn overlay elements (progress bar; logo/headline/sticker in
        # later stages) — its own pass, before captions, so the existing
        # caption path is never touched by this. No-op-safe: returns
        # canvas_out unchanged if there's nothing supported to burn.
        update_job(rerender_job_id, progress=45, current_stage="Applying overlays")
        overlay_out = str(OUTPUT_DIR / f"{out_stem}_{safe_fmt}_{safe_bg}_{job_suffix}_overlays.mp4")
        # User image overlays: opaque image_id → validated absolute path,
        # pinned to THIS job's video_id (see resolve_image_overlays). Pure
        # identity when no image elements are present.
        from services.overlay_renderer import resolve_image_overlays
        elements = resolve_image_overlays(elements, video_id, str(OUTPUT_DIR))
        pre_caption_path = render_elements(canvas_out, overlay_out, elements, target_w, target_h)

        update_job(rerender_job_id, progress=60, current_stage="Burning captions")

        # ── Burn captions (with transcript edits applied) ─────────────────────
        # Commit 4: caption positioning uses a SINGLE code path (\an5\pos on every
        # event) — untouched captions fall back to the frontend default anchor,
        # dragged captions carry their exact (caption_x, caption_y). Either way,
        # the burn needs the real render dimensions so \pos + PlayRes land at
        # literal output pixels on every format (was 9:16-only before Commit 4).
        result = render_captions_for_clip(
            transcript_path=transcript_path,
            clips_path=clips_path,
            clip_index=clip_index,
            vertical_clip_path=pre_caption_path,
            output_dir=str(OUTPUT_DIR),
            style_name=style if style in STYLES else DEFAULT_STYLE,  # TODO: dead fallback once all styles live in caption_renderer.py::STYLES; authoritative warning is there
            transcript_edits=transcript_edits,
            caption_font=caption_font,
            caption_x=caption_x,
            caption_y=caption_y,
            video_width=target_w,
            video_height=target_h,
            caption_font_size=caption_font_size,
            caption_pill=caption_pill,
            caption_script=caption_script,
            emphasis_indices=emphasis_indices,
            cut_spans=cut_spans,
            animation=caption_animation,
        )

        if not result:
            raise RuntimeError("Caption burn failed")

        # Feature #17 — free-tier watermark on the FINAL export. Paid tiers
        # pass watermark=False (computed from the owner's plan at the API
        # boundary), so their output is byte-identical to before this existed.
        if watermark:
            update_job(rerender_job_id, progress=96, current_stage="Adding watermark")
            wm_out = str(OUTPUT_DIR / f"{Path(result).stem}_wm.mp4")
            result = _apply_watermark(result, wm_out)

        # Surface multi-segment edit-skip warning in job status (only when
        # mergedGroups/lineSplits are present — wordEdits are now applied normally).
        # NOTE: clip (from job store) has no 'segments' field — must read from clips_path.
        extra_fields: dict = {}
        if transcript_edits:
            _te = transcript_edits if isinstance(transcript_edits, dict) else {}
            print(f"  [Export] transcript_edits type={type(transcript_edits).__name__} "
                  f"mergedGroups={_te.get('mergedGroups')} lineSplits={_te.get('lineSplits')}",
                  flush=True)
            if _te.get('mergedGroups') or _te.get('lineSplits'):
                try:
                    with open(clips_path, "r", encoding="utf-8") as _f:
                        _raw_clip_segs = json.load(_f)["clips"][clip_index].get("segments", [])
                    print(f"  [Export] clip_index={clip_index} segments in file: {len(_raw_clip_segs)}",
                          flush=True)
                    if len(_raw_clip_segs) > 1:
                        extra_fields["warnings"] = json.dumps(["transcript_edits_skipped_multi_segment"])
                except Exception as _seg_exc:
                    print(f"  [Export] ⚠ could not read clip segments for warning check: {_seg_exc}",
                          flush=True)

        update_job(rerender_job_id,
                   status="done", progress=100, current_stage="Complete",
                   video_id=video_id, captioned_path=result, vertical_path=pre_caption_path,
                   **extra_fields)

        print(f"  [Export] ✓ Done: {result}")

    except Exception as e:
        update_job(rerender_job_id, status="failed", error=str(e), current_stage="Failed")
        raise


# ══════════════════════════════════════════════════════════════
# FFmpeg helpers
# ══════════════════════════════════════════════════════════════

def _get_duration(path: str):
    """Return the source's duration in seconds via ffprobe, or None if
    duration is unknown (BUG-004 fix).

    Historically this function had a bare `except: return 0.0` which
    swallowed every failure — missing ffprobe binary, unreadable file,
    subprocess timeout, malformed metadata — and returned 0.0. Callers used
    the returned value in a `min(clip.end, duration)` clamp, so an ffprobe
    failure silently collapsed every trim to zero length with no log and no
    job failure. Now we narrow the except to the concrete failure modes,
    log the specific failure, and return None so callers can detect and
    handle "duration unknown" explicitly (skip clamp, warn, etc).
    """
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        # ffprobe not on PATH, or process failed to start / timed out.
        print(f"  [_get_duration] ffprobe unavailable / failed for {path!r}: {e}",
              flush=True)
        return None
    out = r.stdout.strip()
    try:
        return float(out)
    except (ValueError, TypeError) as e:
        print(f"  [_get_duration] could not parse duration from ffprobe stdout "
              f"{out!r} (stderr: {r.stderr[-200:]!r}): {e}",
              flush=True)
        return None


def _get_dimensions_fps(path: str):
    """(width, height, fps) of the first video stream via ffprobe, or
    (None, None, None) on any failure. fps is parsed from the r_frame_rate
    'num/den' rational. Mirrors _get_duration's narrow-except discipline."""
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        print(f"  [_get_dimensions_fps] ffprobe unavailable/failed for {path!r}: {e}", flush=True)
        return None, None, None
    parts = r.stdout.strip().split(",")
    if len(parts) < 3:
        print(f"  [_get_dimensions_fps] unexpected ffprobe output {r.stdout!r}", flush=True)
        return None, None, None
    try:
        w = int(parts[0]); h = int(parts[1])
        num, den = parts[2].split("/")
        fps = float(num) / float(den) if float(den) else float(num)
        return w, h, fps
    except (ValueError, ZeroDivisionError, TypeError) as e:
        print(f"  [_get_dimensions_fps] parse failed on {r.stdout!r}: {e}", flush=True)
        return None, None, None


def _apply_crop_keyframes(input_path: str, output_path: str, crop_keyframes: list) -> str:
    """Feature #13 — animated punch-in zoom via a single FFmpeg zoompan pass.

    crop_keyframes: [{time, x, y, w, h}] centered-zoom fractions
    (services/auto_zoom.py). Returns output_path when a zoom was applied, or
    the ORIGINAL input_path (no re-encode) when there's nothing to zoom — so a
    zoom-free export stays byte-identical to before this stage existed.
    """
    if not crop_keyframes:
        return input_path
    from services.auto_zoom import build_zoompan_filter
    import subprocess

    w, h, fps = _get_dimensions_fps(input_path)
    if not (w and h and fps):
        print(f"  [AutoZoom] ⚠ could not probe {input_path!r} — skipping zoom", flush=True)
        return input_path

    vf = build_zoompan_filter(crop_keyframes, w, h, fps)
    if not vf:
        print("  [AutoZoom] keyframes describe no zoom — skipping", flush=True)
        return input_path

    print(f"  [AutoZoom] {len(crop_keyframes)} keyframe(s) → zoompan ({w}x{h}@{fps:.2f}fps)", flush=True)
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-c:a", "copy", "-preset", "fast", "-crf", "23",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        # Never fail the whole export over a cosmetic zoom — fall back to the
        # un-zoomed source and warn.
        print(f"  [AutoZoom] ⚠ zoompan failed ({r.stderr[-300:]}) — using un-zoomed source", flush=True)
        return input_path
    return output_path


def _apply_watermark(input_path: str, output_path: str, text: str = "Shotvi") -> str:
    """Feature #17 — burn a semi-transparent text watermark (bottom-right) for
    free-tier exports. Returns output_path on success, or the ORIGINAL
    input_path on any failure (a watermark must never fail the export).
    Uses a bundled caption font (Latin glyphs, clean filename) so drawtext
    never depends on host fonts.
    """
    import subprocess
    from services.fonts import CAPTION_FONTS
    font = CAPTION_FONTS["Noto Sans Telugu"].replace("\\", "/")
    font = re.sub(r"^([A-Za-z]):/", r"\1\\:/", font)  # escape drive colon for the filter
    safe_text = str(text).replace("\\", "").replace("'", "").replace(":", "")
    vf = (f"drawtext=fontfile='{font}':text='{safe_text}':fontcolor=white@0.55:"
          f"fontsize=h/26:x=w-tw-20:y=h-th-20:"
          f"shadowcolor=black@0.5:shadowx=2:shadowy=2")
    cmd = [
        "ffmpeg", "-y", "-i", input_path, "-vf", vf,
        "-c:v", "libx264", "-c:a", "copy", "-preset", "fast", "-crf", "23",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        print(f"  [Watermark] ⚠ drawtext failed ({r.stderr[-300:]}) — un-watermarked", flush=True)
        return input_path
    print("  [Watermark] applied (free tier)", flush=True)
    return output_path


def _apply_cuts(input_path: str, output_path: str, cut_spans: list, duration: float) -> str:
    """Feature #14 — drop filler/silence spans via a single trim/concat pass.

    Returns output_path when cuts were applied, or the ORIGINAL input_path
    (no re-encode) when there's nothing to cut — so a cut-free export stays
    byte-identical. Never fails the export over cuts: on error, returns the
    un-cut source and warns.
    """
    if not cut_spans:
        return input_path
    from services.filler_removal import build_cut_filtergraph
    import subprocess

    if not duration or duration <= 0:
        duration = _get_duration(input_path)
    if not duration or duration <= 0:
        print(f"  [Cuts] ⚠ unknown duration for {input_path!r} — skipping cuts", flush=True)
        return input_path

    fg = build_cut_filtergraph(cut_spans, duration)
    if not fg:
        print("  [Cuts] spans remove nothing — skipping", flush=True)
        return input_path

    print(f"  [Cuts] removing {len(cut_spans)} span(s) via trim/concat", flush=True)
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", fg, "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-c:a", "aac", "-preset", "fast", "-crf", "23",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        print(f"  [Cuts] ⚠ cut render failed ({r.stderr[-300:]}) — using un-cut source", flush=True)
        return input_path
    return output_path


def _trim_clip(input_path: str, output_path: str, start: float, end: float):
    import subprocess
    duration = end - start
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ss", str(start), "-t", str(duration),
        "-c:v", "libx264", "-c:a", "aac", "-preset", "fast", output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Trim failed: {r.stderr[-200:]}")


def _prepare_source(input_path: str, output_path: str,
                    crop_box=None, trim_start: float = 0, trim_end: float = -1):
    """
    Single FFmpeg pass combining optional crop and optional trim.
    Avoids double-encoding by merging both operations.
    crop_box: {x, y, w, h} as fractions of source dimensions (0–1).
    """
    import subprocess
    cmd = ["ffmpeg", "-y"]
    if trim_start > 0:
        cmd += ["-ss", str(trim_start)]
    cmd += ["-i", input_path]
    if trim_end > 0 and trim_end > trim_start:
        cmd += ["-t", str(trim_end - trim_start)]

    if crop_box:
        x, y, w, h = crop_box["x"], crop_box["y"], crop_box["w"], crop_box["h"]
        vf = f"crop=in_w*{w}:in_h*{h}:in_w*{x}:in_h*{y}"
        cmd += ["-vf", vf, "-c:v", "libx264", "-c:a", "aac", "-preset", "fast"]
    else:
        # Trim only — stream copy is fast and lossless
        cmd += ["-c:v", "copy", "-c:a", "copy"]

    cmd.append(output_path)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"Prepare failed: {r.stderr[-300:]}")


def _apply_canvas(input_path: str, output_path: str,
                  target_w: int, target_h: int,
                  background: str, bg_color: str = "#000000"):
    """
    Place video on a canvas of target_w x target_h.
    Background options:
      blur  — blurred + scaled version of the video itself
      black — solid black
      white — solid white
      color — solid custom color (bg_color hex)
    Video is scaled to fit (letterboxed) and centered.
    """
    import subprocess

    # Scale video to fit inside canvas (maintain aspect ratio)
    scale_filter = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease"
    pad_filter   = f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black@0"

    if background == "blur":
        # Blurred bg: scale+blur the input, overlay the fitted video on top
        vf = (
            f"[0:v]scale={target_w}:{target_h},boxblur=20:5[bg];"
            f"[0:v]{scale_filter}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-filter_complex", vf,
            "-c:v", "libx264", "-c:a", "aac", "-preset", "fast", "-crf", "23",
            output_path
        ]
    else:
        # Solid color background.
        # BUG-007 fix: FFmpeg's `color=` filter parameter needs `#RRGGBB`,
        # `0xRRGGBB`, or a named color. The previous code stripped `#` and
        # passed a bare `rrggbb`, which FFmpeg interpreted as an unknown color
        # NAME and rejected. Rebuild as `0x`-prefixed after the API-boundary
        # regex already guaranteed it is a 6-hex-digit triple.
        if background == "white":
            pad_color = "white"
        elif background == "color":
            pad_color = "0x" + bg_color.lstrip("#")
        else:
            pad_color = "black"

        vf  = f"{scale_filter},pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color={pad_color}"
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-c:a", "aac", "-preset", "fast", "-crf", "23",
            output_path
        ]

    print(f"  [Canvas] {background} {target_w}x{target_h}")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"Canvas FFmpeg failed: {r.stderr[-300:]}")