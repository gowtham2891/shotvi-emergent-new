"""
ClipForge AI — Caption Renderer
=================================
Generates ASS subtitles with word-by-word karaoke highlight animation.
Each line shows MAX_WORDS_PER_LINE words. As each word is spoken, it
changes from white → highlight color. Already-spoken words go dim grey.

Styles supported:
  bold-yellow    — Yellow highlight, semi-transparent black bg (default)
  white-minimal  — White highlight, no background, clean look
  red-pop        — Red highlight, solid black pill bg, large font
  clean-dark     — Cyan highlight, solid dark bar bg, medium font
  hormozi        — Gold highlight, opaque black box, ultra-bold
  fire-gradient  — Orange highlight, no bg (gradient approximated by dominant color)
  neon-green     — Bright green highlight, dark box, glow shadow
  outline-only   — White text, heavy black outline, no background
  big-bold       — Gold highlight, giant font, 2 words per line
  typewriter     — White text, dark box, future words transparent
  split-color    — Pink/magenta highlight, no background
"""

import json
import os
import re
import sys
import subprocess


# ── Caption config ─────────────────────────────────────────────────────────────
MAX_WORDS_PER_LINE = 4
MAX_WORD_DURATION  = 1.5   # cap single-word duration (seconds)
MAX_LINE_DURATION  = 4.0   # cap single line display duration (seconds)


# ── Style presets ──────────────────────────────────────────────────────────────
# Colors in ASS format: &HAABBGGRR  (AA=alpha, 00=opaque)
# MUST stay in sync with frontend/src/hooks/useCaptions.js :: CAPTION_STYLES

STYLES = {
    "bold-yellow": {
        "font_name":      "Noto Sans Telugu SemiBold",
        "font_size":      62,
        "bold":           -1,
        "color_highlight": "&H0000FFFF",   # Yellow
        "color_spoken":    "&H00AAAAAA",   # Grey
        "color_unspoken":  "&H00FFFFFF",   # White
        "outline_color":   "&H00000000",   # Black
        "back_color":      "&H60000000",   # Semi-transparent black
        "outline_width":   3,
        "shadow":          0,
        "border_style":    1,              # 1 = outline+shadow, 3 = opaque box
    },
    "white-minimal": {
        "font_name":      "Noto Sans Telugu",
        "font_size":      52,
        "bold":           0,
        "color_highlight": "&H00FFFFFF",   # White
        "color_spoken":    "&H00CCCCCC",   # Light grey
        "color_unspoken":  "&H00AAAAAA",   # Grey
        "outline_color":   "&H00000000",   # Black
        "back_color":      "&H00000000",   # Transparent (no bg)
        "outline_width":   2,
        "shadow":          1,
        "border_style":    1,
    },
    "red-pop": {
        "font_name":      "Noto Sans Telugu",
        "font_size":      68,
        "bold":           -1,
        "color_highlight": "&H000000FF",   # Red (ASS BGR: FF0000 → 0000FF)
        "color_spoken":    "&H00888888",   # Grey
        "color_unspoken":  "&H00FFFFFF",   # White
        "outline_color":   "&H00000000",   # Black
        "back_color":      "&HCC000000",   # Near-opaque black box
        "outline_width":   3,
        "shadow":          0,
        "border_style":    3,              # Opaque box behind text
    },
    "clean-dark": {
        "font_name":      "Noto Sans Telugu",
        "font_size":      55,
        "bold":           0,
        "color_highlight": "&H00FFD700",   # Cyan (ASS BGR)
        "color_spoken":    "&H00999999",   # Grey
        "color_unspoken":  "&H00FFFFFF",   # White
        "outline_color":   "&H00000000",   # Black
        "back_color":      "&HDD000000",   # Dark solid bar
        "outline_width":   2,
        "shadow":          0,
        "border_style":    3,              # Solid bar
    },
    "hormozi": {
        "font_name":       "Noto Sans Telugu SemiBold",
        "font_size":       67,
        "bold":            -1,
        "color_highlight": "&H0000E5FF",   # #FFE500 → BGR 00E5FF
        "color_spoken":    "&H00CCCCCC",
        "color_unspoken":  "&H00FFFFFF",
        "outline_color":   "&H00000000",
        "back_color":      "&H14000000",   # rgba(0,0,0,0.92) → alpha 0x14
        "outline_width":   5,
        "shadow":          0,
        "border_style":    3,
    },
    "fire-gradient": {
        "font_name":       "Noto Sans Telugu SemiBold",
        "font_size":       64,
        "bold":            -1,
        "color_highlight": "&H00006BFF",   # #FF6B00 → BGR 006BFF (dominant orange; .ass has no gradients)
        "color_spoken":    "&H00888888",
        "color_unspoken":  "&H00FFFFFF",
        "outline_color":   "&H00000000",
        "back_color":      "&H00000000",
        "outline_width":   3,
        "shadow":          2,              # approximates orange fire glow
        "border_style":    1,
    },
    "neon-green": {
        "font_name":       "Noto Sans Telugu SemiBold",
        "font_size":       57,
        "bold":            -1,
        "color_highlight": "&H0041FF00",   # #00FF41 → BGR 41FF00
        "color_spoken":    "&H00166600",   # #006616 → BGR 166600
        "color_unspoken":  "&H00CCCCCC",
        "outline_color":   "&H00000000",
        "back_color":      "&H1F000000",   # rgba(0,0,0,0.88) → alpha 0x1F
        "outline_width":   2,
        "shadow":          1,
        "border_style":    3,
    },
    "outline-only": {
        "font_name":       "Noto Sans Telugu SemiBold",
        "font_size":       60,
        "bold":            -1,
        "color_highlight": "&H00FFFFFF",
        "color_spoken":    "&H00DDDDDD",   # #DDDDDD → BGR DDDDDD
        "color_unspoken":  "&H00FFFFFF",
        "outline_color":   "&H00000000",
        "back_color":      "&H00000000",
        "outline_width":   5,              # heavy outline; strokeWidth 8 in frontend
        "shadow":          0,
        "border_style":    1,
    },
    "big-bold": {
        "font_name":       "Noto Sans Telugu SemiBold",
        "font_size":       86,
        "bold":            -1,
        "color_highlight": "&H0000D7FF",   # #FFD700 → BGR 00D7FF
        "color_spoken":    "&H00AAAAAA",
        "color_unspoken":  "&H00FFFFFF",
        "outline_color":   "&H00000000",
        "back_color":      "&H00000000",
        "outline_width":   4,
        "shadow":          2,
        "border_style":    1,
        "words_per_line":  2,
    },
    "typewriter": {
        "font_name":       "Courier New",
        "font_size":       55,
        "bold":            0,
        "color_highlight": "&H00FFFFFF",
        "color_spoken":    "&H00FFFFFF",   # past words stay white (already-typed feel)
        "color_unspoken":  "&HFFFFFFFF",   # future words fully transparent (not yet typed)
        "outline_color":   "&H00000000",
        "back_color":      "&H4D000000",   # rgba(0,0,0,0.7) → alpha 0x4D
        "outline_width":   1,
        "shadow":          0,
        "border_style":    3,
    },
    "split-color": {
        "font_name":       "Noto Sans Telugu SemiBold",
        "font_size":       60,
        "bold":            -1,
        "color_highlight": "&H00C76EFF",   # #FF6EC7 → BGR C76EFF
        "color_spoken":    "&H00AAAAAA",
        "color_unspoken":  "&H00FFFFFF",
        "outline_color":   "&H00000000",
        "back_color":      "&H00000000",
        "outline_width":   3,
        "shadow":          1,
        "border_style":    1,
    },
}

DEFAULT_STYLE = "bold-yellow"


# ── Default caption position (Commit 4) ────────────────────────────────────
# Untouched-caption anchor, in normalized 0-1 center coordinates. Must match
# the frontend defaults (defaultElementForType('caption') in
# frontend/src/store/useAppStore.js — x from base = 0.5, y = 0.82 — and
# CAPTION_DEFAULT_POSITION in frontend/src/api/renders.js) so a caption the
# user never dragged renders at the SAME visual position in the editor
# preview and in the exported burn. Preview centers via translate(-50%,-50%);
# the export centers via ASS `\an5\pos` — one unified code path, one anchor.
CAPTION_DEFAULT_X_FRAC = 0.5
CAPTION_DEFAULT_Y_FRAC = 0.82


# ── Caption font cap-height calibration (Stage 5) ──────────────────────────────
# k = Latin cap-height (px) per point of ASS Fontsize, MEASURED VIA THE `ass`
# FILTER (the production burn path — see burn_captions) on the bundled static
# font instances. libass scales Fontsize by each font's vertical metrics, so
# Noto Sans Telugu (tall metrics, to fit Telugu's above+below matras) renders
# smaller per point than Ramabhadra/Mandali. These supersede the earlier
# Phase-A `subtitles`-filter numbers — that filter mis-shapes Telugu and is
# forbidden for the burn. Noto anchors each preset's target cap-height; the
# other fonts are sized to render at that same Latin cap-height.
CAPTION_FONT_CAP_K = {
    "Noto Sans Telugu": 0.495,
    "Ramabhadra":       0.660,
    "Mandali":          0.660,
}
_CAP_K_ANCHOR = CAPTION_FONT_CAP_K["Noto Sans Telugu"]


def caption_font_size(preset_font_size: int, caption_font: str) -> int:
    """ASS Fontsize for a (preset, caption_font) pair, calibrated so every font
    renders at the same Latin cap-height as Noto at the preset's canonical size.
    Noto keeps the preset's own size; heavier-metric fonts scale down to match.

    DO NOT bump the Noto anchor sizes (bold-yellow 62, red-pop 68, …). They stay
    at the presets' current nominals ON PURPOSE: the editor preview renders
    Telugu in system Noto Sans Telugu at ~31px cap-height @ nominal 62, which
    exactly matches this bundled Noto export (also ~31px) — so the current sizing
    already gives preview/export size parity. Bumping would make the export
    LARGER than the preview. (Measured in telugu_font_samples/PREVIEW_vs_export_size.png;
    the older "captions shrink vs Nirmala" concern was based on a wrong assumption
    that the preview uses Nirmala — it does not when Noto is installed.)"""
    k = CAPTION_FONT_CAP_K.get(caption_font, _CAP_K_ANCHOR)
    target_cap = preset_font_size * _CAP_K_ANCHOR
    return max(round(target_cap / k), 6)


# ══════════════════════════════════════════════════════════════════════════════
# Loaders
# ══════════════════════════════════════════════════════════════════════════════

def load_transcript(transcript_path: str) -> dict:
    with open(transcript_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_clips(clips_path: str) -> dict:
    with open(clips_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# Word extraction
# ══════════════════════════════════════════════════════════════════════════════

def get_words_for_clip(transcript: dict, clip_start: float, clip_end: float) -> list:
    """
    Extract words that fall within a clip time range.
    Handles both Sarvam V3 and faster-whisper transcript formats.
    """
    raw_words = []

    # Sarvam format: top-level word_timestamps list
    if transcript.get("word_timestamps"):
        raw_words = transcript["word_timestamps"]

    # Whisper format: words nested inside each segment
    if not raw_words:
        for segment in transcript.get("segments", []):
            for word in segment.get("words", []):
                raw_words.append(word)

    words = []
    for word in raw_words:
        w_start = word["start"]
        w_end   = word["end"]
        if w_end > clip_start and w_start < clip_end:
            adj_start = max(w_start, clip_start) - clip_start
            adj_end   = min(w_end,   clip_end)   - clip_start
            text = word["word"].strip()
            if text:
                words.append({
                    "word":  text,
                    "start": round(adj_start, 3),
                    "end":   round(adj_end,   3),
                })
    return words


def get_words_for_multisegment_clip(transcript: dict, clip: dict, sent_by_id: dict) -> list:
    """
    Extract + remap words for a clip with multiple (non-contiguous) segments
    — e.g. a dead zone (sponsor read, intro greeting) cut out of the middle.

    get_words_for_clip() alone would use clip["start"]/clip["end"], which
    spans the FULL original range including the cut-out dead zone. In the
    stitched output file, content after the first segment has shifted left
    by however much was cut, so word timestamps need to be remapped onto
    the output file's own timeline (segments stacked back-to-back) instead
    of the original video's timeline.
    """
    segments = clip.get("segments", [])
    if len(segments) <= 1:
        return get_words_for_clip(transcript, clip["start"], clip["end"])

    all_words = []
    output_time_offset = 0.0

    for seg in segments:
        s_id = int(seg["start_sent_id"])
        e_id = int(seg["end_sent_id"])

        seg_start = sent_by_id[s_id]["start"]
        seg_end   = sent_by_id[e_id]["end"]
        seg_duration = seg_end - seg_start

        # Get words for this segment from the original transcript
        seg_words = get_words_for_clip(transcript, seg_start, seg_end)

        # Remap timestamps relative to this segment's position in the output file
        for w in seg_words:
            remapped = {
                "word":  w["word"],
                "start": round(output_time_offset + w["start"], 3),
                "end":   round(output_time_offset + w["end"], 3),
            }
            all_words.append(remapped)

        output_time_offset += seg_duration

    return all_words


def cap_word_durations(words: list) -> list:
    """Cap abnormally long word durations caused by silence gaps."""
    for w in words:
        if w["end"] - w["start"] > MAX_WORD_DURATION:
            w["end"] = w["start"] + MAX_WORD_DURATION
    return words


def group_words_into_lines(words: list, words_per_line: int = MAX_WORDS_PER_LINE) -> list:
    """
    Group words into lines of `words_per_line` (default MAX_WORDS_PER_LINE).
    Each line dict carries its full word list for karaoke event generation.
    """
    lines = []
    for i in range(0, len(words), words_per_line):
        chunk = words[i : i + words_per_line]
        if not chunk:
            continue
        line_start = chunk[0]["start"]
        line_end   = chunk[-1]["end"]
        if line_end - line_start > MAX_LINE_DURATION:
            line_end = line_start + MAX_LINE_DURATION
        lines.append({
            "words":      chunk,
            "line_start": line_start,
            "line_end":   line_end,
        })

    # Fix overlaps between consecutive lines
    for i in range(len(lines) - 1):
        if lines[i]["line_end"] > lines[i + 1]["line_start"]:
            lines[i]["line_end"] = lines[i + 1]["line_start"] - 0.05

    return lines


# ══════════════════════════════════════════════════════════════════════════════
# ASS generation — karaoke word highlight
# ══════════════════════════════════════════════════════════════════════════════

def format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp: H:MM:SS.cc"""
    seconds = max(0.0, seconds)
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _pill_to_ass_back_color(pill: dict) -> str:
    """Convert an editor caption-pill spec to an ASS &HAABBGGRR BackColour.

    Editor pill:
      color    — '#rrggbb' hex from the color picker
      opacity  — 0.0 (transparent) → 1.0 (opaque)
    ASS BackColour is &HAABBGGRR where:
      AA — 00 (opaque) → FF (transparent)  ← INVERSE of opacity
      BB, GG, RR — 8-bit channels in swapped order
    Returns a safe default when the pill dict is malformed (falls back to
    the same near-opaque black the `hormozi` preset uses).
    """
    hex_rgb = str(pill.get("color", "#000000") or "#000000").lstrip("#")
    if len(hex_rgb) != 6 or any(c not in "0123456789abcdefABCDEF" for c in hex_rgb):
        hex_rgb = "000000"
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    try:
        opacity = float(pill.get("opacity", 1.0))
    except (TypeError, ValueError):
        opacity = 1.0
    opacity = max(0.0, min(1.0, opacity))
    # opacity 0.0 → alpha FF (fully transparent); 1.0 → alpha 00 (opaque)
    alpha_byte = int(round((1.0 - opacity) * 255))
    return f"&H{alpha_byte:02X}{b.upper()}{g.upper()}{r.upper()}"



def _escape_ass_text(text: str) -> str:
    """Escape ASS control characters in transcript word text (BUG-008 fix).

    Words are concatenated straight into a Dialogue line after our {\\1c...}
    override block, so a literal `{` in the transcript opens a new override
    tag, `}` closes one, and `\\` begins an escape sequence — all silently
    corrupt the line (garbled formatting, dropped/blank words). Newlines
    terminate the ASS event line entirely, cutting the caption off mid-word.

    Called ONCE per word BEFORE we wrap it in {\\1c...} override tags, so the
    tags we emit ourselves stay intact — only user/transcript text is escaped.

    ASS rules used here:
      - `\\`   → `\\\\` (literal backslash outside an override block)
      - `{`    → `\\{`  (libass treats `\\{` as a literal `{`)
      - `}`    → `\\}`
      - CR/LF  → `\\N`  (hard line break within the same event)
    """
    if not text:
        return ""
    return (text
            .replace("\\", "\\\\")
            .replace("{",  "\\{")
            .replace("}",  "\\}")
            .replace("\r\n", "\\N")
            .replace("\n",   "\\N")
            .replace("\r",   "\\N"))



def _color_tag(assc: str) -> str:
    """ASS override setting BOTH primary colour and primary alpha from an
    &HAABBGGRR value.

    `\\c` alone sets only the RGB, leaving alpha at the Style's PrimaryColour
    alpha. That silently broke the `typewriter` preset: its `color_unspoken` is
    &HFFFFFFFF (alpha FF = transparent) and becomes the Style PrimaryColour, so
    the spoken/highlight words — coloured with `\\c` only — inherited that FF
    alpha and rendered fully transparent (invisible text on the box). Emitting
    `\\1a` with the colour's OWN alpha byte fixes typewriter (spoken/highlight
    become opaque; unspoken stays transparent for the type-on effect) and is a
    no-op for every other preset, whose colours are already opaque (alpha 00)."""
    if assc.upper().startswith("&H") and len(assc) >= 10:
        return f"\\1c&H{assc[4:10]}&\\1a&H{assc[2:4]}&"
    return f"\\c{assc}"


def generate_ass_karaoke(lines: list, style_name: str = DEFAULT_STYLE,
                         caption_position: float = 84.0,
                         video_width: int = 1080, video_height: int = 1920,
                         caption_font: str = None,
                         caption_x: float = None, caption_y: float = None,
                         caption_font_size_frac: float = None,
                         caption_pill: dict = None) -> str:
    """
    Generate ASS with per-word color highlight animation.
    style_name must be one of: bold-yellow, white-minimal, red-pop, clean-dark,
    hormozi, fire-gradient, neon-green, outline-only, big-bold, typewriter, split-color

    caption_font selects the bundled Telugu caption font (Noto Sans Telugu default,
    Ramabhadra/Mandali selectable). It is resolved to a bundled file by libass via
    the `ass` filter's fontsdir (see burn_captions) — it is NOT the per-style
    font_name, which is no longer used for the caption font (Stage 5 decoupled the
    font from the preset; font_name in STYLES is now dead — see KNOWN_ISSUES.md).

    caption_x/caption_y (0-1 CENTER fractions of the video frame). BOTH provided →
    caption centers at (caption_x*W, caption_y*H) via {\\an5\\pos(cx,cy)}. Either
    missing → default (Commit 4) — the position falls back to
    (CAPTION_DEFAULT_X_FRAC, CAPTION_DEFAULT_Y_FRAC), which matches the frontend
    editor's untouched-caption default. Every karaoke event carries an explicit
    {\\an5\\pos(cx,cy)} prefix in every case, so preview and export share ONE
    positioning code path (drift-free WYSIWYG regardless of drag / line count /
    aspect ratio). PlayResX/Y equal video_width/height so \\pos lands at literal
    output pixels; the caller (worker) is responsible for passing the real render
    dimensions on non-9:16 formats.

    caption_font_size_frac (BUG-001 partial fix): the editor's caption Size — a
    0-1 fraction of video HEIGHT, matching the preview's `elHeight = canvasH *
    fontSize` math (see frontend/src/components/editor/ElementBodies.jsx). When
    provided, the resulting pixel size is used AS-IS (already sized for the
    output canvas; the calibrated k-values in caption_font_size(...) exist to
    match the preset defaults to Noto's cap-height and should NOT compound
    with a user-provided absolute size — the preview does not apply them
    either). When None, we keep the previous behaviour: preset default × the
    calibrated per-font k.

    caption_pill (BUG-001 partial fix): {enabled, color '#rrggbb', opacity 0-1,
    padding, radius}. When enabled, overrides the preset's back_color +
    border_style + outline (padding + radius aren't representable in ASS
    without libass patches, so we ignore them for now — see KNOWN_ISSUES).
    When None or enabled=False, the preset's own back_color renders exactly
    as before this argument existed.

    caption_position is now dead for placement (kept in the signature for
    backwards compat; a future cleanup can remove it — see KNOWN_ISSUES).
    """
    # Lazy import (module also runs as a CLI script; matches this file's pattern).
    from services.fonts import get_caption_font
    from services.canvas_coords import to_pixel_center
    if style_name not in STYLES:
        print(f"✗ WARN: unknown caption style '{style_name}' — falling back to bold-yellow")
        style_name = DEFAULT_STYLE
    s = STYLES[style_name]

    font_family, _ = get_caption_font(caption_font)          # deterministic family name
    # BUG-001 partial: user-set Size (0-1 fraction of video HEIGHT) → absolute
    # pixel size. Falls back to the calibrated preset default when omitted.
    if caption_font_size_frac is not None and caption_font_size_frac > 0:
        font_size = max(round(float(caption_font_size_frac) * int(video_height)), 8)
    else:
        font_size = caption_font_size(s['font_size'], font_family)  # cap-height-calibrated

    # BUG-001 partial: caption background pill — when enabled, override the
    # preset's back_color/border_style/outline. The pill's `color` is a plain
    # `#rrggbb` from the color picker; ASS BackColour wants &HAABBGGRR (alpha
    # is INVERSE opacity in ASS: 00=opaque, FF=transparent), so build it here.
    style_back_color   = s['back_color']
    style_border_style = s['border_style']
    style_outline      = s['outline_width']
    if isinstance(caption_pill, dict) and caption_pill.get("enabled"):
        style_back_color   = _pill_to_ass_back_color(caption_pill)
        style_border_style = 4          # box (opaque background) around text
        style_outline      = 0          # no stroke on top of the box

    # Commit 4: unified default anchor. Untouched captions (either coord missing)
    # fall back to the frontend's default center, so the export burns exactly
    # where the preview drew — no bottom-anchored / center-anchored dual path.
    eff_x = CAPTION_DEFAULT_X_FRAC if caption_x is None else float(caption_x)
    eff_y = CAPTION_DEFAULT_Y_FRAC if caption_y is None else float(caption_y)
    c = to_pixel_center(eff_x, eff_y, video_width, video_height)
    pos_override = f"{{\\an5\\pos({c.cx},{c.cy})}}"

    # MarginV is now cosmetic — \an5\pos overrides Alignment/MarginV on every
    # event — but a sensible default keeps the Style block valid and readable.
    margin_v = 20

    header = f"""[Script Info]
Title: ClipForge Captions
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_family},{font_size},{s['color_unspoken']},&H000000FF,{s['outline_color']},{style_back_color},{s['bold']},0,0,0,100,100,0,0,{style_border_style},{style_outline},{s['shadow']},5,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    for line in lines:
        words      = line["words"]
        line_start = line["line_start"]
        line_end   = line["line_end"]

        for idx, word in enumerate(words):
            evt_start = max(word["start"], line_start)
            if idx + 1 < len(words):
                evt_end = words[idx + 1]["start"]
            else:
                evt_end = line_end

            evt_end = min(evt_end, line_end)
            if evt_end <= evt_start:
                evt_end = evt_start + 0.05

            # Build colored line — every word runs through _escape_ass_text
            # BEFORE being wrapped in the {\1c...} override tag so ASS control
            # characters in transcript text ({, }, \, newline) don't break out
            # of the run, corrupt override syntax, or drop text (BUG-008).
            parts = []
            for j, w in enumerate(words):
                safe_word = _escape_ass_text(w['word'])
                if j < idx:
                    parts.append(f"{{{_color_tag(s['color_spoken'])}}}{safe_word}")
                elif j == idx:
                    parts.append(f"{{{_color_tag(s['color_highlight'])}}}{safe_word}")
                else:
                    parts.append(f"{{{_color_tag(s['color_unspoken'])}}}{safe_word}")

            line_text = pos_override + " ".join(parts)
            events.append(
                f"Dialogue: 0,{format_ass_time(evt_start)},{format_ass_time(evt_end)},"
                f"Default,,0,0,0,,{line_text}"
            )

    return header + "\n".join(events) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# Filename sanitization
# ══════════════════════════════════════════════════════════════════════════════

def sanitize_filename(name: str) -> str:
    """Remove characters that break FFmpeg filter args on Windows."""
    name = re.sub(r"['\"\[\]{}()|&;!]", "", name)
    name = name.replace(" ", "_")
    return name


def safe_ass_path(vertical_clip_path: str, style_name: str = DEFAULT_STYLE) -> str:
    """Derive a clean .ass path from any video input path, including style suffix."""
    dir_part = os.path.dirname(vertical_clip_path)
    stem     = os.path.splitext(os.path.basename(vertical_clip_path))[0]
    return os.path.join(dir_part, sanitize_filename(f"{stem}_{style_name}_captions.ass")).replace("\\", "/")


def safe_output_path(vertical_clip_path: str, output_dir: str, style_name: str = DEFAULT_STYLE) -> str:
    """Derive a clean output path for the captioned clip, including style suffix."""
    stem = os.path.splitext(os.path.basename(vertical_clip_path))[0]
    return os.path.join(output_dir, sanitize_filename(f"{stem}_{style_name}_captioned.mp4")).replace("\\", "/")


# ══════════════════════════════════════════════════════════════════════════════
# FFmpeg burn
# ══════════════════════════════════════════════════════════════════════════════

def burn_captions(video_path: str, ass_path: str, output_path: str) -> bool:
    """Burn ASS subtitles onto video using FFmpeg.

    ENGINE RULE — the `ass` filter is the ONLY permitted subtitle filter here.
    Do NOT switch to `subtitles=`: empirically, on the production libass build
    the `subtitles` filter mis-shapes Telugu below-base (vattu/ottu) conjuncts
    (e.g. ప్ర decomposes) while `ass` shapes them correctly. This is guarded by
    tests/test_caption_shaping.py. `fontsdir` points libass at the bundled
    caption fonts (services/fonts.CAPTION_FONTS_DIR) so font resolution is
    deterministic and never depends on host fontconfig.
    """
    from services.fonts import CAPTION_FONTS_DIR
    ass_filter = ass_path.replace("\\", "/")
    ass_filter = re.sub(r"^([A-Za-z]):/", r"\1\\:/", ass_filter)
    fonts_dir = CAPTION_FONTS_DIR.replace("\\", "/")
    fonts_dir = re.sub(r"^([A-Za-z]):/", r"\1\\:/", fonts_dir)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"ass='{ass_filter}':fontsdir='{fonts_dir}'",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-crf", "23",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
        if result.returncode != 0:
            print(f"  ✗ FFmpeg error: {result.stderr[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  ✗ FFmpeg timed out")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Main render functions
# ══════════════════════════════════════════════════════════════════════════════

def render_captions_for_clip(
    transcript_path: str,
    clips_path: str,
    clip_index: int,
    vertical_clip_path: str,
    output_dir: str,
    style_name: str = DEFAULT_STYLE,
    transcript_edits: dict = None,
    caption_position: float = 84.0,
    video_width: int = 1080,
    video_height: int = 1920,
    caption_font: str = None,
    caption_x: float = None,
    caption_y: float = None,
    caption_font_size: float = None,   # BUG-001 partial: 0-1 fraction of video height
    caption_pill: dict = None,         # BUG-001 partial: {enabled, color, opacity, padding, radius}
) -> str:
    """words → ASS → burn for a single clip with given style + caption font.

    caption_x/caption_y (0-1 center) position the caption per the user's drag
    (Stage 6). Both None → unpositioned, byte-identical to the pre-Stage-6 path;
    for correct \\pos on non-9:16, callers pass the real output video_width/
    video_height alongside them (the worker does this only in the positioned case)."""

    from services.fonts import CAPTION_FONTS, DEFAULT_CAPTION_FONT
    if style_name not in STYLES:
        print(f"✗ WARN: unknown caption style '{style_name}' — falling back to bold-yellow")
        style_name = DEFAULT_STYLE
    if caption_font is not None and caption_font not in CAPTION_FONTS:
        print(f"✗ WARN: unknown caption font '{caption_font}' — falling back to {DEFAULT_CAPTION_FONT}")
        caption_font = None
    wpl = STYLES[style_name].get("words_per_line", MAX_WORDS_PER_LINE)

    transcript = load_transcript(transcript_path)
    clips      = load_clips(clips_path)
    clip       = clips["clips"][clip_index]
    sentences  = transcript.get("sentences", [])
    sent_by_id = {s["id"]: s for s in sentences}

    print(f"📝 Generating captions [{style_name} / {caption_font or DEFAULT_CAPTION_FONT}] "
          f"for: {clip.get('why', clip.get('hook_text', 'clip'))}")

    segments = clip.get("segments", [])

    # ── Apply transcript edits ────────────────────────────────────────────────
    if transcript_edits:
        _n_word  = len(transcript_edits.get("wordEdits",    []))
        _n_merge = len(transcript_edits.get("mergedGroups", []))
        _n_split = len(transcript_edits.get("lineSplits",   []))
        if len(segments) > 1:
            # wordEdits use global refs — safe to apply before segment carving.
            if _n_word:
                from services.apply_transcript_edits import apply_transcript_edits
                _word_only = {
                    'wordEdits':    transcript_edits.get('wordEdits', []),
                    'mergedGroups': [],
                    'lineSplits':   [],
                }
                transcript, n_applied = apply_transcript_edits(
                    transcript, _word_only, clip["start"], clip["end"]
                )
                if n_applied < _n_word:
                    print(f"  ✗ WARN: only {n_applied}/{_n_word} word edit(s) applied — "
                          f"{_n_word - n_applied} skipped (see refs above)", flush=True)
                else:
                    print(f"  ✎ multi-segment clip {clip_index}: {n_applied} word edit(s) applied",
                          flush=True)
            if _n_merge or _n_split:
                print(f"  ⚠ multi-segment clip {clip_index}: "
                      f"{_n_merge} merge(s), {_n_split} split(s) skipped — "
                      f"frontend line indices include gap words; backend does not (not yet remapped)",
                      flush=True)
            transcript_edits = None  # prevent lineSplits grouper below from misapplying
        else:
            from services.apply_transcript_edits import apply_transcript_edits
            transcript, n_applied = apply_transcript_edits(
                transcript, transcript_edits, clip["start"], clip["end"]
            )
            if n_applied < _n_word:
                print(f"  ✗ WARN: only {n_applied}/{_n_word} word edit(s) applied — "
                      f"{_n_word - n_applied} skipped (see refs above)", flush=True)
            else:
                print(f"  ✎ Applied transcript edits: {n_applied}/{_n_word} word edit(s), "
                      f"{_n_merge} merge(s), {_n_split} split(s)", flush=True)

    if len(segments) > 1:
        print(f"   Multi-segment clip: {len(segments)} parts")
        for i, seg in enumerate(segments):
            s_start = sent_by_id.get(int(seg['start_sent_id']), {}).get('start', 0)
            s_end   = sent_by_id.get(int(seg['end_sent_id']),   {}).get('end',   0)
            print(f"   Part {i+1}: {s_start:.1f}s → {s_end:.1f}s (output: remapped)")
        words = get_words_for_multisegment_clip(transcript, clip, sent_by_id)
    else:
        print(f"   Clip time: {clip['start']:.1f}s → {clip['end']:.1f}s")
        words = get_words_for_clip(transcript, clip["start"], clip["end"])

    print(f"   Found {len(words)} words")

    if not words:
        print("   ⚠ No words found — skipping captions for this clip")
        return None

    # Load xfade segment sidecar and remap word timestamps onto output timeline.
    # Without this, captions drift progressively later when xfade overlap removes
    # (n-1) * xfade_duration seconds from the total clip length.
    # Sidecar files only exist for initial-pipeline _vertical.mp4 clips; canvas/rerender
    # inputs never have one, so skip the lookup when the path doesn't contain _vertical.mp4.
    _sidecar = None
    _sidecar_path = (
        vertical_clip_path.replace("_vertical.mp4", "_vertical_segments.json", 1)
        if "_vertical.mp4" in vertical_clip_path
        else None
    )
    if _sidecar_path and os.path.exists(_sidecar_path):
        try:
            with open(_sidecar_path, "r", encoding="utf-8", errors="replace") as _sf:
                _sidecar = json.load(_sf)
            print(f"   ↕ Remapping timestamps via segment sidecar ({len(_sidecar['segments'])} segments)")
        except Exception as _e:
            print(f"   ⚠ Could not load segment sidecar: {_e}")

    def remap_time(t):
        if _sidecar is None:
            return t
        segs = _sidecar["segments"]
        for seg in segs:
            if seg["input_start"] <= t < seg["input_end"]:
                return seg["output_start"] + (t - seg["input_start"])
        if t < segs[0]["input_start"]:
            return 0.0
        return _sidecar["total_output_duration"]

    if _sidecar is not None:
        for w in words:
            w["start"] = round(remap_time(w["start"]), 3)
            w["end"]   = round(remap_time(w["end"]),   3)

    words = cap_word_durations(words)

    # Use split-aware grouper when the user set forced line-break positions
    _line_splits = set(transcript_edits.get("lineSplits", [])) if transcript_edits else set()
    if _line_splits:
        from services.apply_transcript_edits import group_words_with_splits
        lines = group_words_with_splits(words, wpl, _line_splits)
    else:
        lines = group_words_into_lines(words, wpl)

    print(f"   {len(lines)} lines × up to {wpl} words — karaoke highlight mode")

    ass_path    = safe_ass_path(vertical_clip_path, style_name)
    output_path = safe_output_path(vertical_clip_path, output_dir, style_name)

    # Hard guards — catch path derivation bugs before any file is touched.
    if not ass_path.endswith(".ass"):
        raise RuntimeError(
            f"[Path guard] ass_path must end with .ass — got {ass_path!r} "
            f"(derived from vertical_clip_path={vertical_clip_path!r})"
        )
    if ass_path == vertical_clip_path:
        raise RuntimeError(
            f"[Path guard] ass_path equals the video input — would overwrite source: {ass_path!r}"
        )
    if ass_path == output_path:
        raise RuntimeError(
            f"[Path guard] ass_path equals output_path: {ass_path!r}"
        )

    ass_content = generate_ass_karaoke(lines, style_name,
                                       caption_position=caption_position,
                                       video_width=video_width,
                                       video_height=video_height,
                                       caption_font=caption_font,
                                       caption_x=caption_x,
                                       caption_y=caption_y,
                                       caption_font_size_frac=caption_font_size,
                                       caption_pill=caption_pill)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
    print(f"   ✓ ASS: {ass_path}")

    print(f"   🔥 Burning captions [{style_name}]...")
    success = burn_captions(vertical_clip_path, ass_path, output_path)

    if success:
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"   ✓ Saved: {output_path} ({size_mb:.1f} MB)")
        return output_path
    else:
        print(f"   ✗ Failed to burn captions")
        return None


def render_all_captions(
    transcript_path: str,
    clips_path: str,
    clips_dir: str,
    output_dir: str = None,
    style_name: str = DEFAULT_STYLE,
) -> list:
    """Render captions for all vertical clips in clips_dir with given style."""

    if output_dir is None:
        output_dir = clips_dir

    clips = load_clips(clips_path)

    # clips_dir can hold clips from multiple videos at once — scope to this
    # video only, derived from clips_path's naming convention ({video_id}_audio_clips.json)
    video_id = os.path.basename(clips_path).replace("_audio_clips.json", "")

    vertical_files = sorted([
        f for f in os.listdir(clips_dir)
        if f.endswith("_vertical.mp4") and f.startswith(video_id)
    ])

    if not vertical_files:
        print("✗ No vertical clips found in", clips_dir)
        return []

    if len(vertical_files) != len(clips["clips"]):
        print(f"⚠ {len(vertical_files)} vertical clips vs {len(clips['clips'])} in JSON "
              f"— some clip(s) likely failed cropping; pairing by clip number, not list position")

    print(f"✓ Found {len(vertical_files)} vertical clips\n")

    # Pair each file with its clip by the {N} parsed from the filename
    # (clip{N}_...) — NOT by position in this sorted list. If any clip's
    # vertical file is missing (failed crop, etc.), positional pairing would
    # silently shift every subsequent clip's captions onto the wrong video.
    clip_num_re = re.compile(rf"^{re.escape(video_id)}_clip(\d+)_")

    results = []
    for vfile in vertical_files:
        match = clip_num_re.match(vfile)
        if not match:
            print(f"  ⚠ Could not parse clip number from '{vfile}' — skipping")
            continue
        clip_index = int(match.group(1)) - 1
        if clip_index < 0 or clip_index >= len(clips["clips"]):
            print(f"  ⚠ Clip number {clip_index + 1} out of range for '{vfile}' — skipping")
            continue

        vpath = os.path.join(clips_dir, vfile).replace("\\", "/")
        result = render_captions_for_clip(
            transcript_path, clips_path, clip_index, vpath, output_dir, style_name
        )
        if result:
            results.append(result)
        print()

    print(f"{'='*60}")
    print(f"✓ Captioned {len(results)}/{len(vertical_files)} clips [{style_name}]")
    return results


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python services/caption_renderer.py <transcript_json> <clips_json> [clips_dir] [style]")
        print(f"Styles: {', '.join(STYLES.keys())}")
        sys.exit(1)

    style = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_STYLE
    results = render_all_captions(
        sys.argv[1], sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else "storage/outputs",
        style_name=style,
    )
    print(f"\n{'🎉 Done!' if results else '✗ Failed.'} {len(results)} captioned clips ready.")