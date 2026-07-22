import { client, toApiError } from "@/api/client";
import { serializeTranscriptEdits } from "@/lib/transcriptEdits";

// ── Caption styles ───────────────────────────────────────────────
// The backend exposes no styles endpoint; these ids mirror STYLES in
// services/caption_renderer.py exactly. Sending an unknown id would make the
// backend fall back silently, so the UI must only offer these.
// No hand-maintained swatch color here — the Inspector derives each button's
// swatch from captionStylePreview.js's decoded colorHighlight, so it can
// never drift from what the canvas (and export) actually renders.
export const CAPTION_STYLES = [
  { id: "bold-yellow", name: "Bold Yellow" },
  { id: "white-minimal", name: "White Minimal" },
  { id: "red-pop", name: "Red Pop" },
  { id: "clean-dark", name: "Clean Dark" },
  { id: "hormozi", name: "Hormozi" },
  { id: "fire-gradient", name: "Fire Gradient" },
  { id: "neon-green", name: "Neon Green" },
  { id: "outline-only", name: "Outline Only" },
  { id: "big-bold", name: "Big Bold" },
  { id: "typewriter", name: "Typewriter" },
  { id: "split-color", name: "Split Color" },
];
export const DEFAULT_STYLE_ID = "bold-yellow";
export const isKnownStyle = (id) => CAPTION_STYLES.some((s) => s.id === id);

// ── Caption fonts ────────────────────────────────────────────────
// The three bundled Telugu caption fonts the backend resolves deterministically
// via libass fontsdir (services/fonts.py :: CAPTION_FONTS). Order = dropdown
// order; the first is the default the backend falls back to when caption_font
// is omitted, so an untouched default selection must NOT be serialized (keeps
// default exports byte-identical to before the dropdown existed).
export const CAPTION_FONTS = ["Noto Sans Telugu", "Ramabhadra", "Mandali"];
export const DEFAULT_CAPTION_FONT = "Noto Sans Telugu";
export const isKnownCaptionFont = (name) => CAPTION_FONTS.includes(name);

// Formats supported by FORMAT_CONFIG in api/worker.py. Output is always mp4
// at fixed 1080-based canvas sizes — resolution/container are NOT selectable.
export const EXPORT_FORMATS = ["9:16", "1:1", "16:9"];
export const BACKGROUND_OPTIONS = ["blur", "black", "white", "color"];

// Caption default center position — mirrors defaultElementForType('caption') in
// store/useAppStore.js (x from base = 0.5, y = 0.82). Duplicated here on purpose:
// useAppStore imports THIS module, so importing back would be circular. If the
// element default changes, update both. Used only for the drag-detection below.
export const CAPTION_DEFAULT_POSITION = { x: 0.5, y: 0.82 };
const CAPTION_POS_EPS = 1e-3;

// Overlay element types the backend can burn (services/overlay_renderer.py ::
// _PREPARERS). The `caption` element is intentionally excluded — its position
// flows via caption_x/caption_y and the backend burns captions in a separate
// pass (render_elements ignores non-overlay types anyway; excluding here just
// keeps the payload clean). `image` carries an opaque image_id the backend
// resolves + burns through the same single composite pass.
export const OVERLAY_ELEMENT_TYPES = new Set(["progress", "logo", "headline", "image"]);

// ── EditDocument → RerenderRequest ───────────────────────────────
//
// COORDINATE CONTRACT: the editor stores all positions as 0–1 CENTER fractions of
// canvas size, and they stay normalized in every outgoing payload — never pixels.
// Stage 6: the caption's center x/y flow as caption_x/caption_y (0–1); the backend
// converts to pixels at render resolution (canvas_coords.to_pixel_center). They are
// sent ONLY when the caption was dragged off its default (epsilon-guarded) — an
// untouched caption omits them so the backend renders its default path, byte-
// identical to today. crop_box is already 0–1 fractions on both sides.
export function buildRerenderRequest(editDoc = {}) {
  const {
    style = DEFAULT_STYLE_ID,
    format = "9:16",
    background = "blur",
    bgColor = "#000000",
    useAutocrop = true,
    trimStart = 0.0,
    trimEnd = -1.0,
    cropMode = "auto",
    cropBox = null, // {x, y, w, h} as 0–1 fractions
    selectedSubject = null,
    transcriptEdits = null, // STORE shape: {wordEdits: {[wordId]: {text, …}}, mergedGroups, lineSplits} — serialized to the backend list shape below
    captionFont = null, // one of CAPTION_FONTS; sent as caption_font only when non-default (see below)
    captionX = null, // 0–1 fraction of canvas width (caption center)
    captionY = null, // 0–1 fraction of canvas height (caption center)
    // BUG-001 partial fix — caption Size (0–1 fraction of canvas height, same
    // units the preview scales by) and Background Pill (or null when no pill).
    // Sent to the backend as caption_font_size and caption_pill; when both are
    // null / left at defaults, the payload OMITS them so old backends keep
    // rendering the preset defaults byte-identically to today.
    captionFontSize = null,
    captionPill = null,
    // Telugu ⇄ Tanglish toggle: sent as caption_script ONLY when 'tanglish'.
    // 'telugu' is the backend default, so omitting it keeps script-untouched
    // export payloads byte-identical to before the toggle existed; junk
    // values (old drafts) are also omitted → backend renders telugu.
    captionScript = null,
    elements = null, // full EditDocument elements (0–1 coords); filtered below
  } = editDoc;

  const req = {
    style: isKnownStyle(style) ? style : DEFAULT_STYLE_ID,
    format: EXPORT_FORMATS.includes(format) ? format : "9:16",
    background,
    bg_color: bgColor,
    use_autocrop: useAutocrop,
    trim_start: trimStart,
    trim_end: trimEnd,
    crop_mode: cropMode,
  };
  if (cropBox) req.crop_box = cropBox;
  if (selectedSubject) req.selected_subject = selectedSubject;
  // Caption font: serialize ONLY when it's a known caption font other than the
  // default. The default (Noto Sans Telugu) is what the backend renders when
  // caption_font is omitted, so leaving it out keeps default exports byte-
  // identical; an unknown/legacy value (e.g. an old draft's "Outfit") is also
  // omitted so the backend falls back to its own default rather than crashing.
  if (isKnownCaptionFont(captionFont) && captionFont !== DEFAULT_CAPTION_FONT) {
    req.caption_font = captionFont;
  }
  // Transcript edits cross the wire in the backend's TranscriptEdits shape
  // (wordEdits as a ref-addressed LIST — api/models.py:39-42), never the
  // store's id-keyed dict: pydantic 422s on a dict, even an empty one. The
  // serializer returns null when there's nothing to send, so the field is
  // omitted and an edit-free export payload stays byte-identical to today.
  const wireTranscriptEdits = serializeTranscriptEdits(transcriptEdits);
  if (wireTranscriptEdits) req.transcript_edits = wireTranscriptEdits;
  // Send caption center only when moved from default (both coords required by the
  // backend); epsilon stops float-noise from flipping default↔positioned paths.
  if (captionX != null && captionY != null) {
    const moved =
      Math.abs(captionX - CAPTION_DEFAULT_POSITION.x) >= CAPTION_POS_EPS ||
      Math.abs(captionY - CAPTION_DEFAULT_POSITION.y) >= CAPTION_POS_EPS;
    if (moved) {
      req.caption_x = captionX;
      req.caption_y = captionY;
    }
  }
  // BUG-001 partial fix — carry the caption's editor size + background pill.
  // Only serialize when set (non-null) so old drafts / captions-untouched
  // exports produce the pre-fix payload byte-for-byte, keeping every existing
  // regression test green.
  if (typeof captionFontSize === "number" && captionFontSize > 0) {
    req.caption_font_size = captionFontSize;
  }
  if (captionScript === "tanglish") {
    req.caption_script = "tanglish";
  }
  if (captionPill && captionPill.enabled) {
    // Snake-case for the API; only the fields the backend consumes.
    req.caption_pill = {
      enabled: true,
      color: captionPill.color,
      opacity: captionPill.opacity,
      padding: captionPill.padding,
      radius: captionPill.radius,
    };
  }
  // Serialize the visible overlay elements (progress/logo/headline) for
  // the backend burn-in pass. Coords stay 0–1 normalized — no pixel math here
  // (the server converts in canvas_coords). Omit the field entirely when there
  // are no visible overlays so a captions-only draft's payload is unchanged
  // (backend then takes the tested render_elements noop path).
  if (Array.isArray(elements)) {
    const overlays = elements.filter(
      (el) => OVERLAY_ELEMENT_TYPES.has(el.type) && el.visible !== false
    );
    if (overlays.length) req.elements = overlays;
  }
  return req;
}

export async function startRerender(jobId, clipIndex, request) {
  try {
    const { data } = await client.post(
      `/jobs/${encodeURIComponent(jobId)}/clips/${clipIndex}/rerender`,
      request
    );
    return data.rerender_job_id;
  } catch (err) {
    throw toApiError(err, "Could not start the export render");
  }
}
