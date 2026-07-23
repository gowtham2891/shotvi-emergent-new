# -*- coding: utf-8 -*-
"""
Feature #13 — auto-zoom / punch-ins.

Animated crop that punches in (1.0 → PUNCH_ZOOM over ~PUNCH_RISE+PUNCH_FALL)
on speech beats, then eases back out. Punch beats are auto-generated from
word timestamps (a word that begins after a pause = a fresh emphasis beat);
the user can add/remove them on the timeline. The result rides the existing
single-pass render chain: worker._apply_crop_keyframes turns these keyframes
into ONE FFmpeg `zoompan` filter (crop can't vary output size per frame;
zoompan is the tool for time-varying zoom on video).

crop_keyframes wire shape (api/models.py): [{time, x, y, w, h}] — fractions
of the source frame. Auto-zoom is a CENTERED zoom, so w == h == 1/zoom and
x == y == (1 - w)/2; the builder derives zoom = 1/w. (Stored x/y are honored
as the centered offset; a future pan feature could interpolate them freely.)
"""

# Punch shape — spec: 1.0 → 1.12 over ~0.4s.
PUNCH_ZOOM = 1.12
PUNCH_RISE = 0.20   # seconds to reach peak
PUNCH_FALL = 0.20   # seconds to ease back

# Beat selection defaults.
MIN_SPACING = 2.5   # seconds between punches (never stack)
GAP_THRESHOLD = 0.35  # a word starting >= this long after the previous ends = a beat
MAX_PUNCHES = 12


def generate_punch_points(words, min_spacing=MIN_SPACING,
                          gap_threshold=GAP_THRESHOLD, max_punches=MAX_PUNCHES):
    """Word timestamps → punch beat times (seconds, clip-local).

    Heuristic: punch on a word that begins after a pause (a fresh sentence /
    emphasis beat), throttled so punches never sit closer than min_spacing.
    Words carry clip-local {start, end} (the store's transcript shape).
    """
    punches = []
    last = -1e9
    prev_end = None
    for w in words or []:
        s = w.get("start")
        if not isinstance(s, (int, float)):
            continue
        # First word has no preceding pause → never an auto-punch (a clip
        # must not open mid-zoom; the user can add an opening punch by hand).
        gap = (s - prev_end) if prev_end is not None else -1.0
        prev_end = w.get("end", s)
        if s - last < min_spacing:
            continue
        if gap >= gap_threshold:
            punches.append(round(float(s), 3))
            last = s
            if len(punches) >= max_punches:
                break
    return punches


def _pulse(t, tp, rise, fall, zoom):
    """Triangular zoom pulse of one punch at time tp, evaluated at t."""
    if t <= tp - rise or t >= tp + fall:
        return 1.0
    if t <= tp:
        return 1.0 + (zoom - 1.0) * (t - (tp - rise)) / rise
    return 1.0 + (zoom - 1.0) * ((tp + fall) - t) / fall


def punches_to_keyframes(punches, duration, zoom=PUNCH_ZOOM,
                         rise=PUNCH_RISE, fall=PUNCH_FALL):
    """Punch times → crop_keyframes [{time,x,y,w,h}] (centered zoom).

    Emits a keyframe at every pulse breakpoint; overlapping punches combine
    via max(), so two close beats read as one sustained push rather than a
    double-bounce. Times clamp into [0, duration].
    """
    if not punches or not duration or duration <= 0:
        return []
    breakpoints = set()
    for tp in punches:
        for t in (tp - rise, tp, tp + fall):
            breakpoints.add(round(max(0.0, min(duration, t)), 3))
    kfs = []
    for t in sorted(breakpoints):
        z = max(_pulse(t, tp, rise, fall, zoom) for tp in punches)
        w = round(1.0 / z, 5)
        off = round((1.0 - w) / 2.0, 5)
        kfs.append({"time": t, "x": off, "y": off, "w": w, "h": w})
    return kfs


def generate_zoom_keyframes(words, duration, **kw):
    """One-call: word timestamps → punch keyframes."""
    return punches_to_keyframes(generate_punch_points(words, **{
        k: v for k, v in kw.items()
        if k in ("min_spacing", "gap_threshold", "max_punches")
    }), duration)


def _num(v):
    """Compact FFmpeg number literal (no trailing zeros, no sci notation)."""
    f = float(v)
    if f == int(f):
        return str(int(f))
    return ("%.6f" % f).rstrip("0").rstrip(".")


def _piecewise(times, vals, var="on"):
    """FFmpeg piecewise-LINEAR expression through (times[i], vals[i]) in `var`,
    holding the first/last value outside the range. `times` must be sorted."""
    n = len(times)
    if n == 0:
        return "1"
    if n == 1:
        return _num(vals[0])
    expr = _num(vals[-1])  # after the last breakpoint: hold
    for i in range(n - 2, -1, -1):
        t0, t1, v0, v1 = times[i], times[i + 1], vals[i], vals[i + 1]
        span = (t1 - t0) or 1e-6
        seg = f"({_num(v0)}+({_num(v1 - v0)})*({var}-{_num(t0)})/{_num(span)})"
        expr = f"if(lt({var},{_num(t1)}),{seg},{expr})"
    # before the first breakpoint: hold the first value
    return f"if(lt({var},{_num(times[0])}),{_num(vals[0])},{expr})"


def build_zoompan_filter(keyframes, src_w, src_h, fps):
    """crop_keyframes → a single `zoompan` filter string, or None when the
    keyframes describe no zoom (all ~1.0) or inputs are unusable.

    zoom = 1/w per keyframe; time → output frame index via fps (zoompan's `on`
    variable). Centered viewport: x='iw/2-(iw/zoom/2)', y='ih/2-(ih/zoom/2)'.
    d=1 makes it a 1-in-1-out pass over the video; s pins the output size so
    the downstream canvas stage sees constant dimensions.
    """
    if not keyframes or not src_w or not src_h or not fps or fps <= 0:
        return None
    kfs = sorted(keyframes, key=lambda k: k["time"])
    frames = [round(float(k["time"]) * fps, 4) for k in kfs]
    zooms = []
    for k in kfs:
        w = float(k.get("w") or 1.0)
        zooms.append(1.0 / w if w > 0 else 1.0)
    if max(zooms) - 1.0 < 1e-3:
        return None  # nothing to zoom — keep the pre-feature passthrough
    zexpr = _piecewise(frames, zooms, var="on")
    return (
        f"zoompan=z='{zexpr}'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={int(src_w)}x{int(src_h)}:fps={_num(fps)}"
    )
