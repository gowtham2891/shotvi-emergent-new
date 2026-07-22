"""
ClipForge AI — Line-level forced re-alignment (Descript-style line editing)
===========================================================================
When a caption line's word COUNT changes (words added/removed in the editable
transcript), per-word karaoke timing for that line can no longer come from
wordEdits (text-only by contract). This module re-derives it by running the
EXISTING MMS CTC forced aligner (services/transcriber.py :: align_with_ctc —
the same engine that produced the original word timestamps) on JUST that
line's audio span with the new word list.

INVARIANTS (scoped amendment to the text-only rule):
  - Line boundaries are FIXED. Re-alignment only re-derives per-word
    timestamps WITHIN [line_start, line_end]; audio/video is never cut and
    nothing outside the line's span may change.
  - The user's TEXT is authoritative: aligned output supplies timing only —
    word text always comes from the request, never from the aligner (which
    sees romanized tokens).
  - NEVER lose the edit, never crash: any aligner failure or implausible
    output degrades to an even distribution of the span across the new words,
    flagged approximate=True.
"""

import os
import subprocess
import tempfile
from pathlib import Path

# Plausibility floor: an aligned word shorter than this is CTC noise (the
# aligner collapsed the token onto a blank region), not a usable karaoke span.
MIN_WORD_DURATION = 0.02  # seconds

# Tolerance for aligned timestamps poking slightly outside the extracted span
# (emission stride rounding) before we distrust the whole alignment.
SPAN_SLACK = 0.25  # seconds


def even_distribution(words: list, start: float, end: float) -> list:
    """Fallback timing: split [start, end] evenly across *words* (Telugu
    strings), preserving order. Deterministic, monotonic, exact boundaries."""
    n = len(words)
    if n == 0:
        return []
    span = max(end - start, 0.0)
    step = span / n
    return [
        {
            "word":  w,
            "start": round(start + i * step, 3),
            "end":   round(start + (i + 1) * step, 3),
        }
        for i, w in enumerate(words)
    ]


def _extract_span_wav(audio_path: str, abs_start: float, abs_end: float) -> str:
    """Cut the line's audio span to a temp mono 16 kHz wav for the aligner.
    Read-only on the source: this NEVER modifies the job's audio file."""
    fd, tmp = tempfile.mkstemp(suffix="_realign.wav")
    os.close(fd)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{max(abs_start, 0.0):.3f}", "-to", f"{abs_end:.3f}",
            "-i", str(audio_path),
            "-ac", "1", "-ar", "16000",
            tmp,
        ],
        check=True, capture_output=True, timeout=60,
    )
    return tmp


def _run_aligner(audio_path: str, abs_start: float, abs_end: float, words: list) -> list:
    """Extract the span and run the pipeline's MMS CTC aligner on it.
    Returns [{word, start, end}] with times relative to the SPAN start.
    Module-level seam on purpose: tests monkeypatch this to exercise the
    validation/fallback logic without torch or model weights."""
    import torch  # deferred: the API process must import without torch until needed
    from services.transcriber import align_with_ctc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tmp = _extract_span_wav(audio_path, abs_start, abs_end)
    try:
        return align_with_ctc([{"text": " ".join(words)}], tmp, device)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _plausible(aligned: list, words: list, span: float) -> bool:
    """Reject alignments the karaoke path can't trust: token-count mismatch,
    zero-length words, out-of-span times, or non-monotonic starts."""
    if len(aligned) != len(words):
        return False
    for a in aligned:
        try:
            s, e = float(a["start"]), float(a["end"])
        except (KeyError, TypeError, ValueError):
            return False
        if e - s < MIN_WORD_DURATION:
            return False
        if s < -SPAN_SLACK or e > span + SPAN_SLACK:
            return False
    for i in range(1, len(aligned)):
        if float(aligned[i]["start"]) < float(aligned[i - 1]["start"]):
            return False
    return True


def realign_line_words(audio_path, abs_start: float, abs_end: float,
                       line_start: float, line_end: float, words: list) -> tuple:
    """
    Re-derive per-word timestamps for one caption line.

    audio_path           — the job's full audio file ({video_id}_audio.wav)
    abs_start / abs_end  — the line's span on the ORIGINAL video timeline
                           (what ffmpeg extracts)
    line_start / line_end— the same span in CLIP-RELATIVE time (what the
                           returned timestamps are expressed in — the space
                           the frontend transcript and the burn grouper use)
    words                — the user's new Telugu word list (text authority)

    Returns (words, approximate):
      words       — [{word, start, end}] clip-relative, clamped into the
                    line's fixed span, one entry per input word, in order
      approximate — True when the fallback even distribution was used
    """
    fallback = even_distribution(words, line_start, line_end)
    span = line_end - line_start
    if not words or span <= 0.05 or not Path(str(audio_path)).exists():
        return fallback, True

    try:
        aligned = _run_aligner(str(audio_path), abs_start, abs_end, words)
    except Exception as exc:
        print(f"  [Realign] ✗ aligner failed ({exc}) — even-distribution fallback", flush=True)
        return fallback, True

    if not _plausible(aligned, words, span):
        print(f"  [Realign] ⚠ implausible alignment for {len(words)} word(s) "
              f"(got {len(aligned)}) — even-distribution fallback", flush=True)
        return fallback, True

    out = []
    for w, a in zip(words, aligned):
        # Clamp into the FIXED line span; keep at least the plausibility floor
        # of visible duration so the karaoke glow never skips a word.
        s = min(max(line_start + float(a["start"]), line_start), line_end)
        e = min(max(line_start + float(a["end"]), s), line_end)
        if e - s < MIN_WORD_DURATION:
            e = min(line_end, s + MIN_WORD_DURATION)
        out.append({"word": w, "start": round(s, 3), "end": round(e, 3)})
    return out, False


def output_time_to_absolute(t: float, clip: dict, sentences: list) -> float:
    """
    Map a clip-relative (output-timeline) time back to the ORIGINAL video
    timeline — the inverse of get_words_for_multisegment_clip's stacking.
    Single-segment clips are a plain clip.start offset. NOTE: a line span
    crossing a stitched segment boundary maps its endpoints into different
    source regions; the extracted audio then contains the cut-out gap and the
    alignment will fail plausibility → even-distribution fallback (safe).
    """
    segments = clip.get("segments") or []
    if len(segments) <= 1:
        return float(clip["start"]) + t

    sent_by_id = {s["id"]: s for s in sentences}
    offset = 0.0
    seg_end = float(clip["start"])
    for seg in segments:
        try:
            seg_start = float(sent_by_id[int(seg["start_sent_id"])]["start"])
            seg_end   = float(sent_by_id[int(seg["end_sent_id"])]["end"])
        except (KeyError, TypeError, ValueError):
            continue
        dur = seg_end - seg_start
        if t <= offset + dur:
            return seg_start + (t - offset)
        offset += dur
    return seg_end  # past the last segment: clamp to its end
