/**
 * Mirrors services/caption_renderer.py's group_words_into_lines,
 * cap_word_durations, and generate_ass_karaoke's per-word event timing
 * (READ-ONLY reference — logic re-implemented here, not imported).
 * Pulled forward from the deferred CapCut-editor task so the canvas
 * preview's line breaks and pacing match export, instead of a fast
 * sliding word-window.
 */
import {
  capWordDurations,
  groupWordsIntoLines,
  buildCaptionLines,
  findActiveLine,
  findActiveWordIndex,
  MAX_WORD_DURATION,
  MAX_LINE_DURATION,
} from "@/lib/captionLines";

const w = (text, start, end) => ({ text, start, end });

describe("capWordDurations", () => {
  test("caps a word whose span exceeds MAX_WORD_DURATION (silence gap)", () => {
    const words = [w("a", 0, 0.3), w("b", 5, 8)]; // 3s span, from a silence gap
    const capped = capWordDurations(words);
    expect(capped[0]).toEqual({ text: "a", start: 0, end: 0.3 }); // untouched
    expect(capped[1].end).toBeCloseTo(5 + MAX_WORD_DURATION, 5);
  });

  test("does not mutate the input array", () => {
    const words = [w("a", 0, 10)];
    capWordDurations(words);
    expect(words[0].end).toBe(10);
  });
});

describe("groupWordsIntoLines", () => {
  test("chunks sequentially into groups of wordsPerLine (default 4)", () => {
    const words = Array.from({ length: 9 }, (_, i) => w(`w${i}`, i, i + 0.5));
    const lines = groupWordsIntoLines(words, 4);
    expect(lines.map((l) => l.words.length)).toEqual([4, 4, 1]);
    expect(lines[0].lineStart).toBe(0);
    expect(lines[0].lineEnd).toBe(3.5); // last word (idx 3) end
  });

  test("big-bold's 2-words-per-line override", () => {
    const words = Array.from({ length: 5 }, (_, i) => w(`w${i}`, i, i + 0.5));
    const lines = groupWordsIntoLines(words, 2);
    expect(lines.map((l) => l.words.length)).toEqual([2, 2, 1]);
  });

  test("caps line duration at MAX_LINE_DURATION", () => {
    const words = [w("a", 0, 0.2), w("b", 1, 1.2), w("c", 2, 2.2), w("d", 10, 10.5)];
    const lines = groupWordsIntoLines(words, 4);
    expect(lines[0].lineEnd).toBe(0 + MAX_LINE_DURATION); // not 10.5
  });

  test("trims overlap between consecutive lines by 0.05s", () => {
    // "a" spans 0..5 and would overlap "b" starting at 3 — one word per
    // line (wordsPerLine=1) isolates the overlap-trim behavior directly.
    const words = [w("a", 0, 5), w("b", 3, 3.5)];
    const lines = groupWordsIntoLines(words, 1);
    expect(lines[0].lineEnd).toBeCloseTo(3 - 0.05, 5);
  });
});

describe("buildCaptionLines (cap + group pipeline)", () => {
  test("applies word-duration capping before grouping", () => {
    // "b" (the line's LAST word, which determines lineEnd) has a bogus 19s
    // span from a silence gap — capping must happen before grouping, or
    // lineEnd would be 20 instead of 1 + MAX_WORD_DURATION.
    const words = [w("a", 0, 0.4), w("b", 1, 20)];
    const lines = buildCaptionLines(words, 4);
    expect(lines[0].lineEnd).toBeCloseTo(1 + MAX_WORD_DURATION, 5); // 2.5, not 20
    expect(lines[0].lineEnd).toBeLessThan(MAX_LINE_DURATION);
  });
});

describe("findActiveLine / findActiveWordIndex", () => {
  const lines = groupWordsIntoLines(
    [w("hello", 0, 0.5), w("world", 0.6, 1.2), w("how", 1.2, 1.5), w("are", 1.5, 1.8), w("you", 3, 3.4)],
    4
  );
  // lines[0] = [hello, world, how, are] span 0..1.8 (trimmed vs lines[1] start=3)
  // lines[1] = [you] span 3..3.4

  test("no line is active during a gap between lines", () => {
    expect(findActiveLine(lines, 2.5)).toBeNull();
  });

  test("finds the line covering a given time", () => {
    expect(findActiveLine(lines, 0.7)).toBe(lines[0]);
    expect(findActiveLine(lines, 3.1)).toBe(lines[1]);
  });

  test("active word persists through a pause until the NEXT word starts, not its own end", () => {
    const line = lines[0];
    // "hello" ends at 0.5, "world" starts at 0.6 -> at t=0.55 (mid-gap),
    // "hello" (idx 0) is still the active word.
    expect(findActiveWordIndex(line, 0.55)).toBe(0);
    expect(findActiveWordIndex(line, 0.6)).toBe(1);
  });

  test("last word in a line stays active until lineEnd", () => {
    expect(findActiveWordIndex(lines[0], 1.79)).toBe(3); // "are"
  });

  test("no active line -> no active word", () => {
    expect(findActiveWordIndex(findActiveLine(lines, 2.5), 2.5)).toBe(-1);
  });
});
