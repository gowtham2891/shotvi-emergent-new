# -*- coding: utf-8 -*-
"""Feature #6 — keyword emphasis.

Gemini's fine-cut pass tags 2-6 punch words per clip (emphasis_words,
verbatim strings); map_emphasis_to_indices resolves them to indices into the
clip's FILTERED word array (the lineSplits index space, built by the same
caption_renderer code that renders). The burn wraps emphasized words in
persistent ASS override tags (highlight colour + bold + 112% scale); a line
with NO emphasis renders byte-identical to the pre-feature output.
"""

import pytest

from services.clip_selector import map_emphasis_to_indices
from services.caption_renderer import (
    generate_ass_karaoke,
    get_words_for_clip,
    group_words_into_lines,
    STYLES,
    _color_tag,
)


TRANSCRIPT = {
    "word_timestamps": [
        {"word": "మీరు",     "start": 10.0, "end": 10.4},
        {"word": "ఒక",       "start": 10.4, "end": 10.6},
        {"word": "trap-లో",  "start": 10.6, "end": 11.0},
        {"word": "ఉన్నారు!",  "start": 11.0, "end": 11.5},
        {"word": "ఒక",       "start": 11.5, "end": 11.7},
        {"word": "నిజం",     "start": 11.7, "end": 12.2},
    ],
    "sentences": [
        {"id": 0, "text": "", "start": 10.0, "end": 12.2},
    ],
}
CLIP = {"start": 10.0, "end": 12.2, "segments": []}


# ── map_emphasis_to_indices ─────────────────────────────────────────────────

def test_maps_exact_words_to_clip_local_indices():
    clip = dict(CLIP, emphasis_words=["trap-లో", "నిజం"])
    assert map_emphasis_to_indices(clip, TRANSCRIPT) == [2, 5]


def test_matching_ignores_punctuation_and_case():
    clip = dict(CLIP, emphasis_words=["ఉన్నారు", "TRAP-లో"])
    assert map_emphasis_to_indices(clip, TRANSCRIPT) == [2, 3]


def test_duplicate_words_take_first_unused_occurrence():
    # "ఒక" appears at indices 1 and 4 — two mentions map to both, in order.
    clip = dict(CLIP, emphasis_words=["ఒక", "ఒక"])
    assert map_emphasis_to_indices(clip, TRANSCRIPT) == [1, 4]


def test_unmatched_words_drop_silently():
    clip = dict(CLIP, emphasis_words=["పరమపదం", "నిజం"])
    assert map_emphasis_to_indices(clip, TRANSCRIPT) == [5]


def test_no_emphasis_words_is_empty():
    assert map_emphasis_to_indices(dict(CLIP), TRANSCRIPT) == []
    assert map_emphasis_to_indices(dict(CLIP, emphasis_words=[]), TRANSCRIPT) == []


def test_multiword_phrase_maps_each_token():
    clip = dict(CLIP, emphasis_words=["మీరు ఒక"])
    assert map_emphasis_to_indices(clip, TRANSCRIPT) == [0, 1]


# ── ASS override tags ────────────────────────────────────────────────────────

def _lines_with_emphasis(indices):
    words = get_words_for_clip(TRANSCRIPT, 10.0, 12.2)
    for i in indices:
        words[i]["emphasis"] = True
    return group_words_into_lines(words)


def test_no_emphasis_is_byte_identical_to_pre_feature():
    plain = generate_ass_karaoke(_lines_with_emphasis([]), "bold-yellow")
    # No scale/bold override tags anywhere.
    assert "\\fscx112" not in plain
    assert "\\b1" not in plain
    assert "\\fscx100" not in plain


def test_emphasized_word_gets_persistent_highlight_bold_scale():
    ass = generate_ass_karaoke(_lines_with_emphasis([2]), "bold-yellow")
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert dialogue, "no events generated"
    highlight_tag = _color_tag(STYLES["bold-yellow"]["color_highlight"])
    for line in dialogue:
        if "trap-లో" not in line:
            continue
        # The emphasized word carries highlight colour + bold + 112% scale
        # in EVERY event of its line (persistent, not karaoke-transient).
        seg = line.split("trap-లో")[0].rsplit("{", 1)[1]
        assert "\\b1" in seg and "\\fscx112" in seg and "\\fscy112" in seg
        assert highlight_tag in seg


def test_non_emphasized_words_reset_bold_and_scale_in_emphasis_lines():
    ass = generate_ass_karaoke(_lines_with_emphasis([2]), "bold-yellow")
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue:") and "trap-లో" in l]
    line = dialogue[0]
    # The word after the emphasized one must explicitly reset scale, or the
    # 112% would leak (ASS overrides persist until changed).
    after = line.split("trap-లో", 1)[1]
    assert "\\fscx100" in after and "\\fscy100" in after


def test_emphasis_free_lines_in_same_render_have_no_reset_tags():
    # Only the line CONTAINING emphasis pays the reset-tag cost; with 4 words
    # per line, words 0-3 are line 1 and words 4-5 are line 2 — emphasizing a
    # line-1 word leaves line-2 events untouched.
    ass = generate_ass_karaoke(_lines_with_emphasis([2]), "bold-yellow")
    line2_events = [l for l in ass.splitlines()
                    if l.startswith("Dialogue:") and "నిజం" in l and "trap-లో" not in l]
    assert line2_events, "expected separate line-2 events"
    for l in line2_events:
        assert "\\fscx" not in l and "\\b1" not in l
