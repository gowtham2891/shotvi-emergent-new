// Canvas-preview approximations of the backend's ASS karaoke caption styles
// (services/caption_renderer.py :: STYLES — READ-ONLY reference, transcribed
// as raw hex below and decoded programmatically, not hand-computed, so the
// decode itself is testable — see src/__tests__/captionStylePreview.test.js).
//
// Known divergences from the backend, kept because there is no faithful
// CSS equivalent:
//  - The Telugu caption fonts (Noto Sans Telugu default, Ramabhadra, Mandali)
//    are loaded as `@font-face` web fonts in index.css from
//    /fonts/*.ttf — the SAME .ttf files the backend consumes via
//    fontsdir (services/fonts.py :: CAPTION_FONTS_DIR). So the preview
//    renders in a byte-identical font regardless of what the viewer's OS
//    has installed. Only "typewriter" (Courier New) still uses a system font.
//  - outline_width -> outline treatment: caption_renderer.py draws a stroke
//    outline via ASS BorderStyle; the CSS equivalent (-webkit-text-stroke)
//    turned out to visually overwhelm dense Telugu glyphs at caption font
//    sizes (looked like solid dark blobs, not outlined text — a real
//    rendering bug found during this pass, unrelated to color decoding).
//    Replaced with a thin, small, cross-browser 4-direction text-shadow
//    outline instead (also works in Firefox, which does not support
//    -webkit-text-stroke at all).
//  - "shadow" (an ASS offset-copy render) is approximated with CSS
//    text-shadow blur, not a literal offset copy.
//  - the backend renders one wrapped LINE at a time (words_per_line: 4, or
//    2 for big-bold); this preview keeps the app's existing sliding
//    word-window instead. Real line-grouping is deferred to the planned
//    CapCut-style caption editor.
//  - red-pop and clean-dark's back_color alpha bytes (&HCC000000,
//    &HDD000000) decode to ~0.2 and ~0.13 opacity under ASS alpha
//    semantics, despite their source comments claiming "near-opaque" /
//    "dark solid bar". Re-verified twice now (hand arithmetic, an
//    independent Python cross-check, and this module's own decoder +
//    tests) — all agree. Mirrored literally (matches what the backend
//    actually burns in) rather than "corrected" to the comment's intent —
//    see /KNOWN_ISSUES.md. Flagged as a possible backend inconsistency,
//    not fixed here (read-only) — pending verification against a real
//    exported clip.

import { decodeAssColor } from "@/lib/assColor";
import { MAX_WORDS_PER_LINE } from "@/lib/captionLines";

// Transcribed directly from services/caption_renderer.py :: STYLES.
// border_style: 1 = outline+shadow (no box); 3 = opaque box behind text.
export const RAW_STYLES = {
  "bold-yellow": {
    colorHighlight: "&H0000FFFF",
    colorSpoken: "&H00AAAAAA",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&H60000000",
    outlineWidth: 3,
    borderStyle: 1,
    shadow: 0,
  },
  "white-minimal": {
    colorHighlight: "&H00FFFFFF",
    colorSpoken: "&H00CCCCCC",
    colorUnspoken: "&H00AAAAAA",
    backColor: "&H00000000",
    outlineWidth: 2,
    borderStyle: 1,
    shadow: 1,
  },
  "red-pop": {
    colorHighlight: "&H000000FF",
    colorSpoken: "&H00888888",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&HCC000000",
    outlineWidth: 3,
    borderStyle: 3,
    shadow: 0,
  },
  "clean-dark": {
    colorHighlight: "&H00FFD700",
    colorSpoken: "&H00999999",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&HDD000000",
    outlineWidth: 2,
    borderStyle: 3,
    shadow: 0,
  },
  hormozi: {
    colorHighlight: "&H0000E5FF",
    colorSpoken: "&H00CCCCCC",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&H14000000",
    outlineWidth: 5,
    borderStyle: 3,
    shadow: 0,
  },
  "fire-gradient": {
    colorHighlight: "&H00006BFF",
    colorSpoken: "&H00888888",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&H00000000",
    outlineWidth: 3,
    borderStyle: 1,
    shadow: 2,
  },
  "neon-green": {
    colorHighlight: "&H0041FF00",
    colorSpoken: "&H00166600",
    colorUnspoken: "&H00CCCCCC",
    backColor: "&H1F000000",
    outlineWidth: 2,
    borderStyle: 3,
    shadow: 1,
  },
  "outline-only": {
    colorHighlight: "&H00FFFFFF",
    colorSpoken: "&H00DDDDDD",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&H00000000",
    outlineWidth: 5,
    borderStyle: 1,
    shadow: 0,
  },
  "big-bold": {
    colorHighlight: "&H0000D7FF",
    colorSpoken: "&H00AAAAAA",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&H00000000",
    outlineWidth: 4,
    borderStyle: 1,
    shadow: 2,
    wordsPerLine: 2, // only style that overrides STYLES.get("words_per_line", MAX_WORDS_PER_LINE)
  },
  typewriter: {
    colorHighlight: "&H00FFFFFF",
    colorSpoken: "&H00FFFFFF",
    colorUnspoken: "&HFFFFFFFF", // alpha=FF -> invisible ("not yet typed")
    backColor: "&H4D000000",
    outlineWidth: 1,
    borderStyle: 3,
    shadow: 0,
  },
  "split-color": {
    colorHighlight: "&H00C76EFF",
    colorSpoken: "&H00AAAAAA",
    colorUnspoken: "&H00FFFFFF",
    backColor: "&H00000000",
    outlineWidth: 3,
    borderStyle: 1,
    shadow: 1,
  },
};

// Deterministic Telugu caption stack: the bundled @font-face families load
// FIRST (Noto Sans Telugu = default; Ramabhadra / Mandali per user pick), and
// serve the SAME .ttf the backend burns via `fontsdir` — so preview and export
// render byte-identical shapes on every machine, including those without any
// Telugu font installed. `sans-serif` is the last-resort fallback when the
// web font is still loading or the request is blocked; the Nirmala UI stop was
// removed because it silently drifted preview from export on Windows hosts.
const TELUGU_STACK = '"Noto Sans Telugu", sans-serif';
const RAMABHADRA_STACK = '"Ramabhadra", "Noto Sans Telugu", sans-serif';
const MANDALI_STACK = '"Mandali", "Noto Sans Telugu", sans-serif';
const CAPTION_FONT_STACKS = {
  "Noto Sans Telugu": TELUGU_STACK,
  Ramabhadra: RAMABHADRA_STACK,
  Mandali: MANDALI_STACK,
};
// Public lookup used by editor UI (caption font dropdown / Inspector).
export const getCaptionFontStack = (name) =>
  CAPTION_FONT_STACKS[name] || TELUGU_STACK;

const FONT_OVERRIDES = { typewriter: '"Courier New", monospace' };
const FONT_WEIGHT_OVERRIDES = { "white-minimal": 400, "clean-dark": 400, typewriter: 700 };

// 4-direction shadow outline — a thin, crisp, cross-browser alternative to
// -webkit-text-stroke (which visually overwhelmed dense Telugu glyphs at
// caption font sizes, and isn't supported in Firefox at all). Offset scales
// gently with outline_width so relative "heavier outline" styles (hormozi,
// outline-only) still read as slightly bolder than thin ones (typewriter).
const outlineShadow = (outlineWidth) => {
  const px = Math.min(1.75, 0.7 + outlineWidth * 0.2);
  const o = px.toFixed(2);
  return `-${o}px -${o}px 0 #000, ${o}px -${o}px 0 #000, -${o}px ${o}px 0 #000, ${o}px ${o}px 0 #000`;
};

const SHADOW_LAYERS = {
  0: null,
  1: "0 2px 8px rgba(0,0,0,0.65)",
  2: "0 3px 0 rgba(0,0,0,0.6), 0 0 20px rgba(0,0,0,0.5)",
};

const boxStyle = (opacity) =>
  opacity > 0
    ? { background: `rgba(0,0,0,${opacity})`, padding: "0.15em 0.45em", borderRadius: 6 }
    : null;

function buildPreview(id, raw) {
  const highlight = decodeAssColor(raw.colorHighlight);
  const spoken = decodeAssColor(raw.colorSpoken);
  const unspoken = decodeAssColor(raw.colorUnspoken);
  const back = decodeAssColor(raw.backColor);

  const textShadow = [outlineShadow(raw.outlineWidth), SHADOW_LAYERS[raw.shadow]]
    .filter(Boolean)
    .join(", ");

  return {
    fontFamily: FONT_OVERRIDES[id] || TELUGU_STACK,
    fontWeight: FONT_WEIGHT_OVERRIDES[id] || 900,
    colorHighlight: highlight.hex,
    colorSpoken: spoken.hex,
    // typewriter's "unspoken" word is fully transparent by design (alpha
    // 0xFF -> opacity 0) — render as literally invisible, not a dim color.
    colorUnspoken: unspoken.opacity === 0 ? "transparent" : unspoken.hex,
    // Only border_style 3 renders an actual box; for border_style 1,
    // back_color is a shadow tint (already folded into textShadow above).
    box: raw.borderStyle === 3 ? boxStyle(back.opacity) : null,
    textShadow,
    // STYLES[id].get("words_per_line", MAX_WORDS_PER_LINE) — only big-bold
    // overrides this in the backend.
    wordsPerLine: raw.wordsPerLine || MAX_WORDS_PER_LINE,
  };
}

export const CAPTION_STYLE_PREVIEW = Object.fromEntries(
  Object.entries(RAW_STYLES).map(([id, raw]) => [id, buildPreview(id, raw)])
);

export const DEFAULT_CAPTION_STYLE_PREVIEW = CAPTION_STYLE_PREVIEW["bold-yellow"];

export const getCaptionStylePreview = (id) =>
  CAPTION_STYLE_PREVIEW[id] || DEFAULT_CAPTION_STYLE_PREVIEW;
