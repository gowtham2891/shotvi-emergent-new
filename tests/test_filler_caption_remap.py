# -*- coding: utf-8 -*-
"""Feature #14 — cut spans remap the BURNED caption lines (line-level pass in
generate path). A line whose words all fall in a cut vanishes; survivors
shift onto the post-cut timeline; emphasis flags survive the cut.
"""

import re

from services.caption_renderer import (
    get_words_for_clip,
    group_words_into_lines,
    generate_ass_karaoke,
)
from services.filler_removal import apply_cuts_to_words


TRANSCRIPT = {
    "word_timestamps": [
        {"word": "ఒకటి",  "start": 0.0, "end": 0.5},
        {"word": "um",    "start": 1.0, "end": 1.4},
        {"word": "రెండు", "start": 2.0, "end": 2.5},
        {"word": "మూడు",  "start": 3.0, "end": 3.5},
    ]
}


def _times(ass):
    out = []
    for line in ass.splitlines():
        if line.startswith("Dialogue:"):
            m = re.match(r"Dialogue: \d+,(\d+):(\d+):(\d+\.\d+),", line)
            h, mi, s = m.groups()
            out.append(int(h) * 3600 + int(mi) * 60 + float(s))
    return out


def test_cut_shifts_caption_events_earlier():
    words = get_words_for_clip(TRANSCRIPT, 0.0, 4.0)
    # Cut the "um" filler span [1.0, 1.4] — words after shift 0.4s earlier.
    # words_per_line=1 so each word is its own event row (otherwise every
    # karaoke row of a shared line contains all the line's word text).
    lines = group_words_into_lines(words, words_per_line=1)
    kept = []
    for l in lines:
        nw = apply_cuts_to_words(l["words"], [[1.0, 1.4]])
        if not nw:
            continue
        l["words"] = nw
        l["line_start"] = nw[0]["start"]
        l["line_end"] = nw[-1]["end"]
        kept.append(l)
    ass = generate_ass_karaoke(kept, "bold-yellow")
    # "um" is gone; remaining 3 words present.
    assert "um" not in ass
    for w in ("ఒకటి", "రెండు", "మూడు"):
        assert w in ass
    # రెండు originally at 2.0 → now 1.6 (0.4s removed before it).
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue:") and "రెండు" in l]
    assert dialogue
    start = _times("\n".join(dialogue))[0]
    assert abs(start - 1.6) < 0.05


def test_whole_line_in_a_cut_vanishes():
    words = get_words_for_clip(TRANSCRIPT, 0.0, 4.0)
    lines = group_words_into_lines(words, words_per_line=1)  # one word per line
    kept = []
    for l in lines:
        nw = apply_cuts_to_words(l["words"], [[0.9, 1.5]])  # covers only "um"
        if not nw:
            continue
        l["words"] = nw
        l["line_start"] = nw[0]["start"]
        l["line_end"] = nw[-1]["end"]
        kept.append(l)
    assert len(kept) == 3  # the "um" line dropped
    ass = generate_ass_karaoke(kept, "bold-yellow")
    assert "um" not in ass
