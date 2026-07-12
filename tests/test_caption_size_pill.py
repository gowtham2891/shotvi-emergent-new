"""
BUG-001 partial-fix regression gate — the editor's caption Size and
Background Pill must reach the exported ASS.

Historically, `getEditDocument` serialized only style + captionX + captionY
for the caption element; `RerenderRequest` had no fields for `fontSize` or
`pill`, and `generate_ass_karaoke` used the preset's fixed values. So the
preview happily reflected slider drags and the pill toggle while the burned
export ignored them (WYSIWYG break — the audit's HIGH #1).

Post-fix, the chain is: getEditDocument → buildRerenderRequest →
RerenderRequest.caption_font_size / caption_pill → rerender_clip →
render_captions_for_clip → generate_ass_karaoke, which reflects them in the
emitted Style: line. This file guards the backend half of that chain (the
frontend half is asserted in frontend/src/__tests__/editDocument.test.js).

Scope note: Animation is intentionally NOT tested here — Fix 7b disables the
Inspector control (Animation is deferred to a future round); only fontSize +
pill are wired through in this partial fix.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.caption_renderer import generate_ass_karaoke, STYLES


def _words_line():
    return [{"words": [{"word": "hi", "start": 0.0, "end": 0.5}],
             "line_start": 0.0, "line_end": 0.5}]


def _style_fields(ass):
    """Return the CSV fields of the `Style: Default` line."""
    for line in ass.splitlines():
        if line.startswith("Style: Default,"):
            return line[len("Style: "):].split(",")
    raise AssertionError(f"no Style: Default line in ASS:\n{ass}")


def _get_field(fields, name):
    # Layout matches the Style Format: header (24 columns).
    idx = {
        "Name": 0, "Fontname": 1, "Fontsize": 2,
        "PrimaryColour": 3, "SecondaryColour": 4,
        "OutlineColour": 5, "BackColour": 6,
        "Bold": 7, "Italic": 8, "Underline": 9, "StrikeOut": 10,
        "ScaleX": 11, "ScaleY": 12, "Spacing": 13, "Angle": 14,
        "BorderStyle": 15, "Outline": 16, "Shadow": 17,
        "Alignment": 18, "MarginL": 19, "MarginR": 20, "MarginV": 21,
        "Encoding": 22,
    }[name]
    return fields[idx]


# ── caption_font_size_frac wiring ───────────────────────────────────────────

def test_omitted_font_size_matches_preset_default():
    """When the frontend didn't touch Size, the backend must render the exact
    Style line it did before this argument existed (byte-identical on that
    axis — the calibrated per-font k stays applied)."""
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               video_width=1080, video_height=1920)
    ass_with_none = generate_ass_karaoke(_words_line(), "bold-yellow",
                                         video_width=1080, video_height=1920,
                                         caption_font_size_frac=None)
    assert ass == ass_with_none


def test_font_size_frac_changes_the_style_font_size():
    """User dragged Size from 0.05 (typical preview default) to 0.08 → the
    Fontsize on the Style line changes proportionally."""
    small = generate_ass_karaoke(_words_line(), "bold-yellow",
                                 video_width=1080, video_height=1920,
                                 caption_font_size_frac=0.05)
    large = generate_ass_karaoke(_words_line(), "bold-yellow",
                                 video_width=1080, video_height=1920,
                                 caption_font_size_frac=0.08)
    small_px = int(_get_field(_style_fields(small), "Fontsize"))
    large_px = int(_get_field(_style_fields(large), "Fontsize"))
    assert large_px > small_px, (
        f"Fontsize should scale with caption_font_size_frac: small={small_px}, large={large_px}"
    )
    # 0.05 * 1920 = 96, 0.08 * 1920 = 153.6 → round(153.6) = 154. Sanity.
    assert small_px == 96 and large_px == 154


def test_font_size_scales_with_video_height_not_width():
    """Same fraction, different render heights → different pixel size. Same
    fraction, different render widths → SAME pixel size (Size is a fraction
    of HEIGHT, matching the preview's `elHeight = canvasH * fontSize` math)."""
    a = generate_ass_karaoke(_words_line(), "bold-yellow",
                             video_width=1080, video_height=1920,
                             caption_font_size_frac=0.05)
    b = generate_ass_karaoke(_words_line(), "bold-yellow",
                             video_width=1080, video_height=1080,
                             caption_font_size_frac=0.05)
    c = generate_ass_karaoke(_words_line(), "bold-yellow",
                             video_width=1920, video_height=1920,
                             caption_font_size_frac=0.05)
    a_px = int(_get_field(_style_fields(a), "Fontsize"))
    b_px = int(_get_field(_style_fields(b), "Fontsize"))
    c_px = int(_get_field(_style_fields(c), "Fontsize"))
    assert a_px != b_px, "different heights should scale differently"
    assert a_px == c_px, "same height, different width → same Fontsize"


def test_font_size_frac_clamped_to_minimum_visible_pixels():
    """A crazy-tiny fraction (e.g. 0.001) must still emit at least an 8-pixel
    Fontsize so libass has something to render (defensive floor, not a UX)."""
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               video_width=1080, video_height=1920,
                               caption_font_size_frac=0.0001)
    assert int(_get_field(_style_fields(ass), "Fontsize")) >= 8


# ── caption_pill wiring ────────────────────────────────────────────────────

def test_pill_none_leaves_style_backcolour_at_preset_value():
    """When no pill is set, BackColour must equal the preset's back_color
    (byte-identical to today)."""
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               video_width=1080, video_height=1920,
                               caption_pill=None)
    assert _get_field(_style_fields(ass), "BackColour") == STYLES["bold-yellow"]["back_color"]


def test_pill_disabled_is_the_same_as_pill_none():
    """`enabled: False` must be a full no-op — otherwise a toggle-off in the
    Inspector could still drift the ASS."""
    off = generate_ass_karaoke(_words_line(), "bold-yellow",
                               caption_pill={"enabled": False, "color": "#ff0000", "opacity": 1.0})
    plain = generate_ass_karaoke(_words_line(), "bold-yellow")
    assert off == plain


def test_pill_enabled_overrides_backcolour_and_border_style():
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               caption_pill={"enabled": True, "color": "#7c3aed",
                                             "opacity": 1.0, "padding": 12, "radius": 8})
    f = _style_fields(ass)
    # BackColour is &HAA BB GG RR — opacity 1.0 → alpha 00, colour #7C3AED reversed → EDBB7C? Let's decode:
    # #7c3aed → r=7C, g=3A, b=ED. ASS wants &H{aa}{bb}{gg}{rr} → &H00ED3A7C.
    assert _get_field(f, "BackColour") == "&H00ED3A7C"
    # Enabled pill switches to BorderStyle=4 (opaque box), no outline.
    assert _get_field(f, "BorderStyle") == "4"
    assert _get_field(f, "Outline") == "0"


def test_pill_opacity_maps_to_ass_alpha_correctly():
    """ASS alpha is inverse of opacity — 1.0 → 00, 0.5 → 80, 0.0 → FF."""
    for opacity, expected_alpha in [(1.0, "00"), (0.5, "80"), (0.0, "FF")]:
        ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                                   caption_pill={"enabled": True, "color": "#000000",
                                                 "opacity": opacity, "padding": 0, "radius": 0})
        bc = _get_field(_style_fields(ass), "BackColour")
        assert bc.startswith(f"&H{expected_alpha}"), (
            f"opacity {opacity} → expected alpha {expected_alpha}, got {bc}"
        )


def test_pill_malformed_color_falls_back_safely():
    """A junk hex ('nope') must not crash — it falls back to opaque black
    (better than a 500 in the burn stage)."""
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               caption_pill={"enabled": True, "color": "nope",
                                             "opacity": 1.0, "padding": 0, "radius": 0})
    bc = _get_field(_style_fields(ass), "BackColour")
    assert bc == "&H00000000"


# ── EditDocument end-to-end parity ─────────────────────────────────────────

def test_ass_reflects_a_changed_edit_document():
    """The single parity assertion the task called for: two different
    EditDocument-level values for fontSize + pill must produce two
    correspondingly different ASS files."""
    baseline = generate_ass_karaoke(_words_line(), "bold-yellow",
                                    video_width=1080, video_height=1920)
    edited = generate_ass_karaoke(_words_line(), "bold-yellow",
                                  video_width=1080, video_height=1920,
                                  caption_font_size_frac=0.075,
                                  caption_pill={"enabled": True, "color": "#00ff88",
                                                "opacity": 0.6, "padding": 10, "radius": 6})
    assert baseline != edited, "editor changes must reach the ASS"
    fields = _style_fields(edited)
    # Fontsize reflects the 0.075 frac: 0.075 * 1920 = 144.
    assert int(_get_field(fields, "Fontsize")) == 144
    # BackColour reflects the pill: #00ff88, opacity 0.6 → alpha 66.
    # 0.6 opacity → alpha = round((1-0.6)*255) = 102 = 0x66.
    # ASS &HAABBGGRR: aa=66, bb=88 (b of the hex), gg=FF, rr=00 → &H668800FF? Actually:
    #   #00ff88 → r=00, g=FF, b=88 → &H66 88 FF 00 → &H6688FF00
    assert _get_field(fields, "BackColour") == "&H6688FF00"
