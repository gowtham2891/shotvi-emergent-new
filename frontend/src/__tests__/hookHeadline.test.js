/**
 * Feature #5 — auto hook title: a clean clip's headline element is
 * pre-filled from clip.hook (ClipOut.hook_text) and made visible; drafts
 * still win because openClip applies them after this runs.
 */
import { applyHookHeadline } from "@/lib/hookHeadline";
import { INITIAL_ELEMENTS } from "@/data/mockData";

const clone = (x) => JSON.parse(JSON.stringify(x));

test("fills the headline element's text and makes it visible", () => {
  const out = applyHookHeadline(clone(INITIAL_ELEMENTS), "ఈ ఒక్క AI tool మీ life మార్చేస్తుంది!");
  const headline = out.find((el) => el.type === "headline");
  expect(headline.visible).toBe(true);
  expect(headline.props.text).toBe("ఈ ఒక్క AI tool మీ life మార్చేస్తుంది!");
  // Telugu has no case; uppercasing only embedded English tokens reads wrong.
  expect(headline.props.uppercase).toBe(false);
});

test("non-headline elements pass through by reference (no churn)", () => {
  const input = clone(INITIAL_ELEMENTS);
  const out = applyHookHeadline(input, "hook");
  input.forEach((el, i) => {
    if (el.type !== "headline") expect(out[i]).toBe(input[i]);
  });
});

test("empty/whitespace/missing hook is a strict no-op", () => {
  const input = clone(INITIAL_ELEMENTS);
  expect(applyHookHeadline(input, "")).toBe(input);
  expect(applyHookHeadline(input, "   ")).toBe(input);
  expect(applyHookHeadline(input, null)).toBe(input);
  expect(applyHookHeadline(input, undefined)).toBe(input);
  const headline = input.find((el) => el.type === "headline");
  expect(headline.visible).toBe(false); // untouched default stays hidden
});

test("hook text is trimmed", () => {
  const out = applyHookHeadline(clone(INITIAL_ELEMENTS), "  hook line  ");
  expect(out.find((el) => el.type === "headline").props.text).toBe("hook line");
});
