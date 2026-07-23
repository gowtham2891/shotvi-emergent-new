# -*- coding: utf-8 -*-
"""Feature #13 — auto-zoom / punch-ins.

Punch beats from word gaps → centered-zoom crop_keyframes → a single FFmpeg
zoompan filter. The keyframe math + filter-string builder are pinned here;
the actual zoompan render is validated on real media in the manual pass
(constant output size, 1-in-1-out frame count).
"""

import pytest

from services.auto_zoom import (
    generate_punch_points,
    punches_to_keyframes,
    build_zoompan_filter,
    PUNCH_ZOOM,
)


# ── beat selection ──────────────────────────────────────────────────────────

def test_punches_on_words_after_a_pause():
    words = [
        {"start": 0.0, "end": 0.4},   # first word — seeds prevEnd, never a punch
        {"start": 0.9, "end": 1.3},   # gap 0.5 ≥ 0.35 → beat (first punch)
        {"start": 1.3, "end": 1.7},   # gap 0 → no beat
        {"start": 5.0, "end": 5.4},   # gap 3.3 → beat, spaced > 2.5 from last
    ]
    pts = generate_punch_points(words)
    assert pts == [0.9, 5.0]


def test_min_spacing_throttles_close_beats():
    words = [
        {"start": 1.0, "end": 1.2},  # first word — never an auto-punch
        {"start": 2.0, "end": 2.2},  # gap 0.8 ≥ 0.35 → beat (first real punch)
        {"start": 2.8, "end": 3.0},  # gap 0.6 beat but only 0.8s after last → throttled
        {"start": 5.5, "end": 5.7},  # 3.5s after last → allowed
    ]
    pts = generate_punch_points(words, min_spacing=2.5)
    assert pts == [2.0, 5.5]


def test_max_punches_cap():
    words = [{"start": i * 3.0, "end": i * 3.0 + 0.2} for i in range(20)]
    assert len(generate_punch_points(words, max_punches=5)) == 5


def test_no_words_no_punches():
    assert generate_punch_points([]) == []
    assert generate_punch_points([{"end": 1.0}]) == []  # no start


# ── keyframe shape ──────────────────────────────────────────────────────────

def test_single_punch_is_a_centered_zoom_bump():
    kfs = punches_to_keyframes([2.0], duration=5.0)
    times = [k["time"] for k in kfs]
    assert times == [1.8, 2.0, 2.2]  # rise, peak, fall
    peak = kfs[1]
    assert peak["w"] == pytest.approx(1 / PUNCH_ZOOM, abs=1e-4)
    assert peak["h"] == peak["w"]
    # centered: x == (1 - w)/2
    assert peak["x"] == pytest.approx((1 - peak["w"]) / 2, abs=1e-4)
    assert peak["x"] == peak["y"]
    # endpoints are full-frame (no zoom)
    assert kfs[0]["w"] == pytest.approx(1.0, abs=1e-4)
    assert kfs[2]["w"] == pytest.approx(1.0, abs=1e-4)


def test_times_clamp_into_clip():
    # punch near t=0 — the rise breakpoint would be negative, clamped to 0.
    kfs = punches_to_keyframes([0.1], duration=5.0)
    assert kfs[0]["time"] == 0.0
    assert all(0.0 <= k["time"] <= 5.0 for k in kfs)


def test_overlapping_punches_combine_via_max():
    # Two punches 0.2s apart: the trough between them keeps the higher zoom
    # rather than dipping back to 1.0.
    kfs = punches_to_keyframes([2.0, 2.2], duration=5.0)
    zooms = {k["time"]: 1 / k["w"] for k in kfs}
    # at t=2.1 (between peaks) zoom must be > 1.0
    mid = min(kfs, key=lambda k: abs(k["time"] - 2.1))
    assert 1 / mid["w"] > 1.0


def test_empty_punches_or_bad_duration():
    assert punches_to_keyframes([], 5.0) == []
    assert punches_to_keyframes([2.0], 0) == []


# ── zoompan filter string ───────────────────────────────────────────────────

def test_filter_has_centered_zoompan_with_source_size_and_fps():
    kfs = punches_to_keyframes([2.0], duration=5.0)
    f = build_zoompan_filter(kfs, 1280, 640, 24.0)
    assert f.startswith("zoompan=")
    assert "s=1280x640" in f
    assert "fps=24" in f
    assert "iw/2-(iw/zoom/2)" in f and "ih/2-(ih/zoom/2)" in f
    assert "d=1" in f
    # zoom expression references the output-frame index `on`
    assert "on" in f


def test_filter_is_none_when_no_zoom():
    # all-full-frame keyframes describe no zoom → passthrough (None).
    flat = [{"time": 0, "x": 0, "y": 0, "w": 1.0, "h": 1.0},
            {"time": 5, "x": 0, "y": 0, "w": 1.0, "h": 1.0}]
    assert build_zoompan_filter(flat, 1280, 640, 24.0) is None
    assert build_zoompan_filter([], 1280, 640, 24.0) is None


def test_filter_guards_bad_dims_fps():
    kfs = punches_to_keyframes([2.0], duration=5.0)
    assert build_zoompan_filter(kfs, 0, 640, 24.0) is None
    assert build_zoompan_filter(kfs, 1280, 640, 0) is None
