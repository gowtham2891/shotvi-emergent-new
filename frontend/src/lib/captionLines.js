// Mirrors services/caption_renderer.py's line-grouping + timing exactly
// (READ-ONLY reference: cap_word_durations, group_words_into_lines,
// generate_ass_karaoke's per-word event timing), so the canvas preview's
// line breaks and pacing match what the export burns in.
//
// Pure functions of (words, style) -> lines, and (lines, time) -> the
// active line/word — no React, no store. This is also the intended
// foundation for the future Enter-to-split-lines (lineSplits) feature:
// group_words_into_lines is a plain chunk-every-N function today; a later
// caller can pass forced split points before/instead of the modulo chunking
// without changing this module's shape.

export const MAX_WORDS_PER_LINE = 4;
export const MAX_WORD_DURATION = 1.5; // cap single-word duration (seconds)
export const MAX_LINE_DURATION = 4.0; // cap single line display duration (seconds)

// cap_word_durations: silence gaps can make a word's own (start,end) span
// unrealistically long; clip it so it doesn't stretch a line's timing.
export function capWordDurations(words, maxWordDuration = MAX_WORD_DURATION) {
  return words.map((w) =>
    w.end - w.start > maxWordDuration ? { ...w, end: w.start + maxWordDuration } : w
  );
}

// group_words_into_lines: chunk sequentially into groups of wordsPerLine;
// line span is [first word's start, last word's end], capped at
// maxLineDuration; then trim overlaps against the next line by 0.05s,
// exactly as the backend does.
export function groupWordsIntoLines(words, wordsPerLine = MAX_WORDS_PER_LINE, maxLineDuration = MAX_LINE_DURATION) {
  const lines = [];
  for (let i = 0; i < words.length; i += wordsPerLine) {
    const chunk = words.slice(i, i + wordsPerLine);
    if (!chunk.length) continue;
    const lineStart = chunk[0].start;
    let lineEnd = chunk[chunk.length - 1].end;
    if (lineEnd - lineStart > maxLineDuration) lineEnd = lineStart + maxLineDuration;
    lines.push({ words: chunk, lineStart, lineEnd });
  }
  for (let i = 0; i < lines.length - 1; i++) {
    if (lines[i].lineEnd > lines[i + 1].lineStart) {
      lines[i] = { ...lines[i], lineEnd: lines[i + 1].lineStart - 0.05 };
    }
  }
  return lines;
}

// Convenience: the full pure pipeline the backend runs before ASS generation.
export function buildCaptionLines(words, wordsPerLine = MAX_WORDS_PER_LINE) {
  return groupWordsIntoLines(capWordDurations(words), wordsPerLine);
}

// Which line (if any) is on screen at `time`. Faithful to the backend: a
// gap between one line's (overlap-trimmed) lineEnd and the next line's
// lineStart shows nothing, exactly like a real ASS timeline gap.
export function findActiveLine(lines, time) {
  return lines.find((l) => time >= l.lineStart && time < l.lineEnd) || null;
}

// Per-word event timing within a line (generate_ass_karaoke): word i is
// "active" from its own start until the NEXT word's start (not its own
// end) — so highlight persists through any natural pause between words,
// clamped to the line's end for the last word. Equivalent to: the active
// word is the last one whose start <= time.
export function findActiveWordIndex(line, time) {
  if (!line || !line.words.length) return -1;
  let idx = 0;
  for (let i = 0; i < line.words.length; i++) {
    if (line.words[i].start <= time) idx = i;
    else break;
  }
  return idx;
}
