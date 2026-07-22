# -*- coding: utf-8 -*-
"""Telugu → Tanglish engine tests (services/tanglish.py).

Covers the casual-romanization contract: long-vowel doubling, both anusvara
contexts, consonant clusters (vocalic r), hybrid Latin-Telugu tokens,
pure-English pass-through, punctuation, digits, and determinism.
"""

import pytest

from services.tanglish import telugu_to_tanglish, ensure_word_tanglish


# (input, expected) — 30 real words. Expectations are casual WhatsApp-Telugu:
# aa/ee/oo doubling, m-before-labial / n-elsewhere anusvara, ch for చ,
# ru for the vocalic r, sh for ś/ṣ, no diacritics anywhere.
WORDS = [
    # long vowels double
    ("దీన్ని", "deenni"),          # ī → ee (the flagship example)
    ("చూడు", "choodu"),           # ū → oo, c → ch
    ("మాట్లాడు", "maatlaadu"),    # ā → aa, retroflex ṭ/ḍ → t/d
    ("ఆరోగ్యం", "aarogyam"),      # ā → aa, ō → o, final anusvara → m
    ("బాగుంది", "baagundi"),      # ā → aa, anusvara before d → n
    # short ē/ō stay single (casual convention)
    ("ప్రేమ", "prema"),
    ("ఏమి", "emi"),
    ("లో", "lo"),
    # anusvara — labial context → m
    ("పంపు", "pampu"),
    ("కుటుంబం", "kutumbam"),
    ("సంబంధం", "sambandham"),     # both contexts in one word: mb → m, dh → n... m final
    # anusvara — non-labial context → n
    ("అందరు", "andaru"),
    ("ఇంట్లో", "intlo"),
    ("సంఘం", "sangham"),
    # anusvara — word-final → m
    ("పుస్తకం", "pustakam"),
    # anusvara — before liquids/sibilants → m (casual convention)
    ("కల్పవృక్షంలా", "kalpavrukshamlaa"),
    ("సంవత్సరం", "samvatsaram"),
    # consonant clusters / vocalic r (vṛ → vru style)
    ("వృద్ధి", "vruddhi"),
    ("కృష్ణ", "krushna"),
    ("హృదయం", "hrudayam"),
    # sibilants
    ("శక్తి", "shakti"),
    ("షరతు", "sharatu"),
    # ḷ, geminates
    ("వాళ్ళు", "vaallu"),
    ("అమ్మ", "amma"),
    # ñ, ఛ
    ("జ్ఞానం", "jnaanam"),
    ("ఛాయ", "chhaaya"),
    # diphthongs, virama-final
    ("ఔను", "aunu"),
    ("ఐదు", "aidu"),
    ("డాక్టర్", "daaktar"),
    # hybrid Latin-Telugu tokens — Latin run untouched, Telugu run converted
    ("mind-ని", "mind-ni"),
    ("2024లో", "2024lo"),
    # pure-English words pass through byte-identically
    ("control", "control"),
    # punctuation-attached words
    ("చెప్పాడు.", "cheppaadu."),
    ("తెలుగు,", "telugu,"),
]


@pytest.mark.parametrize("telugu,expected", WORDS, ids=[w[1] for w in WORDS])
def test_word(telugu, expected):
    assert telugu_to_tanglish(telugu) == expected


def test_deterministic_double_run():
    for telugu, _ in WORDS:
        assert telugu_to_tanglish(telugu) == telugu_to_tanglish(telugu)


def test_output_is_pure_ascii_no_diacritics():
    for telugu, _ in WORDS:
        out = telugu_to_tanglish(telugu)
        assert all(ord(c) < 128 for c in out), f"non-ASCII in {out!r}"


def test_sentence_with_mixed_scripts():
    assert (
        telugu_to_tanglish("నేను school కి వెళ్తున్నాను")
        == "nenu school ki veltunnaanu"
    )


def test_empty_and_punctuation_only():
    assert telugu_to_tanglish("") == ""
    assert telugu_to_tanglish("...") == "..."
    assert telugu_to_tanglish("?!") == "?!"


# ── ensure_word_tanglish (on-demand backfill for old transcripts) ──────────

def test_ensure_backfills_flat_shape():
    t = {"word_timestamps": [
        {"word": "దీన్ని", "start": 0.0, "end": 0.5},
        {"word": "control", "start": 0.5, "end": 1.0},
    ]}
    assert ensure_word_tanglish(t) == 2
    assert t["word_timestamps"][0]["word_tanglish"] == "deenni"
    assert t["word_timestamps"][1]["word_tanglish"] == "control"
    # second pass is a no-op — nothing left to fill
    assert ensure_word_tanglish(t) == 0


def test_ensure_backfills_nested_whisper_shape():
    t = {"segments": [{"words": [{"word": "చూడు", "start": 0, "end": 1}]}]}
    assert ensure_word_tanglish(t) == 1
    assert t["segments"][0]["words"][0]["word_tanglish"] == "choodu"


def test_ensure_preserves_existing_values():
    t = {"word_timestamps": [{"word": "దీన్ని", "word_tanglish": "custom"}]}
    assert ensure_word_tanglish(t) == 0
    assert t["word_timestamps"][0]["word_tanglish"] == "custom"
