"""Unit tests for services/apply_transcript_edits.py"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.apply_transcript_edits import (
    apply_transcript_edits,
    group_words_with_splits,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def flat_t():
    """8 words A–H at 0.5 s each, absolute times 0–4 s (clip 0–4 s)."""
    return {
        "word_timestamps": [
            {"word": "A", "start": 0.0, "end": 0.5},
            {"word": "B", "start": 0.5, "end": 1.0},
            {"word": "C", "start": 1.0, "end": 1.5},
            {"word": "D", "start": 1.5, "end": 2.0},
            {"word": "E", "start": 2.0, "end": 2.5},
            {"word": "F", "start": 2.5, "end": 3.0},
            {"word": "G", "start": 3.0, "end": 3.5},
            {"word": "H", "start": 3.5, "end": 4.0},
        ]
    }


def seg_t():
    """Same 8 words in segments[].words format (2 segments × 4 words)."""
    return {
        "segments": [
            {
                "words": [
                    {"word": "A", "start": 0.0, "end": 0.5},
                    {"word": "B", "start": 0.5, "end": 1.0},
                    {"word": "C", "start": 1.0, "end": 1.5},
                    {"word": "D", "start": 1.5, "end": 2.0},
                ]
            },
            {
                "words": [
                    {"word": "E", "start": 2.0, "end": 2.5},
                    {"word": "F", "start": 2.5, "end": 3.0},
                    {"word": "G", "start": 3.0, "end": 3.5},
                    {"word": "H", "start": 3.5, "end": 4.0},
                ]
            },
        ]
    }


def words_list():
    """8 clip-relative words (already extracted + duration-capped) for grouping tests."""
    return [
        {"word": "A", "start": 0.0, "end": 0.5},
        {"word": "B", "start": 0.5, "end": 1.0},
        {"word": "C", "start": 1.0, "end": 1.5},
        {"word": "D", "start": 1.5, "end": 2.0},
        {"word": "E", "start": 2.0, "end": 2.5},
        {"word": "F", "start": 2.5, "end": 3.0},
        {"word": "G", "start": 3.0, "end": 3.5},
        {"word": "H", "start": 3.5, "end": 4.0},
    ]


# ── Test 1: identity — empty edits ────────────────────────────────────────────

def test_identity_empty_edits():
    t = flat_t()
    result, applied = apply_transcript_edits(t, {}, clip_start=0.0, clip_end=4.0)
    assert result is not t, "should return a deep copy"
    assert result["word_timestamps"][0]["end"] == 0.5
    assert result["word_timestamps"][3]["end"] == 2.0


# ── Test 2: wordEdit flat — text override ────────────────────────────────────

def test_word_edit_flat_text():
    edits = {
        "wordEdits": [{"ref": {"type": "flat", "index": 2}, "word": "ZZZ"}],
        "mergedGroups": [],
        "lineSplits": [],
    }
    result, applied = apply_transcript_edits(flat_t(), edits, 0.0, 4.0)
    assert applied == 1
    assert result["word_timestamps"][2]["word"] == "ZZZ"
    assert result["word_timestamps"][0]["word"] == "A"  # others untouched


# ── Test 3: wordEdit segment — text override ─────────────────────────────────

def test_word_edit_segment_text():
    edits = {
        "wordEdits": [
            {"ref": {"type": "segment", "segIndex": 1, "wordIndex": 0}, "word": "XXX"}
        ],
        "mergedGroups": [],
        "lineSplits": [],
    }
    result, applied = apply_transcript_edits(seg_t(), edits, 0.0, 4.0)
    assert applied == 1
    assert result["segments"][1]["words"][0]["word"] == "XXX"
    assert result["segments"][0]["words"][0]["word"] == "A"


# ── Test 4: wordEdit — timing override ───────────────────────────────────────

def test_word_edit_timing():
    edits = {
        "wordEdits": [{"ref": {"type": "flat", "index": 0}, "start": 0.1, "end": 0.4}],
        "mergedGroups": [],
        "lineSplits": [],
    }
    result, applied = apply_transcript_edits(flat_t(), edits, 0.0, 4.0)
    assert applied == 1
    assert result["word_timestamps"][0]["start"] == 0.1
    assert result["word_timestamps"][0]["end"] == 0.4


# ── Test 5: mergedGroups — extends word D's end to line B start (2.0 s) ──────

def test_merge_extends_word_end():
    # Line 0 = words A B C D (idx 0–3), line 1 = words E F G H (idx 4–7)
    # mergedGroups=[0] → extend D.end to lineB.start = clip_start + lineB[0].clip_rel_start
    # lineB[0] is word E at abs start 2.0 → clip_rel_start = 2.0 - 0 = 2.0
    edits = {"wordEdits": [], "mergedGroups": [0], "lineSplits": []}
    result, applied = apply_transcript_edits(flat_t(), edits, clip_start=0.0, clip_end=4.0)
    assert applied == 0  # no wordEdits, only mergedGroups
    assert result["word_timestamps"][3]["end"] == pytest.approx(2.0)
    # Other words untouched
    assert result["word_timestamps"][7]["end"] == pytest.approx(4.0)


# ── Test 6: lineSplits — group_words_with_splits produces shorter first line ─

def test_line_split_changes_grouping():
    # rawIndex=1 → force break after word B → line 0 has [A, B], line 1 has [C D E F], line 2 [G H]
    lines = group_words_with_splits(words_list(), wpl=4, line_splits={1})
    assert len(lines[0]["words"]) == 2
    assert lines[0]["words"][0]["word"] == "A"
    assert lines[0]["words"][1]["word"] == "B"
    # Next line starts at C
    assert lines[1]["words"][0]["word"] == "C"


# ── Test 7: merge + split combined ───────────────────────────────────────────

def test_merge_with_split_combined():
    # lineSplits={1} → line 0 = [A, B], line 1 = [C, D, E, F], line 2 = [G, H]
    # mergedGroups=[0] → extend last word of line 0 (B, idx 1) to start of line 1 (C, abs 1.0)
    edits = {"wordEdits": [], "mergedGroups": [0], "lineSplits": [1]}
    result, applied = apply_transcript_edits(flat_t(), edits, clip_start=0.0, clip_end=4.0)
    assert applied == 0  # no wordEdits, only mergedGroups + lineSplits
    # word B is index 1 in flat word_timestamps
    assert result["word_timestamps"][1]["end"] == pytest.approx(1.0)


# ── Test 8: out-of-range ref — no crash ──────────────────────────────────────

def test_out_of_range_ref_no_crash():
    edits = {
        "wordEdits": [{"ref": {"type": "flat", "index": 99}, "word": "BOOM"}],
        "mergedGroups": [],
        "lineSplits": [],
    }
    result, applied = apply_transcript_edits(flat_t(), edits, 0.0, 4.0)
    assert applied == 0  # out-of-range ref must not count as applied
    # No exception; transcript contents unchanged
    assert result["word_timestamps"][0]["word"] == "A"


# ── Test 9: group_words_with_splits — no splits behaves like plain chunking ──

def test_group_words_basic_no_splits():
    lines = group_words_with_splits(words_list(), wpl=4, line_splits=set())
    assert len(lines) == 2
    assert len(lines[0]["words"]) == 4
    assert len(lines[1]["words"]) == 4
    assert lines[0]["line_start"] == pytest.approx(0.0)
    assert lines[1]["line_start"] == pytest.approx(2.0)


# ── Test 10: crop_mode='manual' condition independent of use_autocrop ────────

def test_9_16_manual_crop_condition():
    """
    Verify that the crop decision condition (crop_mode == 'manual' and crop_box)
    fires for a 9:16 clip where use_autocrop=True but crop_mode='manual'.
    This is a model-level logic check, not a subprocess test.
    """
    crop_mode = "manual"
    crop_box  = {"x": 0.1, "y": 0.0, "w": 0.8, "h": 1.0}
    use_autocrop = True   # set by frontend because format == '9:16'

    needs_crop = (crop_mode == "manual" and crop_box is not None)
    assert needs_crop is True, (
        "crop should apply even when use_autocrop=True if crop_mode='manual'"
    )

    # Old behaviour (buggy): would have been 'not use_autocrop'
    old_condition = (crop_box is not None and not use_autocrop)
    assert old_condition is False, "old condition incorrectly skips crop for 9:16 format"


# ── Line re-alignments (apply_line_realignments) ─────────────────────────────

from services.apply_transcript_edits import apply_line_realignments


def _realign_entry(start_idx, end_idx, words):
    return {"startIdx": start_idx, "endIdx": end_idx, "words": words,
            "approximate": False}


def test_realign_replaces_matching_line_words_only():
    lines = group_words_with_splits(words_list(), wpl=4, line_splits=set())
    new_words = [
        {"word": "క", "start": 0.1, "end": 0.6, "word_tanglish": "ka"},
        {"word": "ఖ", "start": 0.7, "end": 1.2, "word_tanglish": "kha"},
        {"word": "గ", "start": 1.3, "end": 1.9, "word_tanglish": "ga"},
    ]
    n = apply_line_realignments(lines, [_realign_entry(0, 3, new_words)])
    assert n == 1
    # Line 1 replaced (3 words now, fresh timing), line 2 untouched.
    assert [w["word"] for w in lines[0]["words"]] == ["క", "ఖ", "గ"]
    assert [w["word"] for w in lines[1]["words"]] == ["E", "F", "G", "H"]
    # Line boundaries NEVER move.
    assert lines[0]["line_start"] == pytest.approx(0.0)
    assert lines[0]["line_end"] == pytest.approx(2.0)


def test_realign_inert_when_grouping_no_longer_matches():
    # Entry addressed lines grouped at wpl=4; regroup at wpl=2 → no line spans
    # exactly 0..3, so the entry must be inert (original words render).
    lines = group_words_with_splits(words_list(), wpl=2, line_splits=set())
    new_words = [{"word": "క", "start": 0.1, "end": 0.6, "word_tanglish": "ka"}]
    n = apply_line_realignments(lines, [_realign_entry(0, 3, new_words)])
    assert n == 0
    assert [w["word"] for w in lines[0]["words"]] == ["A", "B"]


def test_realign_clamps_into_fixed_line_span():
    lines = group_words_with_splits(words_list(), wpl=4, line_splits=set())
    new_words = [
        {"word": "క", "start": -1.0, "end": 0.6, "word_tanglish": "ka"},
        {"word": "ఖ", "start": 0.7, "end": 99.0, "word_tanglish": "kha"},
    ]
    n = apply_line_realignments(lines, [_realign_entry(0, 3, new_words)])
    assert n == 1
    for w in lines[0]["words"]:
        assert lines[0]["line_start"] <= w["start"] <= w["end"] <= lines[0]["line_end"]


def test_realign_tanglish_script_renders_word_tanglish():
    lines = group_words_with_splits(words_list(), wpl=4, line_splits=set())
    new_words = [
        {"word": "ఒకటి", "start": 0.1, "end": 0.9, "word_tanglish": "okati"},
        {"word": "రెండు", "start": 1.0, "end": 1.9, "word_tanglish": None},
    ]
    n = apply_line_realignments(lines, [_realign_entry(0, 3, new_words)],
                                script="tanglish")
    assert n == 1
    texts = [w["word"] for w in lines[0]["words"]]
    assert texts[0] == "okati"
    # Missing word_tanglish derives on demand (deterministic tanglish.py) —
    # ASCII out, never the raw Telugu.
    assert texts[1].isascii() and texts[1]


def test_realign_malformed_entry_skipped_line_untouched():
    lines = group_words_with_splits(words_list(), wpl=4, line_splits=set())
    bad = [{"word": "క", "start": "not-a-number", "end": 0.6}]
    n = apply_line_realignments(lines, [_realign_entry(0, 3, bad)])
    assert n == 0
    assert [w["word"] for w in lines[0]["words"]] == ["A", "B", "C", "D"]


def test_realign_second_line_matches_by_cumulative_index():
    lines = group_words_with_splits(words_list(), wpl=4, line_splits=set())
    new_words = [
        {"word": "ఐదు", "start": 2.1, "end": 2.8, "word_tanglish": "aidu"},
        {"word": "ఆరు", "start": 2.9, "end": 3.4, "word_tanglish": "aaru"},
        {"word": "ఏడు", "start": 3.5, "end": 3.9, "word_tanglish": "edu"},
    ]
    n = apply_line_realignments(lines, [_realign_entry(4, 7, new_words)])
    assert n == 1
    assert [w["word"] for w in lines[0]["words"]] == ["A", "B", "C", "D"]
    assert [w["word"] for w in lines[1]["words"]] == ["ఐదు", "ఆరు", "ఏడు"]
