"""
Commit 4 — unified caption anchoring unit tests (services/caption_renderer.py).

Post-Commit-4 invariants:

  1. EVERY generated ASS carries an explicit {\\an5\\pos(cx,cy)} prefix on every
     karaoke event — untouched captions AND dragged captions share the SAME
     positioning code path. No dual "unpositioned bottom-anchored / positioned
     center-anchored" branches, no drift between preview and export by line
     count or aspect ratio.

  2. Untouched-caption default anchor equals the frontend's untouched-caption
     default (defaultElementForType('caption') in useAppStore.js — x=0.5,
     y=0.82). The regression gate: the pixel `\\pos` in the ASS matches
     round(0.5*W, 0.82*H) exactly, on every aspect ratio (so preview centering
     and export centering land at the same output pixel).

  3. Dragged captions (both caption_x and caption_y provided) continue to
     center at the exact (caption_x*W, caption_y*H) they were dragged to — no
     regression in the Stage 6 WYSIWYG-drag path.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.caption_renderer import (
    generate_ass_karaoke,
    CAPTION_DEFAULT_X_FRAC,
    CAPTION_DEFAULT_Y_FRAC,
)
from services.canvas_coords import to_pixel_center


def _lines():
    words = [{"word": "one", "start": 0.0, "end": 0.5},
             {"word": "two", "start": 0.5, "end": 1.0},
             {"word": "three", "start": 1.0, "end": 1.5}]
    return [{"words": words, "line_start": 0.0, "line_end": 2.0}]


def _dialogue_texts(ass):
    # Text is the 10th field (index 9); it may itself contain commas (\pos(x,y)),
    # so rejoin everything from field 9 onward.
    out = []
    for line in ass.splitlines():
        if line.startswith("Dialogue"):
            out.append(",".join(line.split(",")[9:]))
    return out


def _style_line(ass):
    return next(l for l in ass.splitlines() if l.startswith("Style: Default"))


# ── 1. Single positioning code path (Commit 4) ───────────────────────────────

def test_every_event_carries_an5_pos_prefix_even_untouched():
    """The whole point of Commit 4 — no unpositioned branch. Every karaoke
    event, whether the user ever touched the caption or not, gets an explicit
    \\an5\\pos so preview and export share ONE positioning code path."""
    ass = generate_ass_karaoke(_lines(), "bold-yellow")
    texts = _dialogue_texts(ass)
    assert texts, "no events generated"
    for t in texts:
        assert t.startswith("{\\an5\\pos("), (
            f"event missing explicit \\an5\\pos prefix (Commit 4 requires it "
            f"unconditionally): {t[:60]!r}"
        )


def test_style_alignment_is_5_center_anchor():
    """Style Alignment is 5 (center) — matches the \\an5 on every event, so
    the two never disagree if someone reads the Style line in isolation."""
    style = _style_line(ass=generate_ass_karaoke(_lines(), "bold-yellow"))
    fields = style.split(",")
    # Alignment is the 4th-from-last field before MarginL/MarginR/MarginV/Encoding
    assert fields[-5] == "5", f"expected Alignment=5, got Style line: {style}"


# ── 2. Untouched-caption default anchor matches frontend preview ─────────────

def test_untouched_caption_matches_frontend_default_anchor():
    """Regression gate for the "preview says y=0.82, export bottom-anchored at
    ~84%" mismatch. Post-Commit-4, the untouched-caption \\pos in the ASS must
    equal round(video_width * CAPTION_DEFAULT_X_FRAC,
              video_height * CAPTION_DEFAULT_Y_FRAC) — the frontend's untouched
    center, which is what ElementRenderer.jsx / defaultElementForType render at."""
    W, H = 1080, 1920
    ass = generate_ass_karaoke(_lines(), "bold-yellow", video_width=W, video_height=H)
    expected = to_pixel_center(CAPTION_DEFAULT_X_FRAC, CAPTION_DEFAULT_Y_FRAC, W, H)
    for t in _dialogue_texts(ass):
        assert f"\\pos({expected.cx},{expected.cy})" in t, (
            f"untouched-caption ASS \\pos does not equal frontend default center "
            f"(expected \\pos({expected.cx},{expected.cy}), event text: {t[:80]!r})"
        )


def test_frontend_default_matches_useappstore_and_renders_contract():
    """Backend defaults MUST match the frontend contract (source of truth in
    useAppStore.js :: defaultElementForType('caption') and renders.js ::
    CAPTION_DEFAULT_POSITION). This is a plain constant equality — if the
    frontend default moves, this test's value must be updated in lockstep."""
    assert CAPTION_DEFAULT_X_FRAC == 0.5, (
        "backend CAPTION_DEFAULT_X_FRAC must match frontend base element x=0.5"
    )
    assert CAPTION_DEFAULT_Y_FRAC == 0.82, (
        "backend CAPTION_DEFAULT_Y_FRAC must match frontend caption y=0.82"
    )


def test_untouched_default_uses_render_resolution_pixels_on_1_1_and_16_9():
    """Default \\pos scales with the ACTUAL render dims — the worker now always
    passes target_w/target_h. Was 9:16-only before Commit 4 (see KNOWN_ISSUES a)."""
    for W, H in [(1080, 1080), (1920, 1080), (720, 1280)]:
        ass = generate_ass_karaoke(_lines(), "bold-yellow", video_width=W, video_height=H)
        expected = to_pixel_center(CAPTION_DEFAULT_X_FRAC, CAPTION_DEFAULT_Y_FRAC, W, H)
        for t in _dialogue_texts(ass):
            assert f"\\pos({expected.cx},{expected.cy})" in t, (
                f"{W}x{H}: expected \\pos({expected.cx},{expected.cy}), got {t[:60]!r}"
            )
        assert f"PlayResX: {W}" in ass and f"PlayResY: {H}" in ass


def test_partial_caption_x_or_y_falls_back_to_default_axis():
    """A lone caption_x or caption_y falls back to the default on the missing
    axis — no partial half-positioned mess, no crash."""
    W, H = 1080, 1920
    only_x = generate_ass_karaoke(_lines(), "bold-yellow", video_width=W, video_height=H,
                                  caption_x=0.3, caption_y=None)
    only_y = generate_ass_karaoke(_lines(), "bold-yellow", video_width=W, video_height=H,
                                  caption_x=None, caption_y=0.3)
    # only_x: cx from 0.3, cy from default_y
    ec = to_pixel_center(0.3, CAPTION_DEFAULT_Y_FRAC, W, H)
    for t in _dialogue_texts(only_x):
        assert f"\\pos({ec.cx},{ec.cy})" in t
    # only_y: cx from default_x, cy from 0.3
    ec = to_pixel_center(CAPTION_DEFAULT_X_FRAC, 0.3, W, H)
    for t in _dialogue_texts(only_y):
        assert f"\\pos({ec.cx},{ec.cy})" in t


def test_none_and_both_none_are_byte_identical():
    """No hidden state — omitting caption_x/y or explicitly passing None is the
    same call."""
    a = generate_ass_karaoke(_lines(), "red-pop")
    b = generate_ass_karaoke(_lines(), "red-pop", caption_x=None, caption_y=None)
    assert a == b, "passing caption_x/caption_y=None must not change output"


# ── 3. Dragged-caption path (Stage 6 — must still work post-Commit-4) ────────

def test_positioned_prefixes_every_event_with_an5_pos():
    ass = generate_ass_karaoke(_lines(), "bold-yellow",
                               video_width=1080, video_height=1920,
                               caption_x=0.5, caption_y=0.84)
    c = to_pixel_center(0.5, 0.84, 1080, 1920)
    expect = f"{{\\an5\\pos({c.cx},{c.cy})}}"
    texts = _dialogue_texts(ass)
    assert texts, "no events generated"
    for t in texts:
        assert t.startswith(expect), f"event missing center-anchored \\pos prefix: {t[:40]!r}"


def test_positioned_uses_render_resolution_pixels_non_9_16():
    # 1:1 output — pixel conversion must use the REAL dims, and PlayRes must match
    # them so \pos lands at literal pixels (no stretch).
    W, H = 1080, 1080
    ass = generate_ass_karaoke(_lines(), "bold-yellow",
                               video_width=W, video_height=H,
                               caption_x=0.25, caption_y=0.9)
    c = to_pixel_center(0.25, 0.9, W, H)   # (270, 972)
    assert c.cx == 270 and c.cy == 972
    assert f"\\pos({c.cx},{c.cy})" in ass
    # PlayRes == conversion dims (the structural guarantee)
    assert f"PlayResX: {W}" in ass and f"PlayResY: {H}" in ass


def test_positioned_center_anchor_matches_preview_intent():
    # \an5 (center) — not \an2 (bottom) — so the block centers on the dragged point.
    ass = generate_ass_karaoke(_lines(), "outline-only",
                               caption_x=0.1, caption_y=0.1)
    for t in _dialogue_texts(ass):
        assert "\\an5" in t and "\\an2" not in t
