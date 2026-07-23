# -*- coding: utf-8 -*-
"""
Feature #14 — filler-word & silence removal (render + caption remap).

The frontend detects candidate cut spans (fillers + silence gaps), lets the
user restore individual ones, and sends the effective cut list as
[[start, end], ...] clip-local seconds. This module:
  - renders the cuts (worker._apply_cuts uses build_select_filters) via a
    single FFmpeg select/aselect + setpts/asetpts pass, and
  - remaps caption word timings onto the post-cut timeline
    (apply_cuts_to_words) — the MIRROR of frontend lib/fillerRemoval.js.

Depends on feature #1: cut spans are in the clip's refined (cut-file) time
base, the same base captions already use.
"""


def _norm_spans(spans):
    """Sanitize → sorted, merged [(start, end)] with end > start."""
    clean = []
    for s in spans or []:
        try:
            a, b = float(s[0]), float(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        if b > a:
            clean.append((a, b))
    clean.sort()
    merged = []
    for a, b in clean:
        if merged and a <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def keep_spans(cut_spans, duration):
    """Complement of the cut spans over [0, duration] — the parts we KEEP."""
    cuts = _norm_spans(cut_spans)
    keeps = []
    cursor = 0.0
    for a, b in cuts:
        a = max(0.0, min(a, duration))
        b = max(0.0, min(b, duration))
        if a > cursor:
            keeps.append((round(cursor, 3), round(a, 3)))
        cursor = max(cursor, b)
    if cursor < duration:
        keeps.append((round(cursor, 3), round(duration, 3)))
    return [(a, b) for a, b in keeps if b > a]


def build_cut_filtergraph(cut_spans, duration):
    """FFmpeg -filter_complex string that keeps the non-cut parts and concats
    them, or None when nothing is cut.

    Uses per-segment trim/atrim + concat (NOT select/aselect): select drops
    video frames fine but aselect+asetpts left the audio full-length in
    testing, desyncing the result. trim/atrim+concat cuts BOTH streams
    identically and re-bases each segment's PTS, so audio and video stay
    locked. Output labels are [outv]/[outa] for the worker's -map.
    """
    keeps = keep_spans(cut_spans, duration)
    # No cuts, or a single keep spanning the whole clip → caller passes through.
    if not keeps or (len(keeps) == 1 and keeps[0][0] <= 0 and keeps[0][1] >= duration):
        return None
    parts, labels = [], []
    for i, (a, b) in enumerate(keeps):
        parts.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    concat = "".join(labels) + f"concat=n={len(keeps)}:v=1:a=1[outv][outa]"
    return ";".join(parts) + ";" + concat


def total_removed(cut_spans, duration):
    cuts = _norm_spans(cut_spans)
    return round(sum(min(b, duration) - max(a, 0.0)
                     for a, b in cuts if min(b, duration) > max(a, 0.0)), 3)


# ── caption remap (mirror of frontend lib/fillerRemoval.js) ──────────────────

def _removed_before(t, cuts):
    removed = 0.0
    for a, b in cuts:
        if b <= t:
            removed += b - a
        elif a < t:
            removed += t - a
    return removed


def remap_time_after_cuts(t, cut_spans):
    cuts = _norm_spans(cut_spans)
    return round(max(0.0, t - _removed_before(t, cuts)), 3)


def _word_in_cuts(word, cuts):
    mid = (word["start"] + word["end"]) / 2.0
    return any(a <= mid < b for a, b in cuts)


def apply_cuts_to_words(words, cut_spans):
    """Drop words inside cuts; shift survivors onto the post-cut timeline.
    Mirror of frontend applyCutsToWords — preview and burn must agree."""
    cuts = _norm_spans(cut_spans)
    if not cuts:
        return words
    out = []
    for w in words:
        if _word_in_cuts(w, cuts):
            continue
        nw = dict(w)
        nw["start"] = remap_time_after_cuts(w["start"], cut_spans)
        nw["end"] = remap_time_after_cuts(w["end"], cut_spans)
        out.append(nw)
    return out
