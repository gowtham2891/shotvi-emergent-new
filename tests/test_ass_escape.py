"""
BUG-008 regression gate — ASS-escape user text in generate_ass_karaoke.

Word text is concatenated straight into Dialogue lines after our override
block. If a word contains `{`, `}`, `\\`, or a newline, ASS mis-parses:

  - `{`  opens a new override tag (the text before it stays, the text inside
    the accidental override is treated as tags → dropped or garbled)
  - `}`  closes an override tag prematurely (leaks tag chars into the text)
  - `\\` starts an escape (subsequent character is consumed)
  - `\\n`/`\\r`/`\\r\\n` terminates the event line itself, cutting the
    caption off mid-word

The escaping happens BEFORE the color-override wrap, so the tags we emit
ourselves stay intact and only user/transcript text is escaped.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.caption_renderer import generate_ass_karaoke, _escape_ass_text


def _one_line(word):
    return [{"words": [{"word": word, "start": 0.0, "end": 0.5}],
             "line_start": 0.0, "line_end": 0.5}]


def _dialogue_bodies(ass):
    out = []
    for line in ass.splitlines():
        if line.startswith("Dialogue"):
            out.append(",".join(line.split(",")[9:]))
    return out


# ── unit-level: the escape function itself ──────────────────────────────────

def test_escape_helper_backslash_becomes_double_backslash():
    assert _escape_ass_text("a\\b") == "a\\\\b"


def test_escape_helper_open_brace():
    assert _escape_ass_text("hi{there}") == "hi\\{there\\}"


def test_escape_helper_close_brace_alone():
    assert _escape_ass_text("a}b") == "a\\}b"


def test_escape_helper_newlines():
    assert _escape_ass_text("line1\nline2") == "line1\\Nline2"
    assert _escape_ass_text("line1\r\nline2") == "line1\\Nline2"
    assert _escape_ass_text("line1\rline2") == "line1\\Nline2"


def test_escape_helper_empty_and_plain():
    assert _escape_ass_text("") == ""
    assert _escape_ass_text(None) == ""
    assert _escape_ass_text("plain telugu text") == "plain telugu text"
    # Telugu / Devanagari must pass through unmodified.
    assert _escape_ass_text("ఇది AI tool") == "ఇది AI tool"


# ── integration: words with control chars end up escaped in the ASS ─────────

def test_word_with_open_brace_does_not_open_override():
    ass = generate_ass_karaoke(_one_line("hi{there"), "bold-yellow")
    body = _dialogue_bodies(ass)[0]
    # Escaped literal — libass will print `{`, not open a new tag.
    assert "\\{" in body
    # And the raw open-brace-after-a-non-escape-char pattern must NOT appear
    # in the word portion (the tag `{\1c...}` we emit ourselves still starts
    # with `{` — but immediately after that opening brace we always emit a
    # backslash-then-tag; we test for the disallowed pattern of `{` sitting
    # next to a printable letter, which is the exact word-boundary bug).
    assert "hi{" not in body and "here" in body


def test_word_with_close_brace_stays_intact():
    ass = generate_ass_karaoke(_one_line("closing}here"), "bold-yellow")
    body = _dialogue_bodies(ass)[0]
    assert "\\}" in body
    # The full word content survives (both halves of the split must be present).
    assert "closing" in body and "here" in body


def test_word_with_backslash_stays_intact():
    ass = generate_ass_karaoke(_one_line("path\\name"), "bold-yellow")
    body = _dialogue_bodies(ass)[0]
    assert "path\\\\name" in body


def test_word_with_newline_gets_hard_break():
    ass = generate_ass_karaoke(_one_line("first\nsecond"), "bold-yellow")
    body = _dialogue_bodies(ass)[0]
    assert "first\\Nsecond" in body
    # No raw newline in the event line — otherwise the dialogue would break
    # onto two ASS lines and the second half would be discarded on parse.
    dialogue_lines = [line for line in ass.splitlines() if line.startswith("Dialogue")]
    assert len(dialogue_lines) == 1, (
        f"newline in word text produced {len(dialogue_lines)} Dialogue lines — "
        f"the escape must convert it to \\N, not a real line break"
    )


def test_override_tags_we_emit_are_not_double_escaped():
    """The escape runs on user text ONLY (before the color-override wrap), so
    the `{\\1c...}` tags we emit ourselves must still be present verbatim —
    NOT `\\{\\\\1c...\\}`. Otherwise the whole karaoke color path would break."""
    ass = generate_ass_karaoke(_one_line("plain"), "bold-yellow")
    body = _dialogue_bodies(ass)[0]
    # Our own override still starts with `{\1c` unescaped:
    assert "{\\1c" in body or "{\\1a" in body, (
        f"expected an unescaped color override tag in {body!r} — the escape "
        f"must not touch our own generated tags"
    )


def test_realistic_transcript_string_survives():
    """Multiple special chars in one word — everything survives and nothing
    escapes into the override block."""
    ass = generate_ass_karaoke(_one_line("a{b}\\c\nd"), "bold-yellow")
    body = _dialogue_bodies(ass)[0]
    assert "a\\{b\\}\\\\c\\Nd" in body
