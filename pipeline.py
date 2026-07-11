"""
ClipForge AI — Pipeline Orchestrator
=====================================
Single entry point. Chains all 6 modules in order:
  URL/MP4 → Download → Transcribe → Select Clips → Cut → Crop → Caption

Usage:
    python pipeline.py --url https://www.youtube.com/watch?v=XXXXX
    python pipeline.py --file /path/to/video.mp4
    python pipeline.py --url <url> --language hi
    python pipeline.py --url <url> --resume VIDEO_ID   # Resume from last checkpoint
    python pipeline.py --url <url> --force             # Re-run all stages

Checkpointing:
    Each completed stage saves state to storage/uploads/<video_id>_checkpoint.json
    Re-running the same video skips already-completed stages automatically.
    Use --force to wipe checkpoint and start fresh.
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── make sure services/ is importable ─────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

UPLOAD_DIR = Path("storage/uploads")
OUTPUT_DIR = Path("storage/outputs")

# ── stage keys ─────────────────────────────────────────────────────────────────
STAGE_DOWNLOAD   = "download"
STAGE_TRANSCRIBE = "transcribe"
STAGE_SELECT     = "select"
STAGE_CUT        = "cut"
STAGE_CROP       = "crop"
STAGE_CAPTION    = "caption"

STAGES = [STAGE_DOWNLOAD, STAGE_TRANSCRIBE, STAGE_SELECT, STAGE_CUT, STAGE_CROP, STAGE_CAPTION]


# ══════════════════════════════════════════════════════════════════════════════
# State container
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineState:
    video_id: str = ""
    video_path: str = ""
    audio_path: str = ""
    transcript_path: str = ""
    clips_path: str = ""
    raw_clip_paths: list = field(default_factory=list)
    vertical_clip_paths: list = field(default_factory=list)
    captioned_clip_paths: list = field(default_factory=list)
    completed_stages: list = field(default_factory=list)
    failed_stage: Optional[str] = None
    total_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "video_path": self.video_path,
            "audio_path": self.audio_path,
            "transcript_path": self.transcript_path,
            "clips_path": self.clips_path,
            "raw_clip_paths": self.raw_clip_paths,
            "vertical_clip_paths": self.vertical_clip_paths,
            "captioned_clip_paths": self.captioned_clip_paths,
            "completed_stages": self.completed_stages,
            "failed_stage": self.failed_stage,
            "total_time_seconds": self.total_time_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineState":
        s = cls()
        for k, v in d.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def ensure_dirs():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def checkpoint_path(video_id: str) -> Path:
    return UPLOAD_DIR / f"{video_id}_checkpoint.json"


def load_checkpoint(video_id: str) -> Optional[PipelineState]:
    p = checkpoint_path(video_id)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return PipelineState.from_dict(json.load(f))
    return None


def save_checkpoint(state: PipelineState):
    p = checkpoint_path(state.video_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2)


def clear_checkpoint(video_id: str):
    p = checkpoint_path(video_id)
    if p.exists():
        p.unlink()


def log(stage: str, msg: str):
    print(f"  [{stage.upper():10s}] {msg}", flush=True)


def section(title: str):
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"{bar}")


def stage_done(stage: str, elapsed: float):
    print(f"  ✓ {stage} complete ({elapsed:.1f}s)\n")


def stage_skip(stage: str):
    print(f"  ⏭  {stage} — already done, skipping\n")


def stage_fail(stage: str, err: Exception):
    print(f"  ✗ {stage} FAILED: {err}")
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════════
# Stage runners
# ══════════════════════════════════════════════════════════════════════════════

def run_download(state: PipelineState, source: str, is_url: bool) -> bool:
    """Stage 1 — Download YouTube video or handle local MP4."""
    section("Stage 1 / 6 — Download")

    if STAGE_DOWNLOAD in state.completed_stages:
        stage_skip(STAGE_DOWNLOAD)
        return True

    # Resuming with --force: video files already on disk, no need to re-download
    if not source and state.video_path and Path(state.video_path).exists():
        log(STAGE_DOWNLOAD, f"Video already exists: {state.video_path}")
        state.completed_stages.append(STAGE_DOWNLOAD)
        save_checkpoint(state)
        stage_done(STAGE_DOWNLOAD, 0.0)
        return True

    t0 = time.time()
    try:
        from services.video_downloader import download_youtube, handle_upload

        if is_url:
            log(STAGE_DOWNLOAD, f"Downloading: {source}")
            result = download_youtube(source)
        else:
            log(STAGE_DOWNLOAD, f"Processing upload: {source}")
            filename = Path(source).stem
            result = handle_upload(source, filename)

        state.video_id   = result["video_id"]
        state.video_path = result["video_path"]
        state.audio_path = result["audio_path"]

        log(STAGE_DOWNLOAD, f"Video ID  : {state.video_id}")
        log(STAGE_DOWNLOAD, f"Video     : {state.video_path}")
        log(STAGE_DOWNLOAD, f"Audio     : {state.audio_path}")
        log(STAGE_DOWNLOAD, f"Duration  : {result.get('duration', '?')}s")

        state.completed_stages.append(STAGE_DOWNLOAD)
        save_checkpoint(state)
        stage_done(STAGE_DOWNLOAD, time.time() - t0)
        return True

    except Exception as e:
        stage_fail(STAGE_DOWNLOAD, e)
        state.failed_stage = STAGE_DOWNLOAD
        return False


def run_transcribe(state: PipelineState, language: str, force_whisper: bool) -> bool:
    """Stage 2 — Transcribe audio with Sarvam V3 or faster-whisper fallback."""
    section("Stage 2 / 6 — Transcribe")

    if STAGE_TRANSCRIBE in state.completed_stages:
        stage_skip(STAGE_TRANSCRIBE)
        return True

    # Transcript file already exists on disk but checkpoint was lost
    expected_path = str(UPLOAD_DIR / f"{state.video_id}_audio_transcript.json")
    if Path(expected_path).exists():
        log(STAGE_TRANSCRIBE, f"Found existing transcript on disk, using it")
        state.transcript_path = expected_path
        state.completed_stages.append(STAGE_TRANSCRIBE)
        save_checkpoint(state)
        stage_skip(STAGE_TRANSCRIBE)
        return True

    t0 = time.time()
    try:
        from services.transcriber import transcribe_audio, save_transcript

        log(STAGE_TRANSCRIBE, f"Audio     : {state.audio_path}")
        log(STAGE_TRANSCRIBE, f"Language  : {language}")
        log(STAGE_TRANSCRIBE, f"Mode      : {'faster-whisper (forced)' if force_whisper else 'Sarvam V3 codemix → whisper fallback'}")

        result = transcribe_audio(
            state.audio_path,
            language=language,
            force_whisper=force_whisper,
        )

        transcript_path = str(UPLOAD_DIR / f"{state.video_id}_audio_transcript.json")
        save_transcript(result, transcript_path)
        state.transcript_path = transcript_path

        log(STAGE_TRANSCRIBE, f"Model     : {result['asr_model']}")
        log(STAGE_TRANSCRIBE, f"Segments  : {result['total_segments']}")
        log(STAGE_TRANSCRIBE, f"Words     : {result['total_words']}")
        log(STAGE_TRANSCRIBE, f"Proc time : {result['processing_time_seconds']}s")
        log(STAGE_TRANSCRIBE, f"Saved     : {transcript_path}")

        preview = result["text"][:200].replace("\n", " ")
        log(STAGE_TRANSCRIBE, f"Preview   : {preview}...")

        state.completed_stages.append(STAGE_TRANSCRIBE)
        save_checkpoint(state)
        stage_done(STAGE_TRANSCRIBE, time.time() - t0)
        return True

    except Exception as e:
        stage_fail(STAGE_TRANSCRIBE, e)
        state.failed_stage = STAGE_TRANSCRIBE
        return False


def run_select(state: PipelineState) -> bool:
    """Stage 3 — Select best clip moments via local scoring + Gemini."""
    section("Stage 3 / 6 — Clip Selection")

    if STAGE_SELECT in state.completed_stages:
        stage_skip(STAGE_SELECT)
        return True

    expected_path = str(UPLOAD_DIR / f"{state.video_id}_audio_clips.json")
    if Path(expected_path).exists():
        log(STAGE_SELECT, f"Found existing clips on disk, using it")
        state.clips_path = expected_path
        state.completed_stages.append(STAGE_SELECT)
        save_checkpoint(state)
        stage_skip(STAGE_SELECT)
        return True

    t0 = time.time()
    try:
        from services.clip_selector import select_clips

        log(STAGE_SELECT, f"Transcript: {state.transcript_path}")
        result = select_clips(state.transcript_path)

        if not result or not result.get("clips"):
            raise RuntimeError("Clip selector returned no valid clips")

        # clip_selector saves the JSON to <video_id>_clips.json automatically
        state.clips_path = expected_path

        log(STAGE_SELECT, f"Clips selected: {len(result['clips'])}")
        for i, clip in enumerate(result["clips"], 1):
            log(STAGE_SELECT,
                f"  [{i}] {clip.get('why', f'clip_{i}')} | "
                f"{clip['start']:.1f}s → {clip['end']:.1f}s | "
                f"score={clip.get('virality_score', '?')}")

        state.completed_stages.append(STAGE_SELECT)
        save_checkpoint(state)
        stage_done(STAGE_SELECT, time.time() - t0)
        return True

    except Exception as e:
        stage_fail(STAGE_SELECT, e)
        state.failed_stage = STAGE_SELECT
        return False


def run_cut(state: PipelineState) -> bool:
    """Stage 4 — Cut clips from original video using FFmpeg."""
    section("Stage 4 / 6 — Cut Clips")

    if STAGE_CUT in state.completed_stages:
        stage_skip(STAGE_CUT)
        return True

    # Clean output dir to avoid leftover files from previous runs
    # polluting the crop and caption stages
    if OUTPUT_DIR.exists():
        import shutil
        for f in OUTPUT_DIR.iterdir():
            if f.is_file():
                f.unlink()
        log(STAGE_CUT, f"Cleared output dir: {OUTPUT_DIR}")

    t0 = time.time()
    try:
        from services.video_cutter import cut_all_clips

        log(STAGE_CUT, f"Video  : {state.video_path}")
        log(STAGE_CUT, f"Clips  : {state.clips_path}")

        cut_paths = cut_all_clips(state.clips_path, state.video_path, str(OUTPUT_DIR))

        if not cut_paths:
            raise RuntimeError("No clips were cut — check FFmpeg and clip timestamps")

        state.raw_clip_paths = cut_paths
        log(STAGE_CUT, f"Cut {len(cut_paths)} clips → {OUTPUT_DIR}")

        state.completed_stages.append(STAGE_CUT)
        save_checkpoint(state)
        stage_done(STAGE_CUT, time.time() - t0)
        return True

    except Exception as e:
        stage_fail(STAGE_CUT, e)
        state.failed_stage = STAGE_CUT
        return False


def run_crop(state: PipelineState) -> bool:
    """Stage 5 — Convert horizontal clips to 9:16 vertical."""
    section("Stage 5 / 6 — Vertical Crop (9:16)")

    if STAGE_CROP in state.completed_stages:
        stage_skip(STAGE_CROP)
        return True

    t0 = time.time()
    try:
        from services.vertical_cropper import crop_all_clips

        log(STAGE_CROP, f"Input dir: {OUTPUT_DIR}")
        vertical_paths = crop_all_clips(str(OUTPUT_DIR))

        if not vertical_paths:
            raise RuntimeError("No clips were cropped — check OpenCV and input files")

        state.vertical_clip_paths = vertical_paths
        log(STAGE_CROP, f"Cropped {len(vertical_paths)} clips to 9:16")

        state.completed_stages.append(STAGE_CROP)
        save_checkpoint(state)
        stage_done(STAGE_CROP, time.time() - t0)
        return True

    except Exception as e:
        stage_fail(STAGE_CROP, e)
        state.failed_stage = STAGE_CROP
        return False


def run_caption(state: PipelineState) -> bool:
    """Stage 6 — Burn word-highlighted captions onto vertical clips."""
    section("Stage 6 / 6 — Captions")

    if STAGE_CAPTION in state.completed_stages:
        stage_skip(STAGE_CAPTION)
        return True

    t0 = time.time()
    try:
        from services.caption_renderer import render_all_captions

        log(STAGE_CAPTION, f"Transcript: {state.transcript_path}")
        log(STAGE_CAPTION, f"Clips JSON: {state.clips_path}")
        log(STAGE_CAPTION, f"Clips dir : {OUTPUT_DIR}")

        captioned_paths = render_all_captions(
            state.transcript_path,
            state.clips_path,
            str(OUTPUT_DIR),
        )

        if not captioned_paths:
            raise RuntimeError("Caption rendering failed for all clips")

        state.captioned_clip_paths = captioned_paths
        log(STAGE_CAPTION, f"Captioned {len(captioned_paths)} clips")
        for p in captioned_paths:
            size_mb = Path(p).stat().st_size / (1024 * 1024)
            log(STAGE_CAPTION, f"  → {Path(p).name} ({size_mb:.1f} MB)")

        state.completed_stages.append(STAGE_CAPTION)
        save_checkpoint(state)
        stage_done(STAGE_CAPTION, time.time() - t0)
        return True

    except Exception as e:
        stage_fail(STAGE_CAPTION, e)
        state.failed_stage = STAGE_CAPTION
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline runner
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(
    source: str,
    is_url: bool,
    language: str = "te",
    force_whisper: bool = False,
    force: bool = False,
    resume_id: Optional[str] = None,
    skip_captions: bool = False,
) -> PipelineState:

    ensure_dirs()
    pipeline_start = time.time()

    print("\n🎬 ClipForge AI — Pipeline Starting")
    print(f"   Source   : {source or f'resuming {resume_id}'}")
    print(f"   Language : {language}")
    print(f"   Mode     : {'forced whisper' if force_whisper else 'Sarvam V3 → whisper fallback'}")

    # ── load or init state ────────────────────────────────────────────────────
    state = None

    if resume_id:
        state = load_checkpoint(resume_id)
        if state:
            print(f"\n📂 Resuming pipeline for: {resume_id}")
            print(f"   Completed so far: {state.completed_stages}")
        else:
            print(f"⚠  No checkpoint found for {resume_id} — starting fresh")

    if state is None:
        state = PipelineState()

    if force and state.video_id:
        print(f"\n🔄 --force: resetting completed stages for {state.video_id}")
        clear_checkpoint(state.video_id)
        # Keep video_id and file paths — only reset which stages have run
        state.completed_stages = []
        state.failed_stage = None
        state.raw_clip_paths = []
        state.vertical_clip_paths = []
        state.captioned_clip_paths = []

    # ── run stages ────────────────────────────────────────────────────────────
    stage_fns = [
        lambda: run_download(state, source, is_url),
        lambda: run_transcribe(state, language, force_whisper),
        lambda: run_select(state),
        lambda: run_cut(state),
        lambda: run_crop(state),
    ]

    if not skip_captions:
        stage_fns.append(lambda: run_caption(state))

    for fn in stage_fns:
        ok = fn()
        if not ok:
            print(f"\n✗ Pipeline aborted at: {state.failed_stage}")
            print(f"  Fix the issue then resume with:")
            print(f"  python pipeline.py --resume {state.video_id}")
            break

    # ── summary ───────────────────────────────────────────────────────────────
    state.total_time_seconds = round(time.time() - pipeline_start, 1)

    section("Pipeline Summary")
    print(f"  Video ID         : {state.video_id}")
    print(f"  Completed stages : {state.completed_stages}")
    print(f"  Total time       : {state.total_time_seconds}s")

    if state.failed_stage:
        print(f"  Failed at        : {state.failed_stage}")
        print(f"\n  Re-run with: python pipeline.py --resume {state.video_id}")
    else:
        print(f"\n  ✅ All stages complete!")
        output_clips = state.captioned_clip_paths or state.vertical_clip_paths
        print(f"  Output clips ({len(output_clips)}):")
        for p in output_clips:
            print(f"    → {p}")

    print()
    return state


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ClipForge AI — Full video-to-shorts pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline.py --url https://www.youtube.com/watch?v=XXXXX
  python pipeline.py --file /path/to/video.mp4 --language te
  python pipeline.py --url <url> --force-whisper
  python pipeline.py --resume JGJTV5DFKKA
  python pipeline.py --url <url> --force
  python pipeline.py --url <url> --skip-captions
        """
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--url",    type=str, help="YouTube video URL")
    source_group.add_argument("--file",   type=str, help="Path to local MP4 file")
    source_group.add_argument("--resume", type=str, metavar="VIDEO_ID",
                               help="Resume from last checkpoint using video_id")

    parser.add_argument("--language",      type=str, default="te",
                        choices=["te", "hi", "ta", "kn", "ml", "auto"],
                        help="Video language (default: te)")
    parser.add_argument("--force-whisper", action="store_true",
                        help="Skip Sarvam, use local faster-whisper")
    parser.add_argument("--force",         action="store_true",
                        help="Ignore checkpoint, re-run everything")
    parser.add_argument("--skip-captions", action="store_true",
                        help="Stop after vertical crop, skip captions")

    args = parser.parse_args()

    if args.resume:
        source, is_url, resume_id = "", False, args.resume
    elif args.url:
        source, is_url, resume_id = args.url, True, None
    else:
        source, is_url, resume_id = args.file, False, None
        if not Path(source).exists():
            print(f"✗ File not found: {source}")
            sys.exit(1)

    state = run_pipeline(
        source=source,
        is_url=is_url,
        language=args.language,
        force_whisper=args.force_whisper,
        force=args.force,
        resume_id=resume_id,
        skip_captions=args.skip_captions,
    )

    sys.exit(0 if not state.failed_stage else 1)


if __name__ == "__main__":
    main()