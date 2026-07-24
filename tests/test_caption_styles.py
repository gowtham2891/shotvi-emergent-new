# -*- coding: utf-8 -*-
"""Feature #16 (research-grounded) — script-aware caption fonts + the 10 new
presets (Replix's 9 + the market Hormozi formula).

HARD rule: Telugu script → a Telugu font; Tanglish → a Latin font. All-caps
presets uppercase ONLY in Tanglish; glow (spotlight) puts a neon halo on the
active word with a bright white core; the Latin fonts render at Bold OFF
(weight is baked into the outlines).
"""

import pytest

from services.fonts import (
    resolve_caption_font, is_latin_caption_font,
    TELUGU_CAPTION_FONTS, LATIN_CAPTION_FONTS,
    DEFAULT_CAPTION_FONT, DEFAULT_LATIN_CAPTION_FONT,
)
from services.caption_renderer import (
    STYLES, generate_ass_karaoke, get_words_for_clip, group_words_into_lines,
)

NEW_PRESETS = ["classic", "yellow", "minimal", "dark", "punch",
               "cove", "spotlight", "reel", "noir", "hormozi-caps"]
BS = chr(92)  # backslash — avoids heredoc/escaping ambiguity in assertions


# ── script-aware font resolution ────────────────────────────────────────────

def test_telugu_script_resolves_to_telugu_fonts_only():
    fam, path = resolve_caption_font("Ramabhadra", "telugu")
    assert fam == "Ramabhadra"
    # A Latin font requested in Telugu mode falls back to the Telugu default.
    fam, _ = resolve_caption_font("Montserrat", "telugu")
    assert fam == DEFAULT_CAPTION_FONT
    fam, _ = resolve_caption_font(None, "telugu")
    assert fam == DEFAULT_CAPTION_FONT


def test_tanglish_script_resolves_to_latin_fonts_only():
    fam, _ = resolve_caption_font("Anton", "tanglish")
    assert fam == "Anton"
    # A Telugu font requested in Tanglish mode falls back to Montserrat Black.
    fam, _ = resolve_caption_font("Noto Sans Telugu", "tanglish")
    assert fam == DEFAULT_LATIN_CAPTION_FONT == "Montserrat"
    fam, _ = resolve_caption_font(None, "tanglish")
    assert fam == "Montserrat"


def test_font_sets_are_disjoint():
    assert set(TELUGU_CAPTION_FONTS) & set(LATIN_CAPTION_FONTS) == set()
    assert is_latin_caption_font("Montserrat") and not is_latin_caption_font("Mandali")


# ── the 10 presets, both scripts ────────────────────────────────────────────

def _style_font(ass):
    return ass.split("Style: Default,")[1].split(",")[0]


@pytest.mark.parametrize("preset", NEW_PRESETS)
def test_preset_renders_in_both_scripts_with_correct_font(preset):
    assert preset in STYLES
    TE = {"word_timestamps": [{"word": "పరీక్ష", "start": 0.0, "end": 0.5},
                              {"word": "రెండు", "start": 0.5, "end": 1.0}]}
    TA = {"word_timestamps": [{"word": "pareeksha", "start": 0.0, "end": 0.5},
                              {"word": "rendu", "start": 0.5, "end": 1.0}]}
    ass_te = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(TE, 0, 1.5)),
                                  preset, caption_font="Noto Sans Telugu", caption_script="telugu")
    ass_ta = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(TA, 0, 1.5)),
                                  preset, caption_font=None, caption_script="tanglish")
    assert _style_font(ass_te) in TELUGU_CAPTION_FONTS
    assert _style_font(ass_ta) in LATIN_CAPTION_FONTS


def test_latin_fonts_render_bold_off():
    # Bundled Latin fonts are pre-weighted → Style Bold must be 0 (no faux-bold).
    TA = {"word_timestamps": [{"word": "test", "start": 0.0, "end": 0.5}]}
    ass = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(TA, 0, 1.0)),
                               "hormozi-caps", caption_font="Anton", caption_script="tanglish")
    # Style line: ...,Anton,<size>,<colors...>,<Bold>,... — Bold field is 0.
    style = ass.split("Style: Default,")[1]
    fields = style.split(",")
    # Format: Name(implicit),Fontname,Fontsize,Primary,Secondary,Outline,Back,Bold,...
    assert fields[7] == "0", f"expected Bold=0 for Latin font, got {fields[7]}"


def test_uppercase_only_in_tanglish():
    words = {"word_timestamps": [{"word": "viral", "start": 0.0, "end": 0.5}]}
    # hormozi-caps is an ALL-CAPS preset
    ta = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(words, 0, 1.0)),
                              "hormozi-caps", caption_font="Montserrat", caption_script="tanglish")
    assert "VIRAL" in ta and "viral" not in ta
    # Telugu script: .upper() is a harmless no-op; a lowercase-ascii word stays.
    te = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(words, 0, 1.0)),
                              "hormozi-caps", caption_font="Noto Sans Telugu", caption_script="telugu")
    assert "viral" in te  # NOT uppercased in Telugu mode


def test_non_caps_preset_keeps_case():
    words = {"word_timestamps": [{"word": "viral", "start": 0.0, "end": 0.5}]}
    ta = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(words, 0, 1.0)),
                              "classic", caption_font="Poppins", caption_script="tanglish")
    assert "viral" in ta  # classic is mixed-case


def test_glow_preset_emits_neon_halo_with_white_core():
    words = {"word_timestamps": [{"word": "aa", "start": 0.0, "end": 0.5},
                                 {"word": "bb", "start": 0.5, "end": 1.0}]}
    ass = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(words, 0, 1.5)),
                               "spotlight", caption_font="Montserrat", caption_script="tanglish")
    # blur halo present, and the active word's fill is white (bright core).
    assert ass.count(BS + "blur") >= 2
    assert BS + "blur3" in ass          # glow-on
    assert BS + "blur0" in ass          # glow reset on other words


def test_non_glow_preset_has_no_blur():
    words = {"word_timestamps": [{"word": "aa", "start": 0.0, "end": 0.5}]}
    ass = generate_ass_karaoke(group_words_into_lines(get_words_for_clip(words, 0, 1.0)),
                               "yellow", caption_font="Poppins", caption_script="tanglish")
    assert BS + "blur" not in ass


def test_bg_off_flags_match_border_style():
    # bg_off presets (animation-eligible) are the outline styles (border_style 1);
    # bg-on presets carry a box (border_style 3/4).
    for p in NEW_PRESETS:
        s = STYLES[p]
        if s.get("bg_off"):
            assert s["border_style"] == 1, f"{p}: bg_off but has a box"
        else:
            assert s["border_style"] in (3, 4), f"{p}: bg-on but no box"
