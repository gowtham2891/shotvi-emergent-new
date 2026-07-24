# -*- coding: utf-8 -*-
"""Feature #30 — Gemini emoji suggestions (clip_selector side).

The fine-cut prompt offers a CURATED emoji menu and asks Gemini to anchor each
emoji to a verbatim word (STEP 3.6). _clean_emoji_suggestions drops anything
outside the palette; map_emoji_to_indices resolves the anchors to clip-local
word indices — the SAME index space emphasis_indices uses — so the frontend can
time each emoji overlay to the caption line holding its anchor word.
"""

import pytest

from services.clip_selector import (
    _clean_emoji_suggestions, map_emoji_to_indices, build_fine_cut_prompt,
)
from services.emoji import EMOJI_PALETTE, palette_prompt_block

# Same fixture shape as test_emphasis.py (the resolver shares
# get_words_for_multisegment_clip).
TRANSCRIPT = {
    "word_timestamps": [
        {"word": "మీరు",     "start": 10.0, "end": 10.4},
        {"word": "ఒక",       "start": 10.4, "end": 10.6},
        {"word": "trap-లో",  "start": 10.6, "end": 11.0},
        {"word": "ఉన్నారు!",  "start": 11.0, "end": 11.5},
        {"word": "ఒక",       "start": 11.5, "end": 11.7},
        {"word": "నిజం",     "start": 11.7, "end": 12.2},
    ],
    "sentences": [{"id": 0, "text": "", "start": 10.0, "end": 12.2}],
}
CLIP = {"start": 10.0, "end": 12.2, "segments": []}


# ── _clean_emoji_suggestions ────────────────────────────────────────────────

def test_clean_keeps_only_palette_emoji():
    raw = [
        {"emoji": "🔥", "word": "trap-లో"},   # palette — kept
        {"emoji": "🦄", "word": "నిజం"},       # NOT palette — dropped
        {"emoji": "💯", "word": "మీరు"},       # palette — kept
    ]
    out = _clean_emoji_suggestions(raw)
    assert out == [{"emoji": "🔥", "word": "trap-లో"}, {"emoji": "💯", "word": "మీరు"}]


def test_clean_drops_empty_or_malformed():
    raw = [
        {"emoji": "🔥", "word": ""},       # no anchor
        {"emoji": "", "word": "నిజం"},      # no emoji
        {"word": "నిజం"},                   # missing emoji key
        "not a dict",
        {"emoji": "💯", "word": "మీరు"},    # valid
    ]
    assert _clean_emoji_suggestions(raw) == [{"emoji": "💯", "word": "మీరు"}]


def test_clean_handles_none_and_caps_at_eight():
    assert _clean_emoji_suggestions(None) == []
    big = [{"emoji": "🔥", "word": f"w{i}"} for i in range(20)]
    assert len(_clean_emoji_suggestions(big)) == 8


# ── map_emoji_to_indices ────────────────────────────────────────────────────

def test_resolves_anchor_words_to_clip_local_indices():
    clip = dict(CLIP, emoji_suggestions=[
        {"emoji": "🔥", "word": "trap-లో"},
        {"emoji": "💯", "word": "నిజం"},
    ])
    assert map_emoji_to_indices(clip, TRANSCRIPT) == [
        {"emoji": "🔥", "word_index": 2},
        {"emoji": "💯", "word_index": 5},
    ]


def test_resolution_ignores_case_and_punctuation():
    clip = dict(CLIP, emoji_suggestions=[{"emoji": "🔥", "word": "TRAP-లో"},
                                         {"emoji": "✅", "word": "ఉన్నారు"}])
    assert map_emoji_to_indices(clip, TRANSCRIPT) == [
        {"emoji": "🔥", "word_index": 2},
        {"emoji": "✅", "word_index": 3},
    ]


def test_duplicate_anchor_takes_first_unused_and_returns_sorted():
    clip = dict(CLIP, emoji_suggestions=[{"emoji": "🔥", "word": "ఒక"},
                                         {"emoji": "💯", "word": "ఒక"}])
    # "ఒక" at indices 1 and 4 → two emoji, one each, sorted by index.
    assert map_emoji_to_indices(clip, TRANSCRIPT) == [
        {"emoji": "🔥", "word_index": 1},
        {"emoji": "💯", "word_index": 4},
    ]


def test_unmatched_anchor_drops_silently():
    clip = dict(CLIP, emoji_suggestions=[{"emoji": "🔥", "word": "పరమపదం"},
                                         {"emoji": "💯", "word": "నిజం"}])
    assert map_emoji_to_indices(clip, TRANSCRIPT) == [{"emoji": "💯", "word_index": 5}]


def test_no_suggestions_is_empty():
    assert map_emoji_to_indices(dict(CLIP), TRANSCRIPT) == []
    assert map_emoji_to_indices(dict(CLIP, emoji_suggestions=[]), TRANSCRIPT) == []


# ── prompt integration ──────────────────────────────────────────────────────

def test_prompt_includes_the_emoji_menu_and_schema_field():
    sentences = [{"id": 0, "text": "hello", "start": 0.0, "end": 1.0}]
    sent_by_id = {0: sentences[0]}
    candidates = [{"start_sent_id": 0, "end_sent_id": 0, "why": "", "visual_energy": ""}]
    prompt = build_fine_cut_prompt(candidates, sentences, sent_by_id, video_id="vid")
    # STEP 3.6 present, the full curated menu injected, schema field requested.
    assert "STEP 3.6" in prompt
    assert "emoji_suggestions" in prompt
    for ch, _ in EMOJI_PALETTE:
        assert ch in prompt
    # f-string fully rendered — no leftover placeholder.
    assert "{emoji_menu}" not in prompt
    assert palette_prompt_block() in prompt
