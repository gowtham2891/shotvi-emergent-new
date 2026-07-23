# -*- coding: utf-8 -*-
"""Feature #14 — filler/silence removal: keep-span math, the FFmpeg cut
filtergraph, and the caption-remap mirror.

The actual trim/concat render is validated on real media in the manual pass
(both streams shortened to the same duration, in sync).
"""

import pytest

from services.filler_removal import (
    keep_spans,
    build_cut_filtergraph,
    total_removed,
    remap_time_after_cuts,
    apply_cuts_to_words,
)


# ── keep spans (complement of cuts) ─────────────────────────────────────────

def test_keep_spans_complement():
    # cut [1,2] and [4,5] from 6s → keep [0,1],[2,4],[5,6]
    assert keep_spans([[1, 2], [4, 5]], 6.0) == [(0.0, 1.0), (2.0, 4.0), (5.0, 6.0)]


def test_keep_spans_merges_overlaps_and_clamps():
    # overlapping + out-of-range cuts
    assert keep_spans([[1, 3], [2, 4], [10, 20]], 6.0) == [(0.0, 1.0), (4.0, 6.0)]


def test_keep_spans_cut_at_edges():
    assert keep_spans([[0, 1]], 6.0) == [(1.0, 6.0)]
    assert keep_spans([[5, 6]], 6.0) == [(0.0, 5.0)]


def test_total_removed():
    assert total_removed([[1, 2], [4, 5]], 6.0) == 2.0
    assert total_removed([[1, 3], [2, 4]], 6.0) == 3.0  # merged 1-4


# ── FFmpeg filtergraph ──────────────────────────────────────────────────────

def test_filtergraph_trim_concat_shape():
    fg = build_cut_filtergraph([[1, 2], [4, 5]], 6.0)
    # 3 keep segments → 3 trim + 3 atrim + a concat=n=3
    assert fg.count("[0:v]trim=") == 3
    assert fg.count("[0:a]atrim=") == 3
    assert "concat=n=3:v=1:a=1[outv][outa]" in fg
    assert "setpts=PTS-STARTPTS" in fg and "asetpts=PTS-STARTPTS" in fg


def test_filtergraph_none_when_no_cut():
    assert build_cut_filtergraph([], 6.0) is None
    # a cut that removes nothing (full-clip keep)
    assert build_cut_filtergraph([[10, 20]], 6.0) is None


# ── caption remap (mirror of frontend applyCutsToWords) ─────────────────────

def test_remap_time_subtracts_removed_before():
    cuts = [[1, 2], [4, 5]]
    assert remap_time_after_cuts(0.5, cuts) == 0.5   # before any cut
    assert remap_time_after_cuts(3.0, cuts) == 2.0   # 1s removed before
    assert remap_time_after_cuts(5.5, cuts) == 3.5   # 2s removed before


def test_remap_time_inside_a_cut_clamps_to_cut_start():
    # t inside [1,2] → maps to the cut's start on the output timeline (1.0).
    assert remap_time_after_cuts(1.5, [[1, 2]]) == 1.0


def test_apply_cuts_drops_words_in_cuts_and_remaps_survivors():
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "um", "start": 1.2, "end": 1.6},   # inside cut [1,2] → dropped
        {"word": "b", "start": 3.0, "end": 3.5},     # shifts −1s
        {"word": "c", "start": 5.5, "end": 6.0},     # shifts −2s
    ]
    out = apply_cuts_to_words(words, [[1, 2], [4, 5]])
    assert [w["word"] for w in out] == ["a", "b", "c"]
    assert out[0]["start"] == 0.0
    assert out[1]["start"] == 2.0 and out[1]["end"] == 2.5
    assert out[2]["start"] == 3.5 and out[2]["end"] == 4.0


def test_apply_cuts_preserves_other_word_fields():
    words = [{"word": "x", "start": 3.0, "end": 3.5, "emphasis": True}]
    out = apply_cuts_to_words(words, [[1, 2]])
    assert out[0]["emphasis"] is True
    assert out[0]["start"] == 2.0


def test_apply_cuts_no_spans_is_identity():
    words = [{"word": "a", "start": 0.0, "end": 0.5}]
    assert apply_cuts_to_words(words, []) == words
    assert apply_cuts_to_words(words, None) == words
