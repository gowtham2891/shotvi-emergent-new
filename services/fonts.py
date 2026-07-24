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
#
# LAYOUT INVARIANT (DIAGNOSIS_FONTS.md): every caption .ttf MUST be an
# IMMEDIATE child of CAPTION_FONTS_DIR. libass's fontsdir scan is
# NON-RECURSIVE — it fopen()s each directory entry as a font file, so a font
# in a subdirectory is never loaded and libass silently substitutes a system
# font (Nirmala UI on Windows, tofu elsewhere) for every export. Keep this
# directory flat: .ttf files only (non-font files log an "Error opening
# memory font"; subdirectories like licenses/ are skipped). Guarded by
# tests/test_caption_font_resolution.py.
# Telugu-script caption fonts (Telugu caption mode). Keys are the fonts' real
# internal family names.
TELUGU_CAPTION_FONTS = {
    "Noto Sans Telugu": os.path.join(FONTS_DIR, "captions", "NotoSansTelugu-Regular.ttf"),
    "Ramabhadra":       os.path.join(FONTS_DIR, "captions", "Ramabhadra-Regular.ttf"),
    "Mandali":          os.path.join(FONTS_DIR, "captions", "Mandali-Regular.ttf"),
}

# Latin caption fonts (TANGLISH mode — Telugu written in Latin script). Heavy
# short-form-video display fonts, each a single static instance with the target
# weight baked into the outlines and its OS/2 weight-class normalized to 400,
# so libass resolves each by family name with no faux-bold. Latin glyph
# coverage only — used ONLY for tanglish captions, never Telugu script (which
# these fonts cannot render). Downloaded from Google Fonts (OFL).
LATIN_CAPTION_FONTS = {
    "Montserrat": os.path.join(FONTS_DIR, "captions", "Montserrat-Black.ttf"),
    "Anton":      os.path.join(FONTS_DIR, "captions", "Anton-Regular.ttf"),
    "Bebas Neue": os.path.join(FONTS_DIR, "captions", "BebasNeue-Regular.ttf"),
    "Oswald":     os.path.join(FONTS_DIR, "captions", "Oswald-Bold.ttf"),
    "Poppins":    os.path.join(FONTS_DIR, "captions", "Poppins-Bold.ttf"),
    "Inter":      os.path.join(FONTS_DIR, "captions", "Inter-Bold.ttf"),
}

# Merged view — every caption .ttf libass may resolve (all flat in the
# fontsdir). Kept as CAPTION_FONTS for backward compatibility (get_caption_font,
# tests, the frontend's font list).
CAPTION_FONTS = {**TELUGU_CAPTION_FONTS, **LATIN_CAPTION_FONTS}

DEFAULT_CAPTION_FONT = "Noto Sans Telugu"        # Telugu mode default
DEFAULT_LATIN_CAPTION_FONT = "Montserrat"        # Tanglish mode default (Montserrat Black)

# Directory handed to the ass filter as `fontsdir` — the flat directory whose
# immediate children are exactly the caption .ttf files above (OFL licenses
# live in captions/licenses/, out of libass's scan). The logo/headline fonts
# (manrope/outfit) are NOT here: they are resolved by explicit file path via
# get_font_path, never through fontsdir.
CAPTION_FONTS_DIR = os.path.join(FONTS_DIR, "captions")


def get_caption_font(name: str):
    """(ass_family_name, file_path) for a caption font. Unknown/None falls back
    to DEFAULT_CAPTION_FONT rather than raising — a bad selection should render
    in the default deterministic font, never crash or silently hit host
    fontconfig.

    Script-agnostic (legacy). Prefer resolve_caption_font(name, script) so the
    burn NEVER tries a Telugu-only font on Tanglish text (tofu) or a Latin-only
    font on Telugu text (tofu)."""
    if name not in CAPTION_FONTS:
        name = DEFAULT_CAPTION_FONT
    return name, CAPTION_FONTS[name]


def is_latin_caption_font(name: str) -> bool:
    return name in LATIN_CAPTION_FONTS


def resolve_caption_font(name: str, script: str = "telugu"):
    """Script-aware caption font resolution → (ass_family_name, file_path).

    HARD rule (no exceptions): Telugu-script captions render ONLY in a Telugu
    font; Tanglish (Latin-script) captions render ONLY in a Latin font — a
    Telugu font has no Latin display glyphs worth using and vice-versa, so a
    cross-script pick would tofu. A `name` that isn't valid for the active
    script falls back to that script's default (Noto Sans Telugu / Montserrat
    Black), never to the other script's set."""
    if script == "tanglish":
        if name not in LATIN_CAPTION_FONTS:
            name = DEFAULT_LATIN_CAPTION_FONT
        return name, LATIN_CAPTION_FONTS[name]
    if name not in TELUGU_CAPTION_FONTS:
        name = DEFAULT_CAPTION_FONT
    return name, TELUGU_CAPTION_FONTS[name]
