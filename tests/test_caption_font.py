"""
Caption font dropdown — backend half of the chain.

The Inspector's Font dropdown offers exactly the three bundled Telugu caption
fonts (Noto Sans Telugu = default, Ramabhadra, Mandali). The selection flows
element props → getEditDocument → buildRerenderRequest → RerenderRequest.caption_font
→ rerender_clip → render_captions_for_clip → generate_ass_karaoke, which must
emit the chosen family as the ASS Style `Fontname`. libass then resolves it to
the bundled .ttf via `fontsdir` (services/fonts.py :: CAPTION_FONTS), so preview
and export render byte-identical shapes.

This file guards the backend half (frontend half: frontend/src/__tests__/editDocument.test.js).

Invariant under test: the selection flows THROUGH the calibrated per-font
k-values (Noto 0.495, Ramabhadra/Mandali 0.660), not around them — a heavier-
metric font is sized down so it renders at the same Latin cap-height.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.caption_renderer import generate_ass_karaoke, caption_font_size, STYLES
from services.fonts import CAPTION_FONTS, DEFAULT_CAPTION_FONT


def _words_line():
    return [{"words": [{"word": "hi", "start": 0.0, "end": 0.5}],
             "line_start": 0.0, "line_end": 0.5}]


def _style_fields(ass):
    for line in ass.splitlines():
        if line.startswith("Style: Default,"):
            return line[len("Style: "):].split(",")
    raise AssertionError(f"no Style: Default line in ASS:\n{ass}")


def _fontname(ass):
    # Fontname is the 2nd field of the Style line (Name, Fontname, Fontsize, …).
    return _style_fields(ass)[1]


def _fontsize(ass):
    return int(_style_fields(ass)[2])


# ── Fontname reflects the selection ─────────────────────────────────────────

def test_default_font_is_noto_sans_telugu():
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               video_width=1080, video_height=1920)
    assert _fontname(ass) == "Noto Sans Telugu"


def test_none_selection_behaves_exactly_as_today():
    """Passing caption_font=None must be identical to omitting it entirely —
    the untouched-default export is byte-identical to before the dropdown."""
    omitted = generate_ass_karaoke(_words_line(), "bold-yellow",
                                   video_width=1080, video_height=1920)
    explicit_none = generate_ass_karaoke(_words_line(), "bold-yellow",
                                         video_width=1080, video_height=1920,
                                         caption_font=None)
    assert omitted == explicit_none
    assert _fontname(explicit_none) == DEFAULT_CAPTION_FONT


@pytest.mark.parametrize("font", ["Noto Sans Telugu", "Ramabhadra", "Mandali"])
def test_selected_font_appears_as_ass_fontname(font):
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               video_width=1080, video_height=1920,
                               caption_font=font)
    assert _fontname(ass) == font
    # It must be one of the three bundled, fontsdir-resolvable families.
    assert font in CAPTION_FONTS


def test_unknown_font_falls_back_to_default_not_a_crash():
    ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                               video_width=1080, video_height=1920,
                               caption_font="Outfit")  # not a caption font
    assert _fontname(ass) == DEFAULT_CAPTION_FONT


# ── Selection flows THROUGH the calibrated k-values (invariant) ─────────────

def test_ramabhadra_scales_down_via_calibrated_k():
    """Same preset, different font: Ramabhadra's k (0.660) is heavier than
    Noto's (0.495), so at the preset default size it renders SMALLER in
    ASS Fontsize points to hit the same Latin cap-height. Proves the font
    dropdown flows through caption_font_size()'s calibration, not around it."""
    noto = generate_ass_karaoke(_words_line(), "bold-yellow",
                                video_width=1080, video_height=1920,
                                caption_font="Noto Sans Telugu")
    rama = generate_ass_karaoke(_words_line(), "bold-yellow",
                                video_width=1080, video_height=1920,
                                caption_font="Ramabhadra")
    assert _fontsize(rama) < _fontsize(noto)
    # Exact values from the calibration: bold-yellow font_size 62.
    assert _fontsize(noto) == caption_font_size(STYLES["bold-yellow"]["font_size"], "Noto Sans Telugu")
    assert _fontsize(rama) == caption_font_size(STYLES["bold-yellow"]["font_size"], "Ramabhadra")


def test_user_size_still_overrides_font_calibration():
    """When the user sets an explicit Size (fraction of height), it is used
    as-is regardless of font — the calibration only supplies the DEFAULT."""
    for font in ("Noto Sans Telugu", "Ramabhadra", "Mandali"):
        ass = generate_ass_karaoke(_words_line(), "bold-yellow",
                                   video_width=1080, video_height=1920,
                                   caption_font=font, caption_font_size_frac=0.05)
        assert _fontsize(ass) == round(0.05 * 1920)  # 96, same for every font
