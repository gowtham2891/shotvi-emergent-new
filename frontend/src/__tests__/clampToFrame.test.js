/**
 * Commit 5 — Known Issue 3 fix: caption drag stays inside the frame.
 *
 * The editor stores caption position as a 0–1 CENTER fraction, so a naive
 * (0.02, 0.98) center clamp still lets the rendered text bounding box spill
 * off the frame at the sides / top / bottom, especially for wide multi-word
 * Telugu captions. clampToFrame accepts the measured text bounding box + the
 * current canvas dims and clamps the center so no edge of the box crosses
 * the frame; oversized text symmetric-overflows around 0.5.
 */
import { clampToFrame } from "@/lib/clampToFrame";

const CANVAS = { w: 360, h: 640 };            // 9:16 stage in the editor
const CAPTION = { w: 200, h: 60 };            // a typical caption bounding box

describe("clampToFrame — the four frame edges", () => {
  test("left edge: center is pushed right so the left of the box sits at frame x=0", () => {
    // 200px-wide caption at 360px canvas → half-width fraction = 100/360 ≈ 0.2778.
    // Center dragged to x=0 (far left) must snap to x = halfW so left edge = 0.
    const { x } = clampToFrame(0, 0.5, CAPTION.w, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(x).toBeCloseTo(CAPTION.w / 2 / CANVAS.w, 6);
    // …and the left edge of the rendered box lands exactly at frame x=0.
    const leftEdgeFraction = x - CAPTION.w / 2 / CANVAS.w;
    expect(leftEdgeFraction).toBeCloseTo(0, 6);
  });

  test("right edge: center is pushed left so the right of the box sits at frame x=1", () => {
    const { x } = clampToFrame(1, 0.5, CAPTION.w, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(x).toBeCloseTo(1 - CAPTION.w / 2 / CANVAS.w, 6);
    const rightEdgeFraction = x + CAPTION.w / 2 / CANVAS.w;
    expect(rightEdgeFraction).toBeCloseTo(1, 6);
  });

  test("top edge: center is pushed down so the top of the box sits at frame y=0", () => {
    const { y } = clampToFrame(0.5, 0, CAPTION.w, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(y).toBeCloseTo(CAPTION.h / 2 / CANVAS.h, 6);
    const topEdgeFraction = y - CAPTION.h / 2 / CANVAS.h;
    expect(topEdgeFraction).toBeCloseTo(0, 6);
  });

  test("bottom edge: center is pushed up so the bottom of the box sits at frame y=1", () => {
    const { y } = clampToFrame(0.5, 1, CAPTION.w, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(y).toBeCloseTo(1 - CAPTION.h / 2 / CANVAS.h, 6);
    const bottomEdgeFraction = y + CAPTION.h / 2 / CANVAS.h;
    expect(bottomEdgeFraction).toBeCloseTo(1, 6);
  });
});

describe("clampToFrame — untouched interior positions are pass-through", () => {
  test("a center-region drag point is not moved", () => {
    const { x, y } = clampToFrame(0.5, 0.5, CAPTION.w, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(x).toBeCloseTo(0.5, 6);
    expect(y).toBeCloseTo(0.5, 6);
  });

  test("frontend default caption anchor (0.5, 0.82) is inside the safe range for a normal caption", () => {
    // Sanity: the default anchor (Commit 4) must be legal — Commit 5 must not
    // silently push it upward.
    const { x, y } = clampToFrame(0.5, 0.82, CAPTION.w, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(x).toBeCloseTo(0.5, 6);
    expect(y).toBeCloseTo(0.82, 6);
  });
});

describe("clampToFrame — oversized text symmetric overflow", () => {
  test("a caption wider than the frame pins the x-center at 0.5 so overflow is symmetric", () => {
    // 400px caption on 360px canvas — half-width 0.556 > 0.5, so there is no
    // legal center that fits. Pin to 0.5.
    const { x } = clampToFrame(0.1, 0.5, 400, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(x).toBe(0.5);
    const { x: x2 } = clampToFrame(0.9, 0.5, 400, CAPTION.h, CANVAS.w, CANVAS.h);
    expect(x2).toBe(0.5);
  });

  test("a caption taller than the frame pins the y-center at 0.5", () => {
    const { y } = clampToFrame(0.5, 0.05, CAPTION.w, 900, CANVAS.w, CANVAS.h);
    expect(y).toBe(0.5);
  });
});

describe("clampToFrame — degenerate canvas dimensions do not crash", () => {
  test("zero/negative canvas dims fall back to the plain 2%–98% clamp on both axes", () => {
    // Element unmeasured / canvas ref not yet attached — should still keep
    // the drag inside a safe range, not throw and not send NaN through.
    expect(clampToFrame(-1, 2, 10, 10, 0, 0)).toEqual({ x: 0.02, y: 0.98 });
  });
});
