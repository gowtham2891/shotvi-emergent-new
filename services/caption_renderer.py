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
    # ── Feature #16 (research-grounded): 10 new presets = Replix's 9 named
    # styles + the market "Hormozi formula". Each carries extra keys the newer
    # renderer reads: `uppercase` (Tanglish-only ALL-CAPS), `glow` (neon halo
    # on the active word), `spacing` (ASS letter-spacing), `bg_off` (text-only,
    # animation-eligible — mirrors Replix's "animation only on bg-off styles"),
    # and `latin_font` (the recommended Tanglish font; Telugu mode keeps the
    # user's Telugu pick). Colours are &H00BBGGRR. font_name stays dead (Stage
    # 5) — the family is resolved from caption_font by script at render time.
    "classic": {  # Replix Classic — white pill, current word black, upcoming grey
        "font_name": "Poppins", "latin_font": "Poppins", "font_size": 56, "bold": -1,
        "color_highlight": "&H00000000", "color_spoken": "&H00000000",
        "color_unspoken": "&H00888888", "outline_color": "&H00FFFFFF",
        "back_color": "&H00FFFFFF", "outline_width": 0, "shadow": 0, "border_style": 4,
        "uppercase": False, "glow": False, "spacing": 0, "bg_off": False,
    },
    "yellow": {  # Replix Yellow — bg-off, active word yellow, animatable
        "font_name": "Poppins", "latin_font": "Poppins", "font_size": 60, "bold": -1,
        "color_highlight": "&H0000FFFF", "color_spoken": "&H00AAAAAA",
        "color_unspoken": "&H00FFFFFF", "outline_color": "&H00000000",
        "back_color": "&H00000000", "outline_width": 3, "shadow": 0, "border_style": 1,
        "uppercase": False, "glow": False, "spacing": 0, "bg_off": True,
    },
    "minimal": {  # Replix Minimal — bg-off, subtle, thin
        "font_name": "Poppins", "latin_font": "Inter", "font_size": 54, "bold": 0,
        "color_highlight": "&H00FFFFFF", "color_spoken": "&H00CCCCCC",
        "color_unspoken": "&H00AAAAAA", "outline_color": "&H00000000",
        "back_color": "&H00000000", "outline_width": 2, "shadow": 1, "border_style": 1,
        "uppercase": False, "glow": False, "spacing": 0, "bg_off": True,
    },
    "dark": {  # Replix Dark — dark solid box, yellow accent
        "font_name": "Poppins", "latin_font": "Montserrat", "font_size": 56, "bold": -1,
        "color_highlight": "&H0000FFFF", "color_spoken": "&H00AAAAAA",
        "color_unspoken": "&H00FFFFFF", "outline_color": "&H00000000",
        "back_color": "&HDD000000", "outline_width": 0, "shadow": 0, "border_style": 4,
        "uppercase": False, "glow": False, "spacing": 0, "bg_off": False,
    },
    "punch": {  # loud ALL-CAPS, hot-pink pop, near-opaque box
        "font_name": "Anton", "latin_font": "Anton", "font_size": 66, "bold": -1,
        "color_highlight": "&H009348EC", "color_spoken": "&H00888888",
        "color_unspoken": "&H00FFFFFF", "outline_color": "&H00000000",
        "back_color": "&HCC000000", "outline_width": 0, "shadow": 0, "border_style": 4,
        "uppercase": True, "glow": False, "spacing": 0, "bg_off": False,
    },
    "cove": {  # editorial, rounded dark box, soft cyan accent, mixed case
        "font_name": "Poppins", "latin_font": "Poppins", "font_size": 54, "bold": 0,
        "color_highlight": "&H00E0D040", "color_spoken": "&H00999999",
        "color_unspoken": "&H00FFFFFF", "outline_color": "&H00000000",
        "back_color": "&HCC201810", "outline_width": 0, "shadow": 0, "border_style": 4,
        "uppercase": False, "glow": False, "spacing": 0, "bg_off": False,
    },
    "spotlight": {  # GLOW / neon halo on the active word, bg-off (Replix paid)
        "font_name": "Montserrat", "latin_font": "Montserrat", "font_size": 62, "bold": -1,
        "color_highlight": "&H0000FFFF", "color_spoken": "&H00999999",
        "color_unspoken": "&H00FFFFFF", "outline_color": "&H00000000",
        "back_color": "&H00000000", "outline_width": 2, "shadow": 0, "border_style": 1,
        "uppercase": False, "glow": True, "spacing": 0, "bg_off": True,
    },
    "reel": {  # bold caps, thick black outline, yellow keyword, bg-off
        "font_name": "Bebas Neue", "latin_font": "Bebas Neue", "font_size": 68, "bold": -1,
        "color_highlight": "&H0000FFFF", "color_spoken": "&H00AAAAAA",
        "color_unspoken": "&H00FFFFFF", "outline_color": "&H00000000",
        "back_color": "&H00000000", "outline_width": 4, "shadow": 0, "border_style": 1,
        "uppercase": True, "glow": False, "spacing": 0, "bg_off": True,
    },
    "noir": {  # moody, heavy outline, grey/white, no box
        "font_name": "Oswald", "latin_font": "Oswald", "font_size": 60, "bold": -1,
        "color_highlight": "&H00FFFFFF", "color_spoken": "&H00888888",
        "color_unspoken": "&H00CCCCCC", "outline_color": "&H00000000",
        "back_color": "&H00000000", "outline_width": 5, "shadow": 1, "border_style": 1,
        "uppercase": True, "glow": False, "spacing": 0, "bg_off": True,
    },
    "hormozi-caps": {  # market formula: white ALL-CAPS, thick outline, yellow keyword, shadow
        "font_name": "Montserrat", "latin_font": "Montserrat", "font_size": 66, "bold": -1,
        "color_highlight": "&H0000FFFF", "color_spoken": "&H00FFFFFF",
        "color_unspoken": "&H00FFFFFF", "outline_color": "&H00000000",
        "back_color": "&H00000000", "outline_width": 5, "shadow": 2, "border_style": 1,
        "uppercase": True, "glow": False, "spacing": 0, "bg_off": True,
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
    # Feature #16 Latin caption fonts (Tanglish). Measured the SAME way (an "H"
    # rendered at Fontsize 100 through the `ass` filter, cap-height in px ÷ 100)
    # — so a Tanglish caption renders at the SAME Latin cap-height as a Telugu
    # one at the preset's nominal size. These display fonts have shorter total
    # metrics than Noto, so most scale slightly UP (k below the anchor) rather
    # than down; that's expected, not a bug.
    "Montserrat": 0.450,
    "Anton":      0.490,
    "Bebas Neue": 0.540,
    "Oswald":     0.480,
    "Poppins":    0.390,
    "Inter":      0.500,
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

def _word_text_for_script(word: dict, script: str) -> str:
    """Display text of a transcript word in the requested caption script.

    'tanglish' → the stored word_tanglish; when an old transcript has none,
    derive it on demand (deterministic services/tanglish.py — same function
    that populates it everywhere else, so on-demand == stored). Timestamps
    are untouched either way; this is a display-text switch only.
    """
    if script == "tanglish":
        stored = word.get("word_tanglish")
        if isinstance(stored, str) and stored.strip():
            return stored
        from services.tanglish import telugu_to_tanglish
        return telugu_to_tanglish(word["word"])
    return word["word"]


def get_words_for_clip(transcript: dict, clip_start: float, clip_end: float,
                       script: str = "telugu", time_zero: float = None) -> list:
    """
    Extract words that fall within a clip time range.
    Handles both Sarvam V3 and faster-whisper transcript formats.
    script selects the caption text ('telugu' renders word, 'tanglish' renders
    word_tanglish) — timing/windowing is identical in both.

    time_zero (caption-sync fix): the absolute timestamp that is t=0 of the CUT
    output file — the energy-refined start the cutter actually used, which can
    differ from clip_start (raw CTC) by up to ~0.5s. Word SELECTION still
    windows on [clip_start, clip_end] (the filtered word array is the index
    space for lineSplits/wordEdits — it must not change), but timestamps are
    shifted relative to time_zero. None → clip_start (pre-fix behavior for old
    clips JSONs that carry no refined boundaries).
    """
    if time_zero is None:
        time_zero = clip_start
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
            adj_start = max(0.0, max(w_start, clip_start) - time_zero)
            adj_end   = max(0.0, min(w_end,   clip_end)   - time_zero)
            # Empty-text drop stays keyed on the TELUGU source in both scripts,
            # so the word list (and every raw index / lineSplit address built on
            # it) is identical whichever script renders.
            text = word["word"].strip()
            if text:
                words.append({
                    "word":  _word_text_for_script(word, script).strip() or text,
                    "start": round(adj_start, 3),
                    "end":   round(adj_end,   3),
                })
    return words


def get_words_for_multisegment_clip(transcript: dict, clip: dict, sent_by_id: dict,
                                     script: str = "telugu") -> list:
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
        return get_words_for_clip(transcript, clip["start"], clip["end"], script,
                                  time_zero=clip.get("refined_start"))

    # Caption-sync fix: the cutter refines each segment's boundaries before
    # concatenating, so the stitched file's segments start at refined_start
    # and last (refined_end - refined_start) — use those when available.
    refined = clip.get("refined_segments") or []
    if len(refined) != len(segments):
        refined = None

    all_words = []
    output_time_offset = 0.0

    for seg_i, seg in enumerate(segments):
        s_id = int(seg["start_sent_id"])
        e_id = int(seg["end_sent_id"])

        seg_start = sent_by_id[s_id]["start"]
        seg_end   = sent_by_id[e_id]["end"]
        if refined:
            seg_time_zero = refined[seg_i]["start"]
            seg_duration  = refined[seg_i]["end"] - refined[seg_i]["start"]
        else:
            seg_time_zero = None
            seg_duration  = seg_end - seg_start

        # Get words for this segment from the original transcript
        seg_words = get_words_for_clip(transcript, seg_start, seg_end, script,
                                       time_zero=seg_time_zero)

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


def _pill_padding_px(pill: dict, video_height: int) -> int:
    """Editor pill padding → BorderStyle-4 box padding in output px.

    Feature #4: the wire value is a FRACTION of canvas height (the same unit
    caption_font_size uses), so preview pill and burned box pad proportionally
    on every aspect. Legacy payloads (drafts saved before this) carried
    absolute CSS px designed against the 640px-tall 9:16 stage — anything > 1
    is unambiguously that, so it converts once (mirrors frontend
    lib/pillUnits.js::normalizePillScalar — keep in lockstep).
    """
    try:
        raw = float(pill.get("padding", 0) or 0)
    except (TypeError, ValueError):
        return 0
    if raw <= 0:
        return 0
    frac = raw / 640.0 if raw > 1 else raw
    frac = min(frac, 0.10)  # safety: never pad more than 10% of frame height
    return int(round(frac * int(video_height)))


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
                         caption_pill: dict = None,
                         animation: str = "karaoke",
                         caption_script: str = "telugu") -> str:
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

    caption_pill (BUG-001 partial fix + feature #4): {enabled, color '#rrggbb',
    opacity 0-1, padding, radius}. When enabled, overrides the preset's
    back_color + border_style + outline. padding is a FRACTION of canvas
    height (legacy absolute-px payloads >1 are converted — see
    _pill_padding_px) and reaches the burn as the BorderStyle-4 box's Outline
    padding; radius is still not representable in ASS without libass patches
    and stays ignored (KNOWN_ISSUES). When None or enabled=False, the
    preset's own back_color renders exactly as before this argument existed.

    caption_position is now dead for placement (kept in the signature for
    backwards compat; a future cleanup can remove it — see KNOWN_ISSUES).
    """
    # Lazy import (module also runs as a CLI script; matches this file's pattern).
    from services.fonts import resolve_caption_font, is_latin_caption_font
    from services.canvas_coords import to_pixel_center
    if style_name not in STYLES:
        print(f"✗ WARN: unknown caption style '{style_name}' — falling back to bold-yellow")
        style_name = DEFAULT_STYLE
    s = STYLES[style_name]

    # Script-aware font: Telugu script → a Telugu font; Tanglish → a Latin font
    # (feature #16). The resolver enforces the rule and defaults per script.
    font_family, _ = resolve_caption_font(caption_font, caption_script)
    _is_latin = is_latin_caption_font(font_family)
    # The bundled Latin fonts are already black/heavy (weight baked into the
    # outlines) — faux-bolding on top blurs them, so force Bold OFF for Latin.
    # Telugu fonts are Regular instances that DO rely on the preset's bold flag.
    style_bold = 0 if _is_latin else s['bold']
    # Feature #16 — ALL-CAPS presets uppercase the caption text, but only in
    # Tanglish (Latin) mode; Telugu script has no case, and .upper() there is a
    # harmless no-op we skip to keep the Telugu burn byte-identical.
    _uppercase = bool(s.get("uppercase")) and caption_script == "tanglish"

    def _disp(txt):
        return txt.upper() if _uppercase else txt

    # Feature #16 — GLOW / spotlight: the active (or emphasized) word gets a
    # neon halo (border in its own colour, blurred); ASS override tags persist
    # within an event, so glow presets must RESET \bord/\blur/\3c on every
    # other word or the halo bleeds onto the rest of the line. Non-glow presets
    # emit neither tag → byte-identical to before this existed.
    _glow = bool(s.get("glow"))

    def _rgb(assc):
        return assc[4:10] if (assc.upper().startswith("&H") and len(assc) >= 10) else "FFFFFF"

    _base_bord = int(s.get("outline_width", 3))
    _oc_rgb = _rgb(s.get("outline_color", "&H00000000"))

    def _glow_on(color_hex):
        # Tasteful neon halo: a modest coloured border, lightly blurred, so the
        # letterforms stay crisp on top of the glow (too much blur buries them).
        return f"\\3c&H{_rgb(color_hex)}&\\bord{max(_base_bord, 3)}\\blur3"

    def _glow_off():
        return f"\\3c&H{_oc_rgb}&\\bord{_base_bord}\\blur0"
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
        # Feature #4: with BorderStyle=4 libass pads the box by Outline, so
        # the editor's pill padding (fraction of canvas height, same unit as
        # the text Size) reaches the burn. Radius remains unrepresentable in
        # ASS (KNOWN_ISSUES) — carried but ignored here.
        style_outline      = _pill_padding_px(caption_pill, video_height)

    # Commit 4: unified default anchor. Untouched captions (either coord missing)
    # fall back to the frontend's default center, so the export burns exactly
    # where the preview drew — no bottom-anchored / center-anchored dual path.
    eff_x = CAPTION_DEFAULT_X_FRAC if caption_x is None else float(caption_x)
    eff_y = CAPTION_DEFAULT_Y_FRAC if caption_y is None else float(caption_y)
    c = to_pixel_center(eff_x, eff_y, video_width, video_height)
    pos_override = f"{{\\an5\\pos({c.cx},{c.cy})}}"

    # Feature #15 — reveal animation. 'karaoke' keeps the per-word highlight
    # path below untouched; the reveal presets emit ONE event per line with a
    # motion tag on appearance (pop = scale-up via \t, fade = \fad, slide-up =
    # \move from below). Unknown values degrade to the karaoke path.
    _anim = animation if animation in ("none", "pop", "fade", "slide-up") else "karaoke"
    _slide = max(int(round(0.05 * video_height)), 20)

    def _reveal_override():
        if _anim == "fade":
            return f"{{\\an5\\pos({c.cx},{c.cy})\\fad(180,0)}}"
        if _anim == "pop":
            return (f"{{\\an5\\pos({c.cx},{c.cy})"
                    f"\\fscx70\\fscy70\\t(0,180,\\fscx100\\fscy100)}}")
        if _anim == "slide-up":
            return f"{{\\an5\\move({c.cx},{c.cy + _slide},{c.cx},{c.cy},0,200)}}"
        return pos_override  # 'none'

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
Style: Default,{font_family},{font_size},{s['color_unspoken']},&H000000FF,{s['outline_color']},{style_back_color},{style_bold},0,0,0,100,100,{s.get('spacing', 0)},0,{style_border_style},{style_outline},{s['shadow']},5,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    style_bold_tag_global = "\\b1" if str(style_bold) in ("-1", "1") else "\\b0"

    for line in lines:
        words      = line["words"]
        line_start = line["line_start"]
        line_end   = line["line_end"]

        # ── Feature #15: reveal animations — one event per line ──────────────
        # Non-karaoke: all words in base (unspoken) colour, no per-word timing
        # slices; a single event carries the reveal motion. Emphasis words keep
        # their highlight+bold+scale (feature #6) even here.
        if _anim != "karaoke":
            _has_emph = any(w.get("emphasis") for w in words)
            parts = []
            for w in words:
                safe_word = _escape_ass_text(_disp(w['word']))
                if w.get("emphasis"):
                    tags = f"{_color_tag(s['color_highlight'])}\\b1\\fscx112\\fscy112"
                    if _glow:
                        tags += _glow_on(s['color_highlight'])
                elif _has_emph:
                    tags = f"{_color_tag(s['color_unspoken'])}{style_bold_tag_global}\\fscx100\\fscy100"
                    if _glow:
                        tags += _glow_off()
                else:
                    tags = _color_tag(s['color_unspoken'])
                    if _glow:
                        tags += _glow_off()
                parts.append(f"{{{tags}}}{safe_word}")
            line_text = _reveal_override() + " ".join(parts)
            e_start = line_start
            e_end = max(line_end, line_start + 0.05)
            events.append(
                f"Dialogue: 0,{format_ass_time(e_start)},{format_ass_time(e_end)},"
                f"Default,,0,0,0,,{line_text}"
            )
            continue

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
            #
            # Feature #6 — keyword emphasis: words flagged w["emphasis"] render
            # in the preset's highlight colour, bold, at 112% scale for their
            # whole lifetime (not just the karaoke instant). ASS override tags
            # persist until changed, so once a line contains ANY emphasized
            # word, every non-emphasized word explicitly resets bold + scale;
            # emphasis-free lines emit the color tag alone — byte-identical to
            # the pre-feature output.
            line_has_emphasis = any(w.get("emphasis") for w in words)
            style_bold_tag = "\\b1" if str(style_bold) in ("-1", "1") else "\\b0"
            parts = []
            for j, w in enumerate(words):
                safe_word = _escape_ass_text(_disp(w['word']))
                is_active = (j == idx)
                if j < idx:
                    role_color = s['color_spoken']
                elif is_active:
                    # Glow presets keep the active word a bright WHITE core and
                    # push the colour into the blurred halo — a same-colour
                    # fill+halo just merges into an unreadable blob.
                    role_color = s['color_unspoken'] if _glow else s['color_highlight']
                else:
                    role_color = s['color_unspoken']
                if w.get("emphasis"):
                    tags = f"{_color_tag(s['color_highlight'])}\\b1\\fscx112\\fscy112"
                    if _glow:
                        tags += _glow_on(s['color_highlight'])
                elif line_has_emphasis:
                    tags = f"{_color_tag(role_color)}{style_bold_tag}\\fscx100\\fscy100"
                    if _glow:
                        tags += _glow_on(s['color_highlight']) if is_active else _glow_off()
                else:
                    tags = _color_tag(role_color)
                    if _glow:
                        tags += _glow_on(s['color_highlight']) if is_active else _glow_off()
                parts.append(f"{{{tags}}}{safe_word}")

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

# Typed-caption emoji overlays sit at the same height as feature #30's
# auto-suggested emoji (just above the lower-third caption).
CAPTION_EMOJI_Y = 0.66


def _extract_caption_emoji_overlays(lines: list) -> list:
    """Typed-emoji → overlay. STRIP every emoji from each line's word text (so
    libass never sees a color glyph it renders as mono/tofu) and return overlay
    specs [{emoji, start, end}] for the PALETTE emoji, each timed to its word's
    LINE. Non-palette emoji are stripped with a warning (no overlay). Mutates
    word['word'] in place. Emoji-free captions return [] and are byte-identical
    to before this existed."""
    from services.emoji import split_caption_emoji, resolve_palette_emoji
    overlays = []
    for line in lines:
        ls, le = line.get("line_start"), line.get("line_end")
        for w in line.get("words", []):
            clean, tokens = split_caption_emoji(w.get("word", ""))
            if not tokens:
                continue
            w["word"] = clean  # libass now renders emoji-free text
            for tok in tokens:
                pal = resolve_palette_emoji(tok)
                if pal:
                    overlays.append({"emoji": pal, "start": ls, "end": le})
                else:
                    print(f"   [Emoji] typed {tok!r} not in the 54-emoji palette "
                          f"— stripped, no overlay", flush=True)
    return overlays


def _burn_caption_emoji_overlays(captioned_path: str, overlays: list,
                                 video_width: int, video_height: int) -> str:
    """Composite typed-caption emoji as timed color PNG overlays onto the
    captioned video via the SAME render_elements path feature #30 uses (one
    consistent system). Multiple emoji on a line spread horizontally. Bakes the
    result back into captioned_path (returned unchanged); on any failure the
    caption-only video is kept rather than lost."""
    from collections import defaultdict
    from services.overlay_renderer import render_elements

    by_line = defaultdict(list)
    for e in overlays:
        by_line[(e["start"], e["end"])].append(e["emoji"])

    elements = []
    for (start, end), emojis in by_line.items():
        n = len(emojis)
        for j, em in enumerate(emojis):
            x = 0.5 + (j - (n - 1) / 2.0) * 0.12   # centered row, ~0.12 apart
            elements.append({
                "id": f"capemoji_{len(elements)}",
                "type": "emoji",
                "x": min(max(x, 0.05), 0.95),
                "y": CAPTION_EMOJI_Y,
                "scale": 1, "rotation": 0, "visible": True,
                "props": {"emoji": em, "height": 0.12, "opacity": 1.0,
                          "start": start, "end": end},
            })
    if not elements:
        return captioned_path

    tmp_out = captioned_path + ".capemoji.mp4"
    try:
        result = render_elements(captioned_path, tmp_out, elements, video_width, video_height)
    except Exception as e:  # noqa: BLE001 — never lose the captioned video over emoji
        print(f"   ⚠ Caption-emoji overlay failed ({e}) — captions kept without emoji", flush=True)
        return captioned_path
    if result == tmp_out and os.path.exists(tmp_out):
        os.replace(tmp_out, captioned_path)   # bake emoji into the returned path
        print(f"   ✓ Burned {len(elements)} typed-caption emoji as color overlays", flush=True)
    return captioned_path


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
    caption_script: str = "telugu",    # 'telugu' | 'tanglish' — caption display script
    emphasis_indices: list = None,     # Feature #6: clip-local word indices to emphasize;
                                       # None → the clip's own auto-tagged set; [] → none
    cut_spans: list = None,            # Feature #14: [[start,end],...] clip-local seconds cut
                                       # from the clip; caption words remap onto the shortened
                                       # timeline (mirrors the worker's video cut). None/[] → no cuts
    animation: str = "karaoke",        # Feature #15: caption reveal animation preset
                                       # 'karaoke' (default) = per-word highlight (unchanged);
                                       # 'none'/'pop'/'fade'/'slide-up' = one-event-per-line reveal
) -> str:
    """words → ASS → burn for a single clip with given style + caption font.

    caption_script='tanglish' renders each word's word_tanglish (edits applied
    first — apply_transcript_edits re-derives the Tanglish of an edited word, so
    the resolver order matches the frontend). Everything else — timing, k-values,
    fonts, positioning — is byte-identical to the telugu path; anything other
    than the literal string 'tanglish' falls back to telugu.

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
    if caption_script != "tanglish":
        caption_script = "telugu"
    wpl = STYLES[style_name].get("words_per_line", MAX_WORDS_PER_LINE)

    transcript = load_transcript(transcript_path)
    clips      = load_clips(clips_path)
    clip       = clips["clips"][clip_index]
    sentences  = transcript.get("sentences", [])
    sent_by_id = {s["id"]: s for s in sentences}

    print(f"📝 Generating captions [{style_name} / {caption_font or DEFAULT_CAPTION_FONT} / {caption_script}] "
          f"for: {clip.get('why', clip.get('hook_text', 'clip'))}")

    segments = clip.get("segments", [])

    # ── Apply transcript edits ────────────────────────────────────────────────
    if transcript_edits:
        _n_word    = len(transcript_edits.get("wordEdits",        []))
        _n_merge   = len(transcript_edits.get("mergedGroups",     []))
        _n_split   = len(transcript_edits.get("lineSplits",       []))
        _n_realign = len(transcript_edits.get("lineRealignments", []))
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
            if _n_merge or _n_split or _n_realign:
                print(f"  ⚠ multi-segment clip {clip_index}: "
                      f"{_n_merge} merge(s), {_n_split} split(s), {_n_realign} line realignment(s) skipped — "
                      f"frontend line indices include gap words; backend does not (not yet remapped)",
                      flush=True)
            transcript_edits = None  # prevent lineSplits grouper / realignment overlay below from misapplying
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
        words = get_words_for_multisegment_clip(transcript, clip, sent_by_id, caption_script)
    else:
        print(f"   Clip time: {clip['start']:.1f}s → {clip['end']:.1f}s"
              + (f" (t=0 at refined {clip['refined_start']:.2f}s)"
                 if clip.get("refined_start") is not None else ""))
        words = get_words_for_clip(transcript, clip["start"], clip["end"], caption_script,
                                   time_zero=clip.get("refined_start"))

    print(f"   Found {len(words)} words")

    if not words:
        print("   ⚠ No words found — skipping captions for this clip")
        return None

    # Feature #6 — keyword emphasis. Indices address the clip's filtered word
    # array (the SAME index space lineSplits use). None → the auto set Gemini
    # tagged at selection time (clip["emphasis_indices"]); an explicit list
    # (possibly empty) from the editor wins — the user's toggles are final.
    _effective_emphasis = (emphasis_indices if emphasis_indices is not None
                           else clip.get("emphasis_indices") or [])
    _n_emph = 0
    for _i in _effective_emphasis:
        if isinstance(_i, int) and 0 <= _i < len(words):
            words[_i]["emphasis"] = True
            _n_emph += 1
    if _n_emph:
        print(f"   ★ Emphasis on {_n_emph} word(s)")

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

    # Line-level re-alignments overlay AFTER grouping: a matched line's words
    # are replaced with the realigned set (fresh karaoke timing inside the
    # line's FIXED span); line boundaries and every other line are untouched.
    # Same cumulative-index matching as the frontend's applyLineRealignments,
    # so preview and burn agree line-for-line.
    _realignments = transcript_edits.get("lineRealignments", []) if transcript_edits else []
    if _realignments:
        from services.apply_transcript_edits import apply_line_realignments
        _n_applied = apply_line_realignments(lines, _realignments, caption_script)
        print(f"   ✎ Line realignments: {_n_applied}/{len(_realignments)} applied", flush=True)

    # Feature #14 — filler/silence cuts. Applied at the LINE level (AFTER
    # grouping + realignments) so emphasis flags and lineSplits indices, both
    # defined on the uncut word array, stay valid: we only drop the words the
    # cut removes and remap survivors onto the post-cut timeline, preserving
    # the line structure. Empty lines vanish. Mirrors the worker's video cut
    # (same spans) so burned captions land on the shortened output.
    if cut_spans:
        from services.filler_removal import apply_cuts_to_words
        _kept_lines = []
        _dropped = 0
        for _line in lines:
            _new_words = apply_cuts_to_words(_line["words"], cut_spans)
            if not _new_words:
                _dropped += 1
                continue
            _line["words"] = _new_words
            _line["line_start"] = _new_words[0]["start"]
            _line["line_end"] = _new_words[-1]["end"]
            _kept_lines.append(_line)
        lines = _kept_lines
        print(f"   ✂ Cuts applied: {len(cut_spans)} span(s), {_dropped} line(s) removed", flush=True)

    print(f"   {len(lines)} lines × up to {wpl} words — karaoke highlight mode")

    # Typed-caption emoji → timed overlays (same path as feature #30). Strips
    # emoji from the word text BEFORE ASS generation so libass never renders a
    # color glyph as mono/tofu; palette emoji are re-emitted as overlays below.
    _caption_emoji = _extract_caption_emoji_overlays(lines)
    if _caption_emoji:
        print(f"   😀 {len(_caption_emoji)} typed-caption emoji → color overlays "
              f"(stripped from caption text)", flush=True)

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
                                       animation=animation,
                                       caption_font=caption_font,
                                       caption_x=caption_x,
                                       caption_y=caption_y,
                                       caption_font_size_frac=caption_font_size,
                                       caption_pill=caption_pill,
                                       caption_script=caption_script)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
    print(f"   ✓ ASS: {ass_path}")

    print(f"   🔥 Burning captions [{style_name}]...")
    success = burn_captions(vertical_clip_path, ass_path, output_path)

    if success:
        # Composite any typed-caption emoji as color PNG overlays (feature #30
        # path). Failure here never loses the captioned video — the emoji are a
        # non-critical enhancement.
        if _caption_emoji:
            output_path = _burn_caption_emoji_overlays(
                output_path, _caption_emoji, video_width, video_height
            )
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