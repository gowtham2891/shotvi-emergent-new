# -*- coding: utf-8 -*-
"""Tanglish caption render path (caption_script='tanglish').

Pins the WYSIWYG-both-ways contract: a tanglish burn differs from the telugu
burn ONLY in caption text — same word windows, same timing, same ASS style
header (font, size, k-calibrated metrics), same \\an5\\pos on every event.
Also covers the on-demand derivation fallback for old transcripts and the
edit seam (a word edit re-derives its tanglish before the burn).
"""

import pytest

from services.caption_renderer import (
    get_words_for_clip,
    get_words_for_multisegment_clip,
    group_words_into_lines,
    generate_ass_karaoke,
)
from services.apply_transcript_edits import apply_transcript_edits


TRANSCRIPT = {
    "word_timestamps": [
        {"word": "దీన్ని",  "word_tanglish": "deenni",  "start": 0.0, "end": 0.5},
        {"word": "control", "word_tanglish": "control", "start": 0.5, "end": 1.0},
        {"word": "చూడు",   "word_tanglish": "choodu",  "start": 1.0, "end": 1.5},
    ]
}

# Same words but saved before the toggle existed — no word_tanglish anywhere.
OLD_TRANSCRIPT = {
    "word_timestamps": [
        {"word": w["word"], "start": w["start"], "end": w["end"]}
        for w in TRANSCRIPT["word_timestamps"]
    ]
}


def test_telugu_is_the_default_and_unchanged():
    words = get_words_for_clip(TRANSCRIPT, 0.0, 2.0)
    assert [w["word"] for w in words] == ["దీన్ని", "control", "చూడు"]


def test_tanglish_renders_stored_word_tanglish():
    words = get_words_for_clip(TRANSCRIPT, 0.0, 2.0, script="tanglish")
    assert [w["word"] for w in words] == ["deenni", "control", "choodu"]


def test_old_transcript_derives_tanglish_on_demand():
    words = get_words_for_clip(OLD_TRANSCRIPT, 0.0, 2.0, script="tanglish")
    assert [w["word"] for w in words] == ["deenni", "control", "choodu"]


def test_timing_identical_in_both_scripts():
    telugu   = get_words_for_clip(TRANSCRIPT, 0.0, 2.0, script="telugu")
    tanglish = get_words_for_clip(TRANSCRIPT, 0.0, 2.0, script="tanglish")
    assert [(w["start"], w["end"]) for w in telugu] == \
           [(w["start"], w["end"]) for w in tanglish]


def test_multisegment_passes_script_through():
    transcript = dict(TRANSCRIPT, sentences=[
        {"id": 0, "text": "", "start": 0.0, "end": 1.0},
        {"id": 1, "text": "", "start": 1.0, "end": 1.5},
    ])
    clip = {"start": 0.0, "end": 1.5, "segments": [
        {"start_sent_id": 0, "end_sent_id": 0},
        {"start_sent_id": 1, "end_sent_id": 1},
    ]}
    sent_by_id = {s["id"]: s for s in transcript["sentences"]}
    words = get_words_for_multisegment_clip(transcript, clip, sent_by_id, script="tanglish")
    assert [w["word"] for w in words] == ["deenni", "control", "choodu"]


def test_word_edit_rederives_tanglish():
    edits = {"wordEdits": [{"ref": {"type": "flat", "index": 0}, "word": "శక్తి"}],
             "mergedGroups": [], "lineSplits": []}
    edited, applied = apply_transcript_edits(TRANSCRIPT, edits, 0.0, 2.0)
    assert applied == 1
    w = edited["word_timestamps"][0]
    assert w["word"] == "శక్తి"
    assert w["word_tanglish"] == "shakti"   # never stale "deenni"
    # source dict untouched (apply works on a deep copy)
    assert TRANSCRIPT["word_timestamps"][0]["word_tanglish"] == "deenni"


def test_word_edit_uses_wire_tanglish_verbatim():
    # The user typed "shakthi" in Tanglish view; it rides the wire as
    # word_tanglish and must render VERBATIM — not the deterministic "shakti"
    # that telugu_to_tanglish would derive (proving the override, not a match).
    edits = {"wordEdits": [{"ref": {"type": "flat", "index": 0},
                            "word": "శక్తి", "word_tanglish": "shakthi"}],
             "mergedGroups": [], "lineSplits": []}
    edited, applied = apply_transcript_edits(TRANSCRIPT, edits, 0.0, 2.0)
    assert applied == 1
    w = edited["word_timestamps"][0]
    assert w["word"] == "శక్తి"                 # Telugu remains the source of truth
    assert w["word_tanglish"] == "shakthi"      # verbatim, NOT derived "shakti"
    tanglish = get_words_for_clip(edited, 0.0, 2.0, script="tanglish")
    assert tanglish[0]["word"] == "shakthi"


def test_word_edit_without_wire_tanglish_falls_back_to_derivation():
    # No word_tanglish on the wire → deterministic derivation, exactly as before.
    edits = {"wordEdits": [{"ref": {"type": "flat", "index": 0}, "word": "శక్తి"}],
             "mergedGroups": [], "lineSplits": []}
    edited, _ = apply_transcript_edits(TRANSCRIPT, edits, 0.0, 2.0)
    assert edited["word_timestamps"][0]["word_tanglish"] == "shakti"


def _telugu_ass_with_edit(edit):
    edits = {"wordEdits": [edit], "mergedGroups": [], "lineSplits": []}
    edited, _ = apply_transcript_edits(TRANSCRIPT, edits, 0.0, 2.0)
    words = get_words_for_clip(edited, 0.0, 2.0, script="telugu")
    lines = group_words_into_lines(words)
    return generate_ass_karaoke(lines, "bold-yellow")


def test_telugu_burn_byte_identical_regardless_of_carried_tanglish():
    # A telugu burn never reads word_tanglish, so a text_tanglish-carrying edit
    # must produce byte-identical ASS to the same edit without it.
    base = {"ref": {"type": "flat", "index": 0}, "word": "శక్తి"}
    without = _telugu_ass_with_edit(base)
    with_tanglish = _telugu_ass_with_edit({**base, "word_tanglish": "SHAKTHI-typed"})
    assert without == with_tanglish


def _ass_for(script):
    words = get_words_for_clip(TRANSCRIPT, 0.0, 2.0, script=script)
    lines = group_words_into_lines(words)
    return generate_ass_karaoke(lines, "bold-yellow")


def test_ass_differs_only_in_caption_text():
    telugu, tanglish = _ass_for("telugu"), _ass_for("tanglish")

    t_head, t_events = telugu.split("[Events]"), None
    g_head, g_events = tanglish.split("[Events]"), None
    # Identical style header: same font, size, colors, k-calibrated metrics.
    assert t_head[0] == g_head[0]

    t_lines = [l for l in telugu.splitlines() if l.startswith("Dialogue:")]
    g_lines = [l for l in tanglish.splitlines() if l.startswith("Dialogue:")]
    assert len(t_lines) == len(g_lines) > 0

    for t, g in zip(t_lines, g_lines):
        # Everything up to the Text field (timing, style, margins) matches.
        t_meta, t_text = t.split(",,", 1)
        g_meta, g_text = g.split(",,", 1)
        assert t_meta == g_meta
        # Both carry the same \an5\pos prefix on every event.
        assert t_text.split("}")[0] == g_text.split("}")[0]
        assert "\\an5\\pos" in t_text
        # And the tanglish text is pure ASCII (Latin glyphs, same fonts).
        payload = g_text.split("}", 1)[1] if "}" in g_text else g_text
        assert all(ord(c) < 128 for c in payload), payload
