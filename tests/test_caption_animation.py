# -*- coding: utf-8 -*-
"""Feature #15 — caption reveal animations.

'karaoke' (default) keeps the per-word highlight burn byte-identical; the
reveal presets switch to ONE event per line with an ASS motion tag on
appearance (pop=\\t scale, fade=\\fad, slide-up=\\move).
"""

from services.caption_renderer import (
    get_words_for_clip,
    group_words_into_lines,
    generate_ass_karaoke,
)


TRANSCRIPT = {
    "word_timestamps": [
        {"word": "ఒకటి",  "start": 0.0, "end": 0.5},
        {"word": "రెండు", "start": 0.6, "end": 1.1},
        {"word": "మూడు",  "start": 1.2, "end": 1.7},
    ]
}


def _lines():
    return group_words_into_lines(get_words_for_clip(TRANSCRIPT, 0.0, 2.0))


def _dialogue(ass):
    return [l for l in ass.splitlines() if l.startswith("Dialogue:")]


def test_karaoke_default_is_byte_identical():
    default = generate_ass_karaoke(_lines(), "bold-yellow")
    explicit = generate_ass_karaoke(_lines(), "bold-yellow", animation="karaoke")
    assert default == explicit
    # per-word events (one per word) — the karaoke path is unchanged.
    assert len(_dialogue(default)) == 3


def test_reveal_presets_emit_one_event_per_line():
    for anim in ("pop", "fade", "slide-up", "none"):
        ass = generate_ass_karaoke(_lines(), "bold-yellow", animation=anim)
        # 3 words, wpl=4 → one line → ONE event (not 3).
        assert len(_dialogue(ass)) == 1, anim
        # all three words are present in that single event
        for w in ("ఒకటి", "రెండు", "మూడు"):
            assert w in ass


def test_pop_uses_scale_transform():
    ass = generate_ass_karaoke(_lines(), "bold-yellow", animation="pop")
    assert "\\fscx70\\fscy70\\t(0,180,\\fscx100\\fscy100)" in ass


def test_fade_uses_fad():
    ass = generate_ass_karaoke(_lines(), "bold-yellow", animation="fade")
    assert "\\fad(180,0)" in ass


def test_slide_up_uses_move():
    ass = generate_ass_karaoke(_lines(), "bold-yellow", animation="slide-up",
                               video_width=1080, video_height=1920)
    assert "\\move(" in ass
    # \move present INSTEAD of a bare \pos on the (single) event
    dlg = _dialogue(ass)[0]
    assert "\\move(" in dlg


def test_none_is_static_no_motion_tag():
    ass = generate_ass_karaoke(_lines(), "bold-yellow", animation="none")
    assert "\\fad(" not in ass and "\\move(" not in ass and "\\t(" not in ass
    # still a single \pos-anchored event
    assert "\\an5\\pos(" in ass


def test_unknown_animation_falls_back_to_karaoke():
    weird = generate_ass_karaoke(_lines(), "bold-yellow", animation="disco")
    karaoke = generate_ass_karaoke(_lines(), "bold-yellow", animation="karaoke")
    assert weird == karaoke


def test_emphasis_survives_a_reveal_animation():
    words = get_words_for_clip(TRANSCRIPT, 0.0, 2.0)
    words[1]["emphasis"] = True  # రెండు
    lines = group_words_into_lines(words)
    ass = generate_ass_karaoke(lines, "bold-yellow", animation="fade")
    # emphasized word keeps its bold + 112% scale even in the reveal path
    seg = ass.split("రెండు")[0].rsplit("{", 1)[1]
    assert "\\b1" in seg and "\\fscx112" in seg
