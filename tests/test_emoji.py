# -*- coding: utf-8 -*-
"""Feature #30 — timed color-emoji overlays (Twemoji PNG).

Covers the emoji↔asset contract (services/emoji.py), the burn preparer +
per-layer display window (services/overlay_renderer.py :: _prepare_emoji_layer,
Layer.start/end, _composite_layers enable='between'), and a real ffmpeg burn
proving the emoji is composited ONLY inside its window (skipped without ffmpeg).
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.emoji import (
    EMOJI_PALETTE, PALETTE_CHARS, EMOJI_ASSETS_DIR,
    emoji_codepoint, emoji_asset_path, is_palette_emoji, palette_prompt_block,
    split_caption_emoji, resolve_palette_emoji,
)
from services.overlay_renderer import (
    Layer, _prepare_emoji_layer, _composite_layers, _PREPARERS,
)
from services.caption_renderer import (
    _extract_caption_emoji_overlays, _burn_caption_emoji_overlays,
    generate_ass_karaoke,
)


def _ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")


# ── emoji ↔ asset contract ──────────────────────────────────────────────────

def test_codepoint_strips_variation_selector():
    assert emoji_codepoint("🔥") == "1f525"
    assert emoji_codepoint("❤️") == "2764"      # U+FE0F dropped (Twemoji naming)
    assert emoji_codepoint("⚡") == "26a1"


def test_every_palette_emoji_has_a_bundled_png():
    """The palette is a promise: every emoji Gemini may suggest MUST have a
    bundled asset (no runtime download, no missing-PNG render gap)."""
    missing = [ch for ch, _ in EMOJI_PALETTE if emoji_asset_path(ch) is None]
    assert not missing, f"palette emoji with no bundled PNG: {missing}"
    # and each asset is a real, non-empty PNG file
    for ch, _ in EMOJI_PALETTE:
        path = emoji_asset_path(ch)
        assert os.path.getsize(path) > 0
        with open(path, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_asset_lookup_rejects_non_palette():
    assert emoji_asset_path("🦄") is None      # unicorn not in curated palette
    assert not is_palette_emoji("🦄")
    assert emoji_asset_path("") is None
    assert is_palette_emoji("🔥")


def test_palette_prompt_block_lists_every_emoji():
    block = palette_prompt_block()
    for ch, _ in EMOJI_PALETTE:
        assert ch in block
    assert len(block.splitlines()) == len(EMOJI_PALETTE)


def test_palette_has_no_duplicates():
    chars = [ch for ch, _ in EMOJI_PALETTE]
    assert len(chars) == len(set(chars)) == len(PALETTE_CHARS)


# ── burn preparer: Layer + display window ───────────────────────────────────

def _emoji_el(**props):
    base = {"emoji": "🔥", "height": 0.12, "opacity": 1.0}
    base.update(props)
    return {"id": "em1", "type": "emoji", "x": 0.5, "y": 0.35,
            "scale": 1, "rotation": 0, "visible": True, "props": base}


def test_emoji_registered_as_a_preparer():
    assert "emoji" in _PREPARERS


def test_prepare_emoji_layer_carries_timing():
    with tempfile.TemporaryDirectory() as tmp:
        layer = _prepare_emoji_layer(_emoji_el(start=1.0, end=2.0), 540, 960, tmp)
        assert layer is not None and not layer.is_video
        assert layer.start == 1.0 and layer.end == 2.0
        assert os.path.exists(layer.path)          # a real resized PNG was written


def test_prepare_emoji_layer_skips_non_palette():
    with tempfile.TemporaryDirectory() as tmp:
        assert _prepare_emoji_layer(_emoji_el(emoji="🦄"), 540, 960, tmp) is None
        assert _prepare_emoji_layer(_emoji_el(emoji=None), 540, 960, tmp) is None


def test_prepare_emoji_layer_degenerate_window_becomes_always_on():
    with tempfile.TemporaryDirectory() as tmp:
        layer = _prepare_emoji_layer(_emoji_el(start=2.0, end=1.0), 540, 960, tmp)
        assert layer is not None
        assert layer.start is None and layer.end is None   # backwards window dropped


def test_prepare_emoji_layer_missing_times_is_always_on():
    with tempfile.TemporaryDirectory() as tmp:
        layer = _prepare_emoji_layer(_emoji_el(), 540, 960, tmp)   # no start/end
        assert layer is not None
        assert layer.start is None and layer.end is None


# ── compositor: enable='between' only for timed layers ──────────────────────

def _capture_composite_cmd(layers, monkeypatch):
    captured = {}

    class _R:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, *a, **k):
        captured["cmd"] = cmd
        return _R()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    _composite_layers("in.mp4", "out.mp4", layers, duration=3.0)
    return captured["cmd"]


def _filter_arg(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_timed_layer_emits_enable_between(monkeypatch):
    timed = Layer(path="x.png", is_video=False, width=64, height=64, ox=10, oy=20,
                  start=1.0, end=2.0)
    fc = _filter_arg(_capture_composite_cmd([timed], monkeypatch))
    assert "enable='between(t,1.000,2.000)'" in fc
    assert "overlay=x=10:y=20:enable='between(t,1.000,2.000)':shortest=1" in fc


def test_untimed_layer_omits_enable(monkeypatch):
    plain = Layer(path="x.png", is_video=False, width=64, height=64, ox=10, oy=20)
    fc = _filter_arg(_capture_composite_cmd([plain], monkeypatch))
    assert "enable" not in fc
    assert "overlay=x=10:y=20:shortest=1" in fc


# ── real burn: emoji visible ONLY inside its window ─────────────────────────

@requires_ffmpeg
def test_emoji_burns_only_inside_its_window():
    from services.overlay_renderer import render_elements
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base.mp4")
        out = os.path.join(tmp, "out.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=540x960:d=3",
             "-f", "lavfi", "-i", "anullsrc", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", base],
            capture_output=True, check=True, timeout=60,
        )
        el = _emoji_el(start=1.0, end=2.0)
        el["y"] = 0.35
        render_elements(base, out, [el], 540, 960)
        assert os.path.exists(out)

        def nonblack_at(t):
            fp = os.path.join(tmp, f"f{int(t*10)}.png")
            subprocess.run(["ffmpeg", "-y", "-i", out, "-ss", str(t),
                            "-frames:v", "1", fp], capture_output=True, timeout=60)
            im = Image.open(fp).convert("RGB")
            return sum(1 for r, g, b in im.getdata() if r > 20 or g > 20 or b > 20)

        assert nonblack_at(0.5) == 0        # before window — nothing burned
        assert nonblack_at(1.5) > 500       # inside window — color emoji present
        assert nonblack_at(2.5) == 0        # after window — gone again


# ── typed-caption emoji: detect / strip / resolve ───────────────────────────

def test_split_leaves_plain_text_untouched():
    # Telugu + Latin + punctuation — no emoji, no change, no tokens.
    assert split_caption_emoji("మీరు test-లో ఉన్నారు!") == ("మీరు test-లో ఉన్నారు!", [])
    assert split_caption_emoji("") == ("", [])


def test_split_strips_a_trailing_emoji_and_returns_it():
    clean, tokens = split_caption_emoji("fire🔥")
    assert clean == "fire"
    assert tokens == ["🔥"]


def test_split_emoji_only_word_becomes_empty():
    clean, tokens = split_caption_emoji("🔥")
    assert clean == "" and tokens == ["🔥"]


def test_split_separates_adjacent_emoji():
    clean, tokens = split_caption_emoji("🔥🚀")
    assert clean == "" and tokens == ["🔥", "🚀"]


def test_split_handles_variation_selector():
    # ❤️ = U+2764 U+FE0F — the selector stays attached to the one token.
    clean, tokens = split_caption_emoji("love❤️")
    assert clean == "love" and len(tokens) == 1
    assert resolve_palette_emoji(tokens[0]) == "❤️"


def test_resolve_palette_matches_by_codepoint():
    assert resolve_palette_emoji("🔥") == "🔥"
    assert resolve_palette_emoji("❤") == "❤️"     # bare heart resolves to the palette form
    assert resolve_palette_emoji("🦄") is None      # not in the curated palette


# ── typed-caption emoji: extraction from lines ──────────────────────────────

def _line(words, start, end):
    return {"words": words, "line_start": start, "line_end": end}


def test_extract_strips_word_text_and_times_to_the_line():
    lines = [
        _line([{"word": "AI", "start": 0.0, "end": 0.4},
               {"word": "tool🔥", "start": 0.4, "end": 1.0}], 0.0, 1.0),
        _line([{"word": "next💯", "start": 1.2, "end": 1.8}], 1.2, 1.8),
    ]
    overlays = _extract_caption_emoji_overlays(lines)
    # word text is stripped in place — libass never sees the emoji
    assert lines[0]["words"][1]["word"] == "tool"
    assert lines[1]["words"][0]["word"] == "next"
    # one overlay per palette emoji, timed to its LINE
    assert overlays == [
        {"emoji": "🔥", "start": 0.0, "end": 1.0},
        {"emoji": "💯", "start": 1.2, "end": 1.8},
    ]


def test_extract_drops_non_palette_emoji_but_still_strips_text():
    lines = [_line([{"word": "wow🦄", "start": 0.0, "end": 0.5}], 0.0, 0.5)]
    overlays = _extract_caption_emoji_overlays(lines)
    assert lines[0]["words"][0]["word"] == "wow"   # unicorn stripped from text
    assert overlays == []                          # but no overlay (not in palette)


def test_extracted_text_produces_emoji_free_ass():
    lines = [_line([{"word": "మీరు", "start": 0.0, "end": 0.4},
                    {"word": "hot🔥", "start": 0.4, "end": 1.0}], 0.0, 1.0)]
    _extract_caption_emoji_overlays(lines)
    ass = generate_ass_karaoke(lines, "bold-yellow")
    assert "🔥" not in ass          # the burn text is emoji-free (no tofu)
    assert "hot" in ass and "మీరు" in ass


# ── typed-caption emoji: real burn through the shared overlay path ──────────

@requires_ffmpeg
def test_typed_caption_emoji_burns_as_color_overlay():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "cap.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=540x960:d=3",
             "-f", "lavfi", "-i", "anullsrc", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", base],
            capture_output=True, check=True, timeout=60,
        )
        overlays = [{"emoji": "🔥", "start": 1.0, "end": 2.0}]
        out = _burn_caption_emoji_overlays(base, overlays, 540, 960)
        assert out == base and os.path.exists(base)  # baked back into the same path

        def nonblack_at(t):
            fp = os.path.join(tmp, f"f{int(t*10)}.png")
            subprocess.run(["ffmpeg", "-y", "-i", base, "-ss", str(t),
                            "-frames:v", "1", fp], capture_output=True, timeout=60)
            im = Image.open(fp).convert("RGB")
            return sum(1 for r, g, b in im.getdata() if r > 20 or g > 20 or b > 20)

        assert nonblack_at(0.5) == 0        # before the line
        assert nonblack_at(1.5) > 500       # color emoji burned in during the line
        assert nonblack_at(2.5) == 0        # after the line


@requires_ffmpeg
def test_render_captions_for_clip_end_to_end_typed_emoji():
    """The full worker path: a transcript word carrying a typed 🔥 →
    render_captions_for_clip → captioned video with a COLOR emoji overlay and an
    ASS whose caption text is emoji-free (no tofu)."""
    import json
    from PIL import Image
    from services.caption_renderer import render_captions_for_clip, safe_ass_path

    with tempfile.TemporaryDirectory() as tmp:
        # a real 3s vertical clip (name avoids the _vertical.mp4 sidecar branch)
        clip_mp4 = os.path.join(tmp, "clip0.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=540x960:d=3",
             "-f", "lavfi", "-i", "anullsrc", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", clip_mp4],
            capture_output=True, check=True, timeout=60,
        )
        transcript = {
            "word_timestamps": [
                {"word": "ee", "start": 0.0, "end": 0.5},
                {"word": "tool", "start": 0.5, "end": 1.0},
                {"word": "hot🔥", "start": 1.0, "end": 1.5},   # typed emoji
            ],
            "sentences": [{"id": 0, "text": "ee tool hot", "start": 0.0, "end": 1.5}],
        }
        clips = {"clips": [{"clip_id": "c0", "start": 0.0, "end": 3.0, "segments": [],
                            "why": "t", "hook_text": "t"}]}
        tpath = os.path.join(tmp, "vid_audio_transcript.json")
        cpath = os.path.join(tmp, "vid_audio_clips.json")
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump(transcript, f, ensure_ascii=False)
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(clips, f, ensure_ascii=False)

        out = render_captions_for_clip(
            tpath, cpath, 0, clip_mp4, tmp,
            style_name="bold-yellow", caption_font="Noto Sans Telugu",
            video_width=540, video_height=960,
        )
        assert out and os.path.exists(out)

        # the generated ASS carries NO emoji (libass never saw a color glyph)
        ass_path = safe_ass_path(clip_mp4, "bold-yellow")
        with open(ass_path, "r", encoding="utf-8") as f:
            ass = f.read()
        assert "🔥" not in ass
        assert "hot" in ass          # the word text (minus emoji) is still burned

        # the output video shows the color emoji during the word's line (1.0-1.5s)
        fp = os.path.join(tmp, "frame.png")
        subprocess.run(["ffmpeg", "-y", "-i", out, "-ss", "1.2", "-frames:v", "1", fp],
                       capture_output=True, timeout=60)
        im = Image.open(fp).convert("RGB")
        # a color emoji has saturated (non-grey) pixels — a mono/tofu glyph would
        # be near-greyscale. Count clearly-colored pixels.
        colored = sum(1 for r, g, b in im.getdata()
                      if max(r, g, b) - min(r, g, b) > 40 and max(r, g, b) > 80)
        assert colored > 200, f"expected a color emoji overlay, got {colored} colored px"
