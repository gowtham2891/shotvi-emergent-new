"""
Apply user transcript edits (mergedGroups, lineSplits, wordEdits) to a transcript dict
before caption rendering, so backend exports match the browser preview.

Port of:
  - frontend/src/pages/Editor.jsx  mergedTranscript useMemo (merge timing extension)
  - frontend/src/pages/Editor.jsx  getScriptLines (lineSplit-aware grouping)
  - frontend/src/hooks/useCaptions.js  groupIntoLines (line duration/overlap logic)

TODO: structural transcript ops (add/delete caption line) are NOT yet supported as
export deltas. localTranscript is the canvas source of truth but is never sent to the
backend. These ops clear wordEdits in the frontend store and set hasStructuralEdits=True
so ExportModal warns the user. Future work: add a StructuralEdit delta type, or send
the full localTranscript in the rerender payload.
"""

from copy import deepcopy

# Mirror caption_renderer.py and useCaptions.js constants exactly.
WORDS_PER_LINE    = 4
MAX_WORD_DURATION = 1.5   # cap single-word duration (seconds)
MAX_LINE_DURATION = 4.0   # cap single-line display duration (seconds)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def apply_transcript_edits(transcript: dict, edits: dict,
                            clip_start: float, clip_end: float) -> tuple:
    """
    Return a deep copy of *transcript* with user edits applied:
      1. wordEdits  — text/timing overrides addressed by ref
      2. mergedGroups — extend the END time of the last word of lineA to lineB's
                        absolute start, replicating the frontend mergedTranscript logic.

    lineSplits affect line *grouping* (not transcript timestamps) and are
    handled separately in group_words_with_splits().

    For multi-segment clips, pass a wordEdits-only edits dict (mergedGroups=[],
    lineSplits=[]) — wordEdits use global refs that are segment-structure-agnostic.
    """
    transcript = deepcopy(transcript)
    if not edits:
        return transcript, 0

    word_edits    = edits.get('wordEdits', [])
    merged_groups = edits.get('mergedGroups', [])
    line_splits   = set(edits.get('lineSplits', []))

    # ── 1. Apply wordEdits ────────────────────────────────────────────────────
    applied = 0
    for edit in word_edits:
        ref = edit.get('ref', {})
        try:
            if ref.get('type') == 'flat':
                w = transcript['word_timestamps'][ref['index']]
            else:
                w = transcript['segments'][ref['segIndex']]['words'][ref['wordIndex']]
            if 'word'  in edit: w['word']  = edit['word']
            if 'start' in edit: w['start'] = edit['start']
            if 'end'   in edit: w['end']   = edit['end']
            applied += 1
        except (KeyError, IndexError, TypeError) as exc:
            print(f"  ✗ wordEdit skipped — ref={ref!r}: {exc}", flush=True)

    # ── 2. Apply mergedGroups ────────────────────────────────────────────────
    if merged_groups:
        raw_words = _collect_clip_words(transcript, clip_start, clip_end)
        lines     = _group_with_splits(raw_words, WORDS_PER_LINE, line_splits)
        for line_idx_a in merged_groups:
            if line_idx_a + 1 >= len(lines):
                continue
            # Absolute start of the first word in lineB
            line_b_abs_start = clip_start + lines[line_idx_a + 1][0]['clip_rel_start']
            # Extend the END of the last word of lineA to that timestamp
            _extend_word_end(transcript, lines[line_idx_a][-1]['ref'], line_b_abs_start)

    return transcript, applied


def group_words_with_splits(words: list, wpl: int, line_splits: set) -> list:
    """
    Split-aware replacement for caption_renderer.group_words_into_lines().

    *words*      — [{word, start, end}] (clip-relative, already duration-capped)
    *wpl*        — words per line (normally MAX_WORDS_PER_LINE = 4)
    *line_splits* — set of rawIndex values where forced line breaks occur

    Returns [{words, line_start, line_end}] with overlap correction applied,
    identical in structure to caption_renderer.group_words_into_lines output.

    NOTE: lineSplits do NOT affect the frontend canvas preview (only the editor
    CaptionPanel display). This function makes exports match the editor panel
    view for split lines; the canvas preview will differ for those lines until
    useCaptions.js is updated separately.
    """
    lines: list  = []
    current: list = []

    for raw_idx, w in enumerate(words):
        current.append(w)
        is_last        = raw_idx == len(words) - 1
        forced_break   = raw_idx in line_splits
        full_line      = len(current) >= wpl

        if forced_break or full_line or is_last:
            if current:
                ls = current[0]['start']
                le = current[-1]['end']
                if le - ls > MAX_LINE_DURATION:
                    le = ls + MAX_LINE_DURATION
                lines.append({'words': current[:], 'line_start': ls, 'line_end': le})
                current = []

    # Fix overlaps between consecutive lines (same as caption_renderer)
    for i in range(len(lines) - 1):
        if lines[i]['line_end'] > lines[i + 1]['line_start']:
            lines[i]['line_end'] = lines[i + 1]['line_start'] - 0.05

    return lines


# ══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ══════════════════════════════════════════════════════════════════════════════

def _collect_clip_words(transcript: dict, clip_start: float, clip_end: float) -> list:
    """
    Return words that fall within [clip_start, clip_end), each decorated with:
      - clip_rel_start: clip-relative start time (mirrors extractWords in useCaptions.js)
      - ref: pointer back to the word's location in the transcript dict

    Boundary operators intentionally match useCaptions.js extractWords:
      w.end > clip_start  AND  w.start < clip_end
    """
    result = []

    if transcript.get('word_timestamps'):
        # Sarvam / flat format
        for idx, w in enumerate(transcript['word_timestamps']):
            if w['end'] > clip_start and w['start'] < clip_end:
                result.append({
                    'clip_rel_start': max(w['start'], clip_start) - clip_start,
                    'ref': {'type': 'flat', 'index': idx},
                })
    else:
        # faster-whisper / nested segments format
        for si, seg in enumerate(transcript.get('segments', [])):
            for wi, w in enumerate(seg.get('words', [])):
                if w['end'] > clip_start and w['start'] < clip_end:
                    result.append({
                        'clip_rel_start': max(w['start'], clip_start) - clip_start,
                        'ref': {'type': 'segment', 'segIndex': si, 'wordIndex': wi},
                    })

    return result


def _group_with_splits(raw_words: list, wpl: int, line_splits_set: set) -> list:
    """
    Group ref-bearing words into lines, respecting forced breaks.
    Mirrors frontend getScriptLines(transcript, clip, wpl, lineSplits).
    Each element of the returned list is a sub-list of raw_word dicts.
    """
    lines: list   = []
    current: list = []

    for raw_idx, word in enumerate(raw_words):
        current.append(word)
        is_last      = raw_idx == len(raw_words) - 1
        forced_break = raw_idx in line_splits_set
        full_line    = len(current) >= wpl

        if forced_break or full_line or is_last:
            if current:
                lines.append(current[:])
                current = []

    return lines


def _extend_word_end(transcript: dict, ref: dict, new_end: float) -> None:
    """Write *new_end* back into the transcript dict at the location given by *ref*."""
    try:
        if ref['type'] == 'flat':
            transcript['word_timestamps'][ref['index']]['end'] = new_end
        else:
            transcript['segments'][ref['segIndex']]['words'][ref['wordIndex']]['end'] = new_end
    except (KeyError, IndexError, TypeError):
        pass
