# -*- coding: utf-8 -*-
"""Caption-sync fix: captions lock to the ENERGY-REFINED cut start, not the
raw CTC clip start.

The cutter trims each clip at refine_boundary()'s output (up to ~0.5s away
from the CTC timestamp), but caption timing used clip["start"] as t=0 — so
every caption fired early by (clip_start - refined_start). The fix threads a
`time_zero` through word extraction and persists the refined boundaries the
cutter actually used into the clips JSON (refined_start / refined_end /
refined_segments).

Contract pins:
- word SELECTION still windows on [clip_start, clip_end] — the filtered word
  array is the index space for lineSplits/wordEdits and must not change;
- timestamps shift by the refined offset only;
- clips JSONs without refined keys behave exactly as before the fix;
- realign_line.output_time_to_absolute stays the exact inverse of the
  forward stacking, refined or not.
"""

import json

import pytest

from services.caption_renderer import (
    get_words_for_clip,
    get_words_for_multisegment_clip,
)
from services.realign_line import output_time_to_absolute


TRANSCRIPT = {
    "word_timestamps": [
        {"word": "దీన్ని",  "start": 10.0, "end": 10.5},
        {"word": "control", "start": 10.5, "end": 11.0},
        {"word": "చూడు",   "start": 11.0, "end": 11.5},
    ]
}


# ── get_words_for_clip: time_zero shifts times, never the word set ──────────

def test_no_time_zero_is_byte_identical_to_pre_fix():
    words = get_words_for_clip(TRANSCRIPT, 10.0, 12.0)
    assert [(w["start"], w["end"]) for w in words] == [
        (0.0, 0.5), (0.5, 1.0), (1.0, 1.5)]


def test_time_zero_shifts_timestamps_only():
    # Cutter refined the start 0.4s earlier than CTC — captions must fire
    # 0.4s LATER on the output file's timeline.
    plain   = get_words_for_clip(TRANSCRIPT, 10.0, 12.0)
    shifted = get_words_for_clip(TRANSCRIPT, 10.0, 12.0, time_zero=9.6)
    assert [w["word"] for w in shifted] == [w["word"] for w in plain]
    assert [(w["start"], w["end"]) for w in shifted] == [
        (0.4, 0.9), (0.9, 1.4), (1.4, 1.9)]


def test_time_zero_does_not_change_word_selection():
    # Even with time_zero far earlier than the window, no extra words appear:
    # selection windows on [clip_start, clip_end], not on time_zero.
    words = get_words_for_clip(TRANSCRIPT, 10.4, 12.0, time_zero=9.0)
    assert [w["word"] for w in words] == ["దీన్ని", "control", "చూడు"]
    # (First word clamps to the window start, then shifts by the offset.)
    assert words[0]["start"] == pytest.approx(1.4)


def test_time_zero_never_produces_negative_times():
    words = get_words_for_clip(TRANSCRIPT, 10.0, 12.0, time_zero=10.2)
    assert all(w["start"] >= 0.0 and w["end"] >= 0.0 for w in words)


# ── multi-segment stacking with refined_segments ────────────────────────────

def _multiseg_fixture():
    transcript = dict(TRANSCRIPT, sentences=[
        {"id": 0, "text": "", "start": 10.0, "end": 11.0},
        {"id": 1, "text": "", "start": 11.0, "end": 11.5},
    ])
    clip = {"start": 10.0, "end": 11.5, "segments": [
        {"start_sent_id": 0, "end_sent_id": 0},
        {"start_sent_id": 1, "end_sent_id": 1},
    ]}
    sent_by_id = {s["id"]: s for s in transcript["sentences"]}
    return transcript, clip, sent_by_id


def test_multiseg_without_refined_matches_pre_fix():
    transcript, clip, sent_by_id = _multiseg_fixture()
    words = get_words_for_multisegment_clip(transcript, clip, sent_by_id)
    assert [(w["start"], w["end"]) for w in words] == [
        (0.0, 0.5), (0.5, 1.0), (1.0, 1.5)]


def test_multiseg_uses_refined_segments_for_zero_and_stacking():
    transcript, clip, sent_by_id = _multiseg_fixture()
    # Cutter trimmed seg 1 to [9.7, 11.1] (1.4s long) and seg 2 to [10.9, 11.6].
    clip["refined_segments"] = [
        {"start": 9.7,  "end": 11.1},
        {"start": 10.9, "end": 11.6},
    ]
    words = get_words_for_multisegment_clip(transcript, clip, sent_by_id)
    # Seg 1 words shift by (10.0 - 9.7) = +0.3; seg 2 stacks at offset 1.4
    # and its word (abs 11.0-11.5) sits at local (11.0-10.9)=(0.1, 0.6).
    assert [(w["start"], w["end"]) for w in words] == [
        (0.3, 0.8), (0.8, 1.3), (1.5, 2.0)]


def test_multiseg_refined_length_mismatch_falls_back():
    transcript, clip, sent_by_id = _multiseg_fixture()
    clip["refined_segments"] = [{"start": 9.7, "end": 11.1}]  # 1 ≠ 2 segments
    words = get_words_for_multisegment_clip(transcript, clip, sent_by_id)
    assert [(w["start"], w["end"]) for w in words] == [
        (0.0, 0.5), (0.5, 1.0), (1.0, 1.5)]


# ── realign inverse mapping stays in lockstep with the forward path ─────────

def test_inverse_single_segment_uses_refined_start():
    clip = {"start": 10.0, "end": 11.5, "refined_start": 9.6}
    assert output_time_to_absolute(0.4, clip, []) == pytest.approx(10.0)


def test_inverse_single_segment_without_refined_unchanged():
    clip = {"start": 10.0, "end": 11.5}
    assert output_time_to_absolute(0.4, clip, []) == pytest.approx(10.4)


def test_inverse_roundtrips_forward_multiseg_stacking():
    transcript, clip, sent_by_id = _multiseg_fixture()
    clip["refined_segments"] = [
        {"start": 9.7,  "end": 11.1},
        {"start": 10.9, "end": 11.6},
    ]
    sentences = transcript["sentences"]
    words = get_words_for_multisegment_clip(transcript, clip, sent_by_id)
    # Every word's output-timeline start maps back to its absolute start.
    absolute = [output_time_to_absolute(w["start"], clip, sentences) for w in words]
    assert absolute == pytest.approx([10.0, 10.5, 11.0])


# ── cutter persists what it actually used ────────────────────────────────────

def test_cut_all_clips_persists_refined_boundaries(tmp_path, monkeypatch):
    from services import video_cutter

    clips_path = tmp_path / "vid_audio_clips.json"
    clips_path.write_text(json.dumps({"clips": [
        {"start": 10.0, "end": 20.0, "duration": 10.0, "why": "t"},
    ]}), encoding="utf-8")
    video_path = str(tmp_path / "vid.mp4")

    def fake_cut(video, start, end, output_path):
        with open(output_path, "wb") as f:
            f.write(b"0")
        return True

    monkeypatch.setattr(video_cutter, "cut_clip", fake_cut)
    monkeypatch.setattr(video_cutter, "find_audio_path", lambda p: None)
    monkeypatch.setattr(video_cutter, "extract_thumbnail", lambda p: None)

    video_cutter.cut_all_clips(str(clips_path), video_path, str(tmp_path / "out"))

    saved = json.loads(clips_path.read_text(encoding="utf-8"))["clips"][0]
    # No audio → fallback padding is the refined boundary the cut used.
    assert saved["refined_start"] == pytest.approx(10.0 - video_cutter.CUT_PRE_ROLL)
    assert saved["refined_end"] == pytest.approx(20.0 + video_cutter.FALLBACK_POST_ROLL)
