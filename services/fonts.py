"""
ClipForge AI — Server-Side Font Lookup
=========================================
Central name -> file-path lookup for text rendered server-side (logo,
headline, captions), so font resolution is explicit and deterministic
instead of relying on OS/fontconfig name matching (see the Phase 1
exploration finding: no "Noto Sans Telugu" font exists on this system at
all, and captions have likely been silently substituting a different font
this whole time).

Stage 3 (logo) bundled Manrope — logo's only actual font need; there's no
Inspector UI to change it, so it's always the default. Stage 4 (headline)
adds Outfit for the same reason: HeadlineSection in Inspector.jsx exposes
only text and color, never font/weight/italic/uppercase/stroke, so Outfit
at whatever weight the draft specifies is the only font headline can ever
actually need today.

Stage 5 (captions) bundles the deterministic caption fonts (Noto Sans
Telugu = default, Ramabhadra + Mandali = selectable) and points libass at
them via the `ass` filter's `fontsdir`, so caption font resolution no
longer depends on host fontconfig (which silently substituted whatever
Telugu-capable font the machine happened to have — Nirmala UI on Windows,
possibly nothing/tofu in a Linux container). Suranna/Gidugu were evaluated
but dropped from captions (too light to read over video) — future headline
candidates. License files live alongside each font's own subdirectory.
"""

import os

FONTS_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")

FONT_FILES = {
    "Manrope": os.path.join(FONTS_DIR, "manrope", "Manrope[wght].ttf"),
    "Outfit": os.path.join(FONTS_DIR, "outfit", "Outfit[wght].ttf"),
}

DEFAULT_FONT = "Manrope"


def get_font_path(name: str) -> str:
    """Explicit file path for a font name; falls back to DEFAULT_FONT for
    anything not yet bundled, rather than raising — a not-yet-bundled
    choice should render in SOME real font, not crash the render."""
    return FONT_FILES.get(name, FONT_FILES[DEFAULT_FONT])


# ── Caption fonts (Stage 5) ────────────────────────────────────────────────
# Keys are the fonts' real internal family names — used verbatim as the ASS
# `Fontname`, and resolved to bundled files by libass via `fontsdir`
# (CAPTION_FONTS_DIR). Static Regular instances (Noto's variable [wght] axis
# was instanced at 400) to avoid libass variable-font weight ambiguity.
CAPTION_FONTS = {
    "Noto Sans Telugu": os.path.join(FONTS_DIR, "noto-sans-telugu", "NotoSansTelugu-Regular.ttf"),
    "Ramabhadra":       os.path.join(FONTS_DIR, "ramabhadra", "Ramabhadra-Regular.ttf"),
    "Mandali":          os.path.join(FONTS_DIR, "mandali", "Mandali-Regular.ttf"),
}

DEFAULT_CAPTION_FONT = "Noto Sans Telugu"

# Directory handed to the ass filter as `fontsdir`. It also contains the
# logo/headline fonts (manrope/outfit) — harmless: libass indexes the tree but
# the .ass only references caption fonts by their family name.
CAPTION_FONTS_DIR = FONTS_DIR


def get_caption_font(name: str):
    """(ass_family_name, file_path) for a caption font. Unknown/None falls back
    to DEFAULT_CAPTION_FONT rather than raising — a bad selection should render
    in the default deterministic font, never crash or silently hit host
    fontconfig."""
    if name not in CAPTION_FONTS:
        name = DEFAULT_CAPTION_FONT
    return name, CAPTION_FONTS[name]
