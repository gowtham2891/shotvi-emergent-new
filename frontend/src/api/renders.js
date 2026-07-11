import { client, toApiError } from "@/api/client";

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
// keeps the payload clean).
export const OVERLAY_ELEMENT_TYPES = new Set(["progress", "sticker", "logo", "headline"]);

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
    transcriptEdits = null, // {wordEdits, mergedGroups, lineSplits}
    captionX = null, // 0–1 fraction of canvas width (caption center)
    captionY = null, // 0–1 fraction of canvas height (caption center)
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
  if (transcriptEdits) req.transcript_edits = transcriptEdits;
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
  // Serialize the visible overlay elements (progress/sticker/logo/headline) for
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
