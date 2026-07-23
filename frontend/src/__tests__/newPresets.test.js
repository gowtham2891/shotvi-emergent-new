/**
 * Feature #16 — the 6 new caption presets exist in the dropdown AND the
 * preview, and their highlight colours decode to the intended hex (the
 * WYSIWYG contract with services/caption_renderer.py :: STYLES).
 */
import { CAPTION_STYLES, isKnownStyle } from "@/api/renders";
import { CAPTION_STYLE_PREVIEW } from "@/data/captionStylePreview";

const NEW = {
  "purple-punch": "#a855f7",
  "ocean-blue": "#22d3ee",
  sunshine: "#fb923c",
  "mono-bold": "#ffffff",
  "pink-pop": "#ec4899",
  "lime-shock": "#a3e635",
};

describe("new caption presets", () => {
  test("all 6 are in the dropdown and recognized by isKnownStyle", () => {
    for (const id of Object.keys(NEW)) {
      expect(CAPTION_STYLES.some((s) => s.id === id)).toBe(true);
      expect(isKnownStyle(id)).toBe(true);
    }
    // 11 original + 6 new = 17 (mirrors backend STYLES count).
    expect(CAPTION_STYLES.length).toBe(17);
  });

  test("each new preset's highlight colour decodes to the intended hex", () => {
    for (const [id, hex] of Object.entries(NEW)) {
      expect(CAPTION_STYLE_PREVIEW[id]).toBeTruthy();
      expect(CAPTION_STYLE_PREVIEW[id].colorHighlight).toBe(hex);
    }
  });

  test("box presets expose a box; no-box presets are null (border_style parity)", () => {
    expect(CAPTION_STYLE_PREVIEW["pink-pop"].box).not.toBeNull(); // border_style 3
    expect(CAPTION_STYLE_PREVIEW["sunshine"].box).toBeNull(); // border_style 1
  });
});
