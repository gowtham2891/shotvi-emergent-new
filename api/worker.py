"""
ClipForge AI — Celery Worker
"""

import os
import sys
import json
import uuid
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.database import get_job, update_job, set_job_clips

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


# ══════════════════════════════════════════════════════════════
# Full pipeline task
# ══════════════════════════════════════════════════════════════

@celery_app.task(bind=True, name="process_video")
def process_video(self, job_id: str, url: str, language: str = "te"):
    try:
        from services.video_downloader import download_youtube
        from services.transcriber import transcribe_audio, save_transcript
        from services.clip_selector import select_clips
        from services.video_cutter import cut_all_clips
        from services.vertical_cropper import crop_all_clips
        from services.caption_renderer import render_all_captions

        update_job(job_id, status="downloading", progress=5, current_stage="Downloading video")
        # Local file from POST /jobs/upload — FastAPI and this worker share the
        # filesystem (both run from the repo root on one machine), so the saved
        # path resolves here. YouTube URLs never exist as local paths.
        if Path(url).exists():
            from services.video_downloader import handle_upload
            update_job(job_id, current_stage="Preparing upload")
            result = handle_upload(url, filename=Path(url).stem)
        else:
            result = download_youtube(url)
        video_id   = result["video_id"]
        video_path = result["video_path"]
        audio_path = result["audio_path"]
        update_job(job_id, video_id=video_id, progress=15)

        update_job(job_id, status="transcribing", progress=20, current_stage="Transcribing audio")
        transcript_path = str(UPLOAD_DIR / f"{video_id}_audio_transcript.json")
        if not Path(transcript_path).exists():
            transcript = transcribe_audio(audio_path, language=language)
            save_transcript(transcript, transcript_path)
        update_job(job_id, progress=40)

        update_job(job_id, status="selecting", progress=45, current_stage="Selecting best moments")
        clips_path = str(UPLOAD_DIR / f"{video_id}_audio_clips.json")
        select_clips(transcript_path)
        update_job(job_id, progress=60)

        update_job(job_id, status="cutting", progress=65, current_stage="Cutting clips")
        if OUTPUT_DIR.exists() and video_id:
            for f in OUTPUT_DIR.iterdir():
                if f.is_file() and f.name.startswith(video_id):
                    f.unlink()
                    print(f"  [Cleanup] Removed old file: {f.name}")
        cut_all_clips(clips_path, video_path, str(OUTPUT_DIR))
        update_job(job_id, progress=75)

        update_job(job_id, status="cropping", progress=80, current_stage="Cropping to 9:16")
        crop_all_clips(str(OUTPUT_DIR))
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
            # Raw cut clip (no crop, no captions) — source for re-renders
            raw_files      = [f for f in OUTPUT_DIR.glob(f"{video_id}_clip{i}_*.mp4")
                              if "_vertical" not in f.name and "_captioned" not in f.name and "_captions" not in f.name]
            captioned_file = list(OUTPUT_DIR.glob(f"{video_id}_clip{i}_*bold-yellow_captioned.mp4"))
            if not captioned_file:
                captioned_file = list(OUTPUT_DIR.glob(f"{video_id}_clip{i}_*captioned.mp4"))
            vertical_file  = list(OUTPUT_DIR.glob(f"{video_id}_clip{i}_*_vertical.mp4"))

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
                "raw_path":        str(raw_files[0])      if raw_files      else "",
                "vertical_path":   str(vertical_file[0])  if vertical_file  else "",
                "captioned_path":  str(captioned_file[0]) if captioned_file else "",
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


# ══════════════════════════════════════════════════════════════
# Export task — canvas background + captions
# ══════════════════════════════════════════════════════════════

@celery_app.task(bind=True, name="rerender_clip")
def rerender_clip(self, rerender_job_id: str, source_job_id: str, clip_index: int,
                  style: str, fmt: str, background: str, bg_color: str,
                  use_autocrop: bool, trim_start: float, trim_end: float, video_id: str,
                  transcript_edits=None, crop_box=None, selected_subject=None,
                  crop_mode: str = "auto", elements=None, caption_font=None,
                  caption_x=None, caption_y=None):
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
    - elements: EditDocument overlay elements (progress bar, logo, headline, sticker) burned
      in their own pass before captions; None/[] renders exactly as before this existed
    - caption_font: bundled Telugu caption font (Noto Sans Telugu default, Ramabhadra/Mandali
      selectable); None → default. Resolved deterministically via fontsdir, not host fonts.
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
        if use_autocrop:
            source_path = clip.get("vertical_path", "")
        else:
            source_path = clip.get("raw_path", "")

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
        needs_trim = trim_start > 0 or (trim_end > 0 and trim_end < _get_duration(source_path))

        if needs_crop or needs_trim:
            prepared_path = str(OUTPUT_DIR / f"{out_stem}_prepared.mp4")
            _prepare_source(
                source_path, prepared_path,
                crop_box=crop_box if needs_crop else None,
                trim_start=trim_start if needs_trim else 0,
                trim_end=trim_end    if needs_trim else -1,
            )
            working_path = prepared_path
        else:
            working_path = source_path

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
        )

        if not result:
            raise RuntimeError("Caption burn failed")

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

def _get_duration(path: str) -> float:
    import subprocess
    r = subprocess.run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", path
    ], capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except: return 0.0


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
        # Solid color background
        if background == "white":
            pad_color = "white"
        elif background == "color":
            # Strip # from hex
            pad_color = bg_color.lstrip("#")
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