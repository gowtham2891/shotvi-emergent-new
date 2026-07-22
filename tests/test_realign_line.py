"""
Line-level re-alignment gates (services/realign_line.py + POST /realign-line).

Pins the contract line editing depends on:
  - even_distribution: deterministic monotonic fallback timing
  - realign_line_words: NEVER loses the user's text — aligner failure,
    missing audio, or implausible output all degrade to the fallback with
    approximate=True; plausible alignments come back clamped into the FIXED
    line span
  - output_time_to_absolute: single-segment offset + multi-segment reverse map
  - the endpoint: 404/422 on genuinely broken requests, 200 + fallback on
    alignment trouble, word_tanglish always populated

The aligner itself is monkeypatched at the module seam (_run_aligner) so no
torch/model weights are needed here.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.realign_line import (  # noqa: E402
    even_distribution,
    realign_line_words,
    output_time_to_absolute,
    _plausible,
    MIN_WORD_DURATION,
)


# ══════════════════════════════════════════════════════════════
# even_distribution
# ══════════════════════════════════════════════════════════════

def test_even_distribution_splits_span_exactly():
    out = even_distribution(["ఒకటి", "రెండు", "మూడు"], 2.0, 5.0)
    assert [w["word"] for w in out] == ["ఒకటి", "రెండు", "మూడు"]
    assert out[0]["start"] == 2.0
    assert out[-1]["end"] == 5.0
    # contiguous + monotonic
    for a, b in zip(out, out[1:]):
        assert a["end"] == b["start"]
        assert b["end"] > b["start"]


def test_even_distribution_empty_words():
    assert even_distribution([], 0.0, 4.0) == []


# ══════════════════════════════════════════════════════════════
# plausibility gate
# ══════════════════════════════════════════════════════════════

WORDS3 = ["ఒకటి", "రెండు", "మూడు"]


def test_plausible_accepts_clean_alignment():
    aligned = [
        {"word": "okati", "start": 0.1, "end": 0.6},
        {"word": "rendu", "start": 0.7, "end": 1.2},
        {"word": "moodu", "start": 1.3, "end": 1.9},
    ]
    assert _plausible(aligned, WORDS3, span=2.0)


def test_plausible_rejects_count_mismatch():
    aligned = [{"word": "okati", "start": 0.1, "end": 0.6}]
    assert not _plausible(aligned, WORDS3, span=2.0)


def test_plausible_rejects_zero_length_words():
    aligned = [
        {"word": "okati", "start": 0.1, "end": 0.1},  # zero-length
        {"word": "rendu", "start": 0.7, "end": 1.2},
        {"word": "moodu", "start": 1.3, "end": 1.9},
    ]
    assert not _plausible(aligned, WORDS3, span=2.0)


def test_plausible_rejects_non_monotonic_starts():
    aligned = [
        {"word": "okati", "start": 1.0, "end": 1.5},
        {"word": "rendu", "start": 0.2, "end": 0.8},  # goes backwards
        {"word": "moodu", "start": 1.6, "end": 1.9},
    ]
    assert not _plausible(aligned, WORDS3, span=2.0)


def test_plausible_rejects_out_of_span_times():
    aligned = [
        {"word": "okati", "start": 0.1, "end": 0.6},
        {"word": "rendu", "start": 0.7, "end": 1.2},
        {"word": "moodu", "start": 5.0, "end": 6.0},  # way past span
    ]
    assert not _plausible(aligned, WORDS3, span=2.0)


# ══════════════════════════════════════════════════════════════
# realign_line_words — fallback + happy path
# ══════════════════════════════════════════════════════════════

def test_missing_audio_falls_back_even(tmp_path):
    out, approx = realign_line_words(
        tmp_path / "nope.wav", 10.0, 13.0, 4.0, 7.0, WORDS3
    )
    assert approx is True
    assert out == even_distribution(WORDS3, 4.0, 7.0)


def test_aligner_exception_falls_back_even(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    import services.realign_line as rl

    def boom(*a, **k):
        raise RuntimeError("no cuda for you")

    monkeypatch.setattr(rl, "_run_aligner", boom)
    out, approx = realign_line_words(audio, 10.0, 13.0, 4.0, 7.0, WORDS3)
    assert approx is True
    assert out == even_distribution(WORDS3, 4.0, 7.0)


def test_implausible_alignment_falls_back_even(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    import services.realign_line as rl

    # Wrong token count — the aligner dropped a word.
    monkeypatch.setattr(
        rl, "_run_aligner",
        lambda *a, **k: [{"word": "okati", "start": 0.0, "end": 3.0}],
    )
    out, approx = realign_line_words(audio, 10.0, 13.0, 4.0, 7.0, WORDS3)
    assert approx is True
    assert out == even_distribution(WORDS3, 4.0, 7.0)


def test_good_alignment_offsets_into_clip_time_and_keeps_user_text(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    import services.realign_line as rl

    # Aligner speaks romanized tokens with SPAN-relative times.
    monkeypatch.setattr(
        rl, "_run_aligner",
        lambda *a, **k: [
            {"word": "okati", "start": 0.10, "end": 0.90},
            {"word": "rendu", "start": 1.00, "end": 1.80},
            {"word": "moodu", "start": 2.00, "end": 2.85},
        ],
    )
    out, approx = realign_line_words(audio, 10.0, 13.0, 4.0, 7.0, WORDS3)
    assert approx is False
    # User's TELUGU text is authoritative — never the aligner's romanization.
    assert [w["word"] for w in out] == WORDS3
    # Span-relative → clip-relative (line_start = 4.0 offset).
    assert out[0]["start"] == pytest.approx(4.10)
    assert out[-1]["end"] == pytest.approx(6.85)
    # Everything inside the FIXED span.
    for w in out:
        assert 4.0 <= w["start"] <= w["end"] <= 7.0


def test_alignment_clamped_to_fixed_span(tmp_path, monkeypatch):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    import services.realign_line as rl

    # Slight overshoot within SPAN_SLACK: plausible, but must clamp.
    monkeypatch.setattr(
        rl, "_run_aligner",
        lambda *a, **k: [
            {"word": "okati", "start": -0.10, "end": 0.90},
            {"word": "rendu", "start": 1.00, "end": 1.80},
            {"word": "moodu", "start": 2.00, "end": 3.15},
        ],
    )
    out, approx = realign_line_words(audio, 10.0, 13.0, 4.0, 7.0, WORDS3)
    assert approx is False
    assert out[0]["start"] >= 4.0
    assert out[-1]["end"] <= 7.0
    for w in out:
        assert w["end"] - w["start"] >= MIN_WORD_DURATION or w["end"] == 7.0


def test_empty_words_falls_back_empty(tmp_path):
    out, approx = realign_line_words(tmp_path / "nope.wav", 0, 1, 0, 1, [])
    assert out == []
    assert approx is True


# ══════════════════════════════════════════════════════════════
# output_time_to_absolute
# ══════════════════════════════════════════════════════════════

def test_single_segment_is_clip_start_offset():
    clip = {"start": 120.5, "end": 150.0, "segments": []}
    assert output_time_to_absolute(3.25, clip, []) == pytest.approx(123.75)


def test_multi_segment_reverse_maps_across_the_cut():
    # Two kept segments: [10, 14] and [20, 26] — 4s then 6s of output.
    sentences = [
        {"id": 0, "start": 10.0, "end": 14.0},
        {"id": 1, "start": 14.0, "end": 20.0},
        {"id": 2, "start": 20.0, "end": 26.0},
    ]
    clip = {
        "start": 10.0, "end": 26.0,
        "segments": [
            {"start_sent_id": 0, "end_sent_id": 0},
            {"start_sent_id": 2, "end_sent_id": 2},
        ],
    }
    # Inside the first segment
    assert output_time_to_absolute(2.0, clip, sentences) == pytest.approx(12.0)
    # Inside the second segment (output 5.0 = 1.0s into segment two)
    assert output_time_to_absolute(5.0, clip, sentences) == pytest.approx(21.0)
    # Past the end clamps to the last segment's end
    assert output_time_to_absolute(99.0, clip, sentences) == pytest.approx(26.0)


# ══════════════════════════════════════════════════════════════
# POST /realign-line endpoint
# ══════════════════════════════════════════════════════════════

@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from api import main as api_main
    from api.auth import AuthUser, get_current_user

    jobs = {
        "job-1": {"job_id": "job-1", "video_id": "vidX",
                  "clips": [{"start": 100.0, "end": 130.0}]},
        "job-novid": {"job_id": "job-novid"},
    }
    monkeypatch.setattr(api_main, "get_job", lambda job_id: jobs.get(job_id))
    monkeypatch.setattr(api_main, "UPLOAD_DIR", tmp_path)

    # Auth: run as the DEV_MODE identity so these ownerless fixture jobs stay
    # visible (auth/ownership behaviour has its own suite — test_auth_ownership).
    api_main.app.dependency_overrides[get_current_user] = (
        lambda: AuthUser(id="dev-user", is_dev=True))

    # No audio file on disk → realign_line_words takes the fallback path;
    # the endpoint must still 200 with approximate=true.
    yield TestClient(api_main.app)
    api_main.app.dependency_overrides.pop(get_current_user, None)


def test_endpoint_unknown_job_404(api):
    r = api.post("/jobs/ghost/clips/0/realign-line",
                 json={"line_start": 1.0, "line_end": 3.0, "words": ["ఒకటి"]})
    assert r.status_code == 404


def test_endpoint_empty_words_422(api):
    r = api.post("/jobs/job-1/clips/0/realign-line",
                 json={"line_start": 1.0, "line_end": 3.0, "words": ["  ", ""]})
    assert r.status_code == 422


def test_endpoint_inverted_span_422(api):
    r = api.post("/jobs/job-1/clips/0/realign-line",
                 json={"line_start": 3.0, "line_end": 1.0, "words": ["ఒకటి"]})
    assert r.status_code == 422


def test_endpoint_no_video_id_400(api):
    r = api.post("/jobs/job-novid/clips/0/realign-line",
                 json={"line_start": 1.0, "line_end": 3.0, "words": ["ఒకటి"]})
    assert r.status_code == 400


def test_endpoint_degrades_to_even_distribution_with_tanglish(api):
    r = api.post(
        "/jobs/job-1/clips/0/realign-line",
        json={"line_start": 2.0, "line_end": 6.0, "words": ["ఒకటి", "రెండు"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["approximate"] is True
    assert [w["word"] for w in body["words"]] == ["ఒకటి", "రెండు"]
    # Even split of the fixed span
    assert body["words"][0]["start"] == pytest.approx(2.0)
    assert body["words"][0]["end"] == pytest.approx(4.0)
    assert body["words"][1]["end"] == pytest.approx(6.0)
    # Tanglish re-derived server-side for every word (deterministic path)
    for w in body["words"]:
        assert isinstance(w["word_tanglish"], str) and w["word_tanglish"].strip()
        assert w["word_tanglish"].isascii()
