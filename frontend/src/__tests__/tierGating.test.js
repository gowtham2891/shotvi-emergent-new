/**
 * Features #17/#19/#21 — frontend tier surfacing: premium-preset marking
 * (mirror of api/tiers.PREMIUM_PRESETS) and billing-status entitlement fields.
 */
import { isPremiumPreset, PREMIUM_PRESET_IDS, CAPTION_STYLES } from "@/api/renders";

describe("premium preset marking (mirror of backend)", () => {
  test("the 6 new presets are premium; the originals are not", () => {
    for (const id of ["purple-punch", "ocean-blue", "sunshine", "mono-bold", "pink-pop", "lime-shock"]) {
      expect(isPremiumPreset(id)).toBe(true);
    }
    for (const id of ["bold-yellow", "hormozi", "typewriter", "split-color"]) {
      expect(isPremiumPreset(id)).toBe(false);
    }
  });

  test("every premium id is a real preset in the dropdown", () => {
    for (const id of PREMIUM_PRESET_IDS) {
      expect(CAPTION_STYLES.some((s) => s.id === id)).toBe(true);
    }
  });
});
