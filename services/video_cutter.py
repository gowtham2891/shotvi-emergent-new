"""
ClipForge AI — Video Cutter (v3 — CTC-aligned + boundary refinement)
=====================================================================
Reads clips JSON and cuts each clip from the original video using FFmpeg.

v3: CTC forced alignment (MMS) gives ~20ms word-level accuracy.
Boundary refinement snaps clip start/end to the nearest energy dip
within ±0.5s of the CTC timestamp. This catches the ~0.3-0.5s error
margin that CTC sometimes has on word boundaries.

This is step 3 from the alignment plan:
  CTC gives ~20ms frame accuracy → snap each boundary to nearest
  energy dip (silence gap) within ±25ms window → ~10ms final accuracy.

We use a slightly larger window (±0.5s) to handle CTC's occasional errors.
"""

import json
import os
import sys
import subprocess
import re
import numpy as np


# ── Padding (only used if refinement fails) ──────────────────────────────────``
CUT_PRE_ROLL = 0.10    # seconds before clip start
FALLBACK_POST_ROLL = 0.50  # fallback if audio not available

# ── Boundary refinement config ────────────────────────────────────────────────
REFINE_WINDOW = 0.5     # search ±0.5s around CTC boundary
REFINE_HOP = 256        # ~16ms at 16kHz — fine resolution for word edges
REFINE_FRAME = 512      # ~32ms window for short-time energy
REFINE_PAD = 0.08       # 80ms padding after detected dip


# ── Audio cache ───────────────────────────────────────────────────────────────
_audio_cache = {}


def _load_audio(audio_path: str):
    """Load audio once, cache for all clips."""
    if audio_path in _audio_cache:
        return _audio_cache[audio_path]
    try:
        import librosa
        y, sr = librosa.load(audio_path, sr=None, mono=True)
        _audio_cache[audio_path] = (y, sr)
        print(f"  [Audio] Loaded: {len(y)/sr:.1f}s, {sr}Hz")
        return y, sr
    except Exception as e:
        print(f"  [Audio] ⚠ Failed: {e}")
        return None, None


def refine_boundary(y, sr, timestamp: float, direction: str = "end") -> float:
    """
    Snap a CTC timestamp to the nearest energy dip within ±REFINE_WINDOW.

    For 'end' boundaries: find the nearest energy minimum AFTER the timestamp.
    This is where the last word's sound actually fades out.

    For 'start' boundaries: find the nearest energy minimum BEFORE the timestamp.
    This is where silence ends and the first word begins.

    Returns the refined timestamp, or original + small pad if no dip found.
    """
    import librosa

    # Search window
    if direction == "end":
        win_start_sec = timestamp - 0.1       # small look-back
        win_end_sec = timestamp + REFINE_WINDOW  # main search forward
    else:  # start
        win_start_sec = timestamp - REFINE_WINDOW  # main search backward
        win_end_sec = timestamp + 0.1       # small look-forward

    win_start_sec = max(0.0, win_start_sec)
    win_end_sec = min(len(y) / sr, win_end_sec)

    win_start = int(win_start_sec * sr)
    win_end = int(win_end_sec * sr)

    if win_end <= win_start:
        return timestamp + (REFINE_PAD if direction == "end" else -REFINE_PAD)

    segment = y[win_start:win_end]

    # Compute short-time energy
    rms = librosa.feature.rms(
        y=segment, frame_length=REFINE_FRAME, hop_length=REFINE_HOP
    )[0]

    if len(rms) == 0:
        return timestamp + (REFINE_PAD if direction == "end" else -REFINE_PAD)

    if direction == "end":
        # Find the frame with minimum energy (the dip between words)
        # Search from the CTC timestamp forward
        ctc_frame = int((timestamp - win_start_sec) * sr / REFINE_HOP)
        ctc_frame = max(0, min(ctc_frame, len(rms) - 1))

        # Look for the minimum in the region after CTC endpoint
        search_region = rms[ctc_frame:]
        if len(search_region) == 0:
            return timestamp + REFINE_PAD

        min_idx = np.argmin(search_region) + ctc_frame
        dip_time = win_start_sec + (min_idx * REFINE_HOP / sr)

        # Add small padding after the dip
        refined = dip_time + REFINE_PAD

    else:  # start
        # Find the minimum energy before the CTC start
        ctc_frame = int((timestamp - win_start_sec) * sr / REFINE_HOP)
        ctc_frame = max(0, min(ctc_frame, len(rms) - 1))

        search_region = rms[:ctc_frame + 1]
        if len(search_region) == 0:
            return timestamp - REFINE_PAD

        min_idx = np.argmin(search_region)
        dip_time = win_start_sec + (min_idx * REFINE_HOP / sr)

        # Subtract small padding before the dip
        refined = dip_time - REFINE_PAD

    return max(0.0, refined)


def load_clips(clips_path: str) -> dict:
    """Load clips JSON file."""
    with open(clips_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"✓ Loaded {len(data['clips'])} clips")
    return data


def cut_clip(video_path: str, start: float, end: float, output_path: str) -> bool:
    """
    Cut a single clip from the video using FFmpeg.
    start/end are already refined — just apply directly.
    """
    duration = end - start

    fast_seek = max(0.0, start - 5.0)
    accurate_offset = start - fast_seek

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{fast_seek:.3f}",
        "-i", video_path,
        "-ss", f"{accurate_offset:.3f}",
        "-t", f"{duration:.3f}",
        "-avoid_negative_ts", "1",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-crf", "23",
        output_path
    ]

    print(f"  CMD: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=300)
        if result.returncode != 0:
            print(f"  ✗ FFmpeg error: {result.stderr[-300:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  ✗ FFmpeg timed out")
        return False


def extract_thumbnail(clip_path: str) -> str:
    """Pick the most representative frame, skipping the first 20% to avoid dark intros."""
    thumb_path = clip_path.replace('.mp4', '_thumb.jpg')

    # Get duration so we can skip the intro
    probe = subprocess.run([
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        clip_path
    ], capture_output=True, text=True, encoding='utf-8', errors='replace')

    seek_time = 0.0
    if probe.returncode == 0:
        try:
            duration = float(probe.stdout.strip())
            seek_time = duration * 0.20  # skip first 20%
        except Exception:
            pass

    cmd = [
        'ffmpeg', '-y',
        '-ss', f'{seek_time:.3f}',
        '-i', clip_path,
        '-vf', 'thumbnail=200,scale=360:-1',
        '-frames:v', '1',
        '-q:v', '3',
        thumb_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and os.path.exists(thumb_path):
        return thumb_path
    return None


def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in Windows filenames or that break
    downstream tools (FFmpeg concat file lists, shell quoting, etc.)."""
    cleaned = re.sub(r'[<>:"/\\|?*!=\'‘’]', '', name)
    cleaned = cleaned.replace(" ", "_")
    return cleaned[:30]


def find_audio_path(video_path: str):
    """Find the WAV file for boundary refinement."""
    video_dir = os.path.dirname(video_path)
    video_id = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = os.path.join(video_dir, f"{video_id}_audio.wav")
    if os.path.exists(audio_path):
        return audio_path
    alt_path = os.path.join("storage", "uploads", f"{video_id}_audio.wav")
    if os.path.exists(alt_path):
        return alt_path
    return None


def get_segment_timestamps(clip: dict, sent_by_id: dict):
    """
    Resolve a clip's segments array into per-segment timestamps.
    Returns None for single-segment clips (caller should use clip start/end
    as-is). Returns a list of {"start", "end"} dicts for clips with a
    genuine multi-segment array (Gemini cut a dead zone out of the middle).
    """
    segments = clip.get("segments", [])
    if not segments or len(segments) == 1:
        return None

    result = []
    for seg in segments:
        s_id = int(seg["start_sent_id"])
        e_id = int(seg["end_sent_id"])
        s_sent = sent_by_id.get(s_id)
        e_sent = sent_by_id.get(e_id)
        if s_sent and e_sent:
            result.append({
                "start": s_sent["start"],
                "end": e_sent["end"]
            })
    return result if len(result) > 1 else None


def cut_multi_segment_clip(video_path: str, segments: list, output_path: str, y, sr):
    """
    Cut a multi-segment clip: cut each segment separately (with the same
    boundary refinement used for single-segment clips), then concatenate
    them into one continuous output file. Used for clips where Gemini cut
    a dead zone out of the middle via the segments array (sponsor reads,
    intro animation, mid-video recaps, etc).

    Returns (success, refined_segments) — the per-segment refined boundaries
    actually used for cutting, so the caption stage can build word timings on
    the stitched output file's REAL timeline (caption-sync fix): each output
    segment starts at its refined_start, not the raw CTC segment start.
    """
    tmp_dir = output_path + "_segs"
    os.makedirs(tmp_dir, exist_ok=True)

    seg_paths = []
    refined_segments = []
    for i, seg in enumerate(segments):
        seg_path = os.path.join(tmp_dir, f"seg{i}.mp4").replace("\\", "/")

        # Apply boundary refinement to each segment
        if y is not None:
            refined_start = refine_boundary(y, sr, seg["start"], "start")
            refined_end = refine_boundary(y, sr, seg["end"], "end")
        else:
            refined_start = max(0.0, seg["start"] - CUT_PRE_ROLL)
            refined_end = seg["end"] + FALLBACK_POST_ROLL

        success = cut_clip(video_path, refined_start, refined_end, seg_path)
        if not success:
            for p in seg_paths:
                try: os.remove(p)
                except OSError: pass
            try: os.rmdir(tmp_dir)
            except OSError: pass
            return False, []
        seg_paths.append(seg_path)
        refined_segments.append({
            "start": round(refined_start, 3),
            "end":   round(refined_end,   3),
        })

    # Concatenate segments
    list_path = output_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in seg_paths:
            safe = os.path.abspath(p).replace("\\", "/")
            # Escape embedded single quotes — an unescaped ' in the path
            # (e.g. from a clip title) breaks the concat demuxer's quoting.
            escaped = safe.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_path, "-c", "copy", output_path
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300
    )

    # Cleanup
    try: os.remove(list_path)
    except OSError: pass
    for p in seg_paths:
        try: os.remove(p)
        except OSError: pass
    try: os.rmdir(tmp_dir)
    except OSError: pass

    if result.returncode != 0:
        print(f"  ✗ Concat error: {result.stderr[-300:]}")
        return False, []
    return True, refined_segments


def cut_all_clips(clips_path: str, video_path: str, output_dir: str = "storage/outputs") -> list:
    """Cut all clips with boundary refinement."""

    data = load_clips(clips_path)
    clips = data["clips"]

    if not clips:
        print("✗ No clips to cut")
        return []

    os.makedirs(output_dir, exist_ok=True)
    video_id = os.path.splitext(os.path.basename(video_path))[0]

    # Load audio for boundary refinement
    audio_path = find_audio_path(video_path)
    y, sr = (None, None)
    if audio_path:
        print(f"✓ Audio for boundary refinement: {audio_path}")
        y, sr = _load_audio(audio_path)

    # Load transcript sentences so multi-segment clips can resolve their
    # segments array into per-segment timestamps
    transcript_path = clips_path.replace("_audio_clips.json", "_audio_transcript.json")
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_data = json.load(f)
        sentences = transcript_data.get("sentences", [])
        sent_by_id = {s["id"]: s for s in sentences}
    else:
        sent_by_id = {}

    cut_paths = []
    for i, clip in enumerate(clips, 1):
        title_slug = sanitize_filename(clip.get("why", clip.get("hook_text", "clip")))
        output_path = os.path.join(
            output_dir, f"{video_id}_clip{i}_{title_slug}.mp4"
        ).replace("\\", "/")

        clip_start = clip["start"]
        clip_end = clip["end"]

        print(f"\n✂ Cutting clip {i}/{len(clips)}: {clip.get('why', clip.get('hook_text', f'clip_{i}'))}")
        print(f"  CTC: {clip_start:.2f}s → {clip_end:.2f}s ({clip['duration']:.1f}s)")

        # Refine boundaries using audio energy
        if y is not None:
            refined_start = refine_boundary(y, sr, clip_start, direction="start")
            refined_end = refine_boundary(y, sr, clip_end, direction="end")
            print(f"  Refined: {refined_start:.2f}s → {refined_end:.2f}s "
                  f"(start {refined_start - clip_start:+.3f}s, "
                  f"end {refined_end - clip_end:+.3f}s)")
        else:
            refined_start = max(0.0, clip_start - CUT_PRE_ROLL)
            refined_end = clip_end + FALLBACK_POST_ROLL
            print(f"  No audio — using fixed padding: "
                  f"{refined_start:.2f}s → {refined_end:.2f}s")

        seg_timestamps = get_segment_timestamps(clip, sent_by_id)

        if seg_timestamps:
            print(f"  Multi-segment clip: {len(seg_timestamps)} parts")
            for j, seg in enumerate(seg_timestamps):
                print(f"    Part {j+1}: {seg['start']:.2f}s → {seg['end']:.2f}s")
            success, refined_segments = cut_multi_segment_clip(
                video_path, seg_timestamps, output_path, y, sr)
            if success:
                # Caption-sync fix: persist the boundaries the cutter ACTUALLY
                # used, so caption timing is built on the output file's real
                # timeline instead of the raw CTC clip start (≤0.5s drift).
                clip["refined_segments"] = refined_segments
        else:
            success = cut_clip(video_path, refined_start, refined_end, output_path)
            if success:
                clip["refined_start"] = round(refined_start, 3)
                clip["refined_end"]   = round(refined_end,   3)

        if success:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"  ✓ Saved: {output_path} ({size_mb:.1f} MB)")
            cut_paths.append(output_path)
            try:
                thumb = extract_thumbnail(output_path)
                if thumb:
                    print(f"  ✓ Thumbnail: {thumb}")
                else:
                    print(f"  ⚠ Thumbnail extraction returned nothing for {output_path}")
            except Exception as e:
                print(f"  ⚠ Thumbnail failed (non-fatal): {e}")
        else:
            print(f"  ✗ Failed to cut clip {i}")

    # Persist refined boundaries back into the clips JSON so every later
    # stage (pipeline captions, re-renders, ClipOut → frontend preview) shares
    # the same t=0 as the cut files. Old JSONs without these keys keep the
    # pre-fix behavior via .get(..., clip["start"]) fallbacks downstream.
    try:
        with open(clips_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ Refined boundaries saved into {clips_path}")
    except OSError as e:
        print(f"⚠ Could not persist refined boundaries: {e}")

    print(f"\n{'='*60}")
    print(f"✓ Cut {len(cut_paths)}/{len(clips)} clips successfully")
    print(f"  Output: {output_dir}")
    return cut_paths


# --- CLI Entry Point ---
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python services/video_cutter.py <clips_json> <video_path>")
        print("Example: python services/video_cutter.py "
              "storage/uploads/JGJTV5DFKKA_clips.json storage/uploads/JGJTV5DFKKA.mp4")
        sys.exit(1)

    clips_path = sys.argv[1]
    video_path = sys.argv[2]

    if not os.path.exists(clips_path):
        print(f"✗ Clips file not found: {clips_path}")
        sys.exit(1)
    if not os.path.exists(video_path):
        print(f"✗ Video not found: {video_path}")
        sys.exit(1)

    results = cut_all_clips(clips_path, video_path)
    if results:
        print(f"\n🎉 Done! {len(results)} clips cut and saved.")
    else:
        print("\n✗ Cutting failed.")