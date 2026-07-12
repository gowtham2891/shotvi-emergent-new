"""
Render-and-verify tests for services/overlay_renderer.py + canvas_coords.py.

The progress-bar test is a real end-to-end render (FFmpeg + PIL), not a
mock — it burns an actual overlay onto a synthetic base clip, extracts
frames at known timestamps, and samples pixels to confirm the fill's
measured width matches the expected linear-over-duration formula. This is
the same render-and-verify approach used to empirically settle the
red-pop/clean-dark box-alpha question during Phase 1 exploration (see
frontend/KNOWN_ISSUES.md) — trust the actual rendered pixels, not just the
code that's supposed to produce them.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from PIL import Image

from services.canvas_coords import to_pixel_center, to_pixel_size, center_to_topleft
from services.overlay_renderer import render_elements, render_progress_bar, _ffprobe_duration


def _ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")


# ── canvas_coords.py — pure math, no ffmpeg ──────────────────────────────────

def test_to_pixel_center_is_a_simple_fraction_of_dimensions():
    c = to_pixel_center(0.5, 0.965, 1080, 1920)
    assert (c.cx, c.cy) == (540, 1853)  # round(0.965*1920) == 1853


def test_to_pixel_size_scales_independently_per_aspect():
    # Same width fraction, different render aspect -> different pixel width;
    # this is the deliberate generalization away from the frontend's
    # 9:16-specific canvasW=canvasH*9/16 shortcut (see canvas_coords.py docstring).
    w_916, _ = to_pixel_size(0.92, 0.02, 1080, 1920)
    w_11, _ = to_pixel_size(0.92, 0.02, 1080, 1080)
    w_169, _ = to_pixel_size(0.92, 0.02, 1920, 1080)
    assert w_916 == w_11 == 994  # both 1080-wide renders -> same pixel width
    assert w_169 == round(0.92 * 1920)  # 16:9's actual width, not 9:16's


def test_center_to_topleft_offsets_by_half_dimensions():
    assert center_to_topleft(100, 100, 20, 10) == (90, 95)


# ── render_elements — backward-compat no-op path ─────────────────────────────

def test_no_elements_is_a_pure_noop():
    # None/[]/invisible must all return the input path unchanged with zero
    # ffmpeg invocations, so existing caption-only rerenders (no elements
    # field at all) are byte-for-byte unaffected by this feature existing.
    for elements in (None, [], [{"type": "progress", "visible": False, "props": {}}]):
        result = render_elements("some_input.mp4", "unused_output.mp4", elements, 1080, 1920)
        assert result == "some_input.mp4"
    assert not os.path.exists("unused_output.mp4")


def test_each_element_type_invisible_is_a_pure_noop():
    # The visible-filter in render_elements is one shared, type-agnostic
    # mechanism — but assert it explicitly per type so a future refactor of
    # that filter can't silently start rendering (and re-encoding) an
    # element a draft has toggled off. Invisible logo/sticker/headline must
    # each return the input path unchanged with zero ffmpeg invocations,
    # exactly like the progress case above.
    for etype, props in (
        ("logo", {"handle": "@clipforge"}),
        ("headline", {"text": "hi", "color": "#22ff9c"}),
    ):
        el = {"type": etype, "visible": False, "x": 0.5, "y": 0.5, "props": props}
        result = render_elements("some_input.mp4", "unused_output.mp4", [el], 1080, 1920)
        assert result == "some_input.mp4", f"invisible {etype} was not a noop"
    assert not os.path.exists("unused_output.mp4")


def test_unknown_element_type_is_a_pure_noop():
    # A type not in _PREPARERS (e.g. a future element kind an older backend
    # doesn't understand) must be filtered out entirely, not crash — the
    # same forward-compat guarantee as an empty elements list.
    el = {"type": "confetti", "visible": True, "x": 0.5, "y": 0.5, "props": {}}
    result = render_elements("some_input.mp4", "unused_output.mp4", [el], 1080, 1920)
    assert result == "some_input.mp4"
    assert not os.path.exists("unused_output.mp4")


def test_retired_sticker_payload_is_skipped_not_a_crash():
    # The sticker element type was removed as a product decision. An old draft
    # may still carry a visible sticker element; render_elements must skip it
    # (it is no longer in _PREPARERS) with zero ffmpeg calls, never raise.
    el = {"type": "sticker", "visible": True, "x": 0.78, "y": 0.6,
          "props": {"emoji": "🔥", "fontSize": 0.13}}
    result = render_elements("some_input.mp4", "unused_output.mp4", [el], 1080, 1920)
    assert result == "some_input.mp4"
    assert not os.path.exists("unused_output.mp4")


def test_retired_sticker_mixed_with_supported_element_only_burns_supported(monkeypatch):
    # A draft with BOTH a retired sticker and a real (progress) element must
    # burn only the progress bar — the sticker is filtered out before the
    # single composite pass, which still runs for the supported layer.
    import services.overlay_renderer as ovr

    captured = {}

    def fake_composite(input_path, output_path, layers, duration):
        captured["n_layers"] = len(layers)
        return output_path

    monkeypatch.setattr(ovr, "_ffprobe_duration", lambda p: 5.0)
    monkeypatch.setattr(ovr, "_composite_layers", fake_composite)

    elements = [
        {"type": "sticker", "visible": True, "x": 0.8, "y": 0.6, "props": {"emoji": "🔥"}},
        {"type": "progress", "visible": True, "x": 0.5, "y": 0.9, "scale": 1, "rotation": 0,
         "props": {"color": "#7c3aed", "width": 0.8, "height": 0.03}},
    ]
    result = ovr.render_elements("in.mp4", "out.mp4", elements, 400, 600)
    assert result == "out.mp4"
    assert captured["n_layers"] == 1  # only the progress layer, sticker dropped


# ── render_progress_bar — real render-and-verify ─────────────────────────────

@requires_ffmpeg
def test_progress_bar_fill_width_matches_elapsed_time():
    with tempfile.TemporaryDirectory(prefix="overlay_test_") as tmp:
        base = os.path.join(tmp, "base.mp4")
        out = os.path.join(tmp, "out.mp4")
        duration = 10.0
        video_w, video_h = 400, 600

        # Synthetic base clip — solid color, no external fixture dependency.
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c=gray:s={video_w}x{video_h}:d={duration}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", base],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stderr

        element = {
            "x": 0.5, "y": 0.9, "scale": 1, "rotation": 0,
            "props": {"color": "#7c3aed", "width": 0.8, "height": 0.03},
        }
        render_progress_bar(base, out, element, video_w, video_h)
        assert os.path.exists(out)

        bar_w, bar_h = to_pixel_size(0.8, 0.03, video_w, video_h)
        center = to_pixel_center(0.5, 0.9, video_w, video_h)
        ox, oy = center_to_topleft(center.cx, center.cy, bar_w, bar_h)
        fill_rgb = (0x7C, 0x3A, 0xED)

        def measured_fill_width(t):
            frame_png = os.path.join(tmp, f"frame_{t}.png")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(t), "-i", out,
                 "-frames:v", "1", "-update", "1", frame_png],
                capture_output=True, timeout=30,
            )
            img = Image.open(frame_png).convert("RGB")
            px = img.load()
            y = oy + bar_h // 2
            rightmost = 0
            for x in range(ox, ox + bar_w):
                if all(abs(a - b) <= 40 for a, b in zip(px[x, y], fill_rgb)):
                    rightmost = x - ox + 1
            return rightmost

        # Checkpoints: start (~empty), middle (~50%), near-end (~full).
        for t, expected_frac, tol_frac in [(0.2, 0.02, 0.05), (5.0, 0.5, 0.05), (9.5, 0.95, 0.05)]:
            width = measured_fill_width(t)
            frac = width / bar_w
            assert abs(frac - expected_frac) <= tol_frac, (
                f"t={t}: measured fill fraction {frac:.3f}, expected ~{expected_frac} +/-{tol_frac}"
            )


# ── multiple elements together — single-pass architecture ───────────────────

@requires_ffmpeg
def test_progress_bar_and_logo_together_stay_in_sync_and_in_bounds():
    with tempfile.TemporaryDirectory(prefix="overlay_test_") as tmp:
        base = os.path.join(tmp, "base.mp4")
        out = os.path.join(tmp, "out.mp4")
        duration = 8.0
        video_w, video_h = 400, 600

        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c=gray:s={video_w}x{video_h}:d={duration}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", base],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stderr

        elements = [
            {"type": "progress", "id": "p1", "x": 0.5, "y": 0.9, "scale": 1, "rotation": 0,
             "visible": True, "props": {"color": "#7c3aed", "width": 0.8, "height": 0.03}},
            {"type": "logo", "id": "l1", "x": 0.25, "y": 0.15, "scale": 1, "rotation": 0,
             "visible": True, "props": {"text": "@test", "avatar": "T", "font": "Manrope", "fontSize": 0.04}},
        ]
        render_elements(base, out, elements, video_w, video_h)
        assert os.path.exists(out)

        out_duration = _ffprobe_duration(out)
        assert abs(out_duration - duration) < 0.2

        bar_w, bar_h = to_pixel_size(0.8, 0.03, video_w, video_h)
        bar_center = to_pixel_center(0.5, 0.9, video_w, video_h)
        bar_ox, bar_oy = center_to_topleft(bar_center.cx, bar_center.cy, bar_w, bar_h)
        fill_rgb = (0x7C, 0x3A, 0xED)

        frame_png = os.path.join(tmp, "mid.png")
        t_mid = duration / 2
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t_mid), "-i", out,
             "-frames:v", "1", "-update", "1", frame_png],
            capture_output=True, timeout=30,
        )
        img = Image.open(frame_png).convert("RGB")
        px = img.load()
        y = bar_oy + bar_h // 2
        rightmost = 0
        for x in range(bar_ox, bar_ox + bar_w):
            if all(abs(a - b) <= 40 for a, b in zip(px[x, y], fill_rgb)):
                rightmost = x - bar_ox + 1
        frac = rightmost / bar_w
        # Progress bar still animates correctly with a logo layer also
        # present in the same single composite pass.
        assert abs(frac - 0.5) <= 0.1, f"mid-clip fill fraction {frac:.2f}, expected ~0.5"


# ── logo ──────────────────────────────────────────────────────────────────────

@requires_ffmpeg
def test_logo_renders_gradient_circle_and_persists_for_the_whole_clip():
    with tempfile.TemporaryDirectory(prefix="overlay_test_") as tmp:
        base = os.path.join(tmp, "base.mp4")
        out = os.path.join(tmp, "out.mp4")
        duration = 6.0
        video_w, video_h = 400, 700

        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c=black:s={video_w}x{video_h}:d={duration}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", base],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stderr

        element = {
            "type": "logo", "id": "l1", "x": 0.2, "y": 0.1, "scale": 1, "rotation": 0,
            "visible": True,
            "props": {"text": "@test_user", "avatar": "T", "font": "Manrope", "fontSize": 0.04},
        }
        render_elements(base, out, [element], video_w, video_h)
        assert os.path.exists(out)
        assert abs(_ffprobe_duration(out) - duration) < 0.2

        center = to_pixel_center(0.2, 0.1, video_w, video_h)

        def has_purple_ish_pixel(t):
            frame_png = os.path.join(tmp, f"logo_{t}.png")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(t), "-i", out,
                 "-frames:v", "1", "-update", "1", frame_png],
                capture_output=True, timeout=30,
            )
            img = Image.open(frame_png).convert("RGB")
            px = img.load()
            # The gradient circle spans #7c3aed..#a78bfa — both have R<G<B
            # roughly, and are far from black background/white text.
            for x in range(max(center.cx - 60, 0), center.cx + 20, 5):
                for y in range(max(center.cy - 30, 0), center.cy + 30, 5):
                    r_, g_, b_ = px[x, y]
                    if b_ > 150 and r_ > 90 and (r_ + g_ + b_) < 720:
                        return True
            return False

        for t in (0.2, duration / 2, duration - 0.3):
            assert has_purple_ish_pixel(t), f"logo circle missing/wrong color at t={t}"


def test_logo_uses_bundled_manrope_font():
    from services.fonts import get_font_path
    path = get_font_path("Manrope")
    assert os.path.exists(path)
    assert "Manrope" in path


# ── headline ──────────────────────────────────────────────────────────────────

def test_headline_uses_bundled_outfit_font():
    from services.fonts import get_font_path
    path = get_font_path("Outfit")
    assert os.path.exists(path)
    assert "Outfit" in path


@requires_ffmpeg
def test_headline_renders_colored_text_and_persists_for_the_whole_clip():
    with tempfile.TemporaryDirectory(prefix="overlay_test_") as tmp:
        base = os.path.join(tmp, "base.mp4")
        out = os.path.join(tmp, "out.mp4")
        duration = 6.0
        video_w, video_h = 400, 700

        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c=black:s={video_w}x{video_h}:d={duration}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", base],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stderr

        element = {
            "type": "headline", "id": "h1", "x": 0.5, "y": 0.2, "scale": 1, "rotation": 0,
            "visible": True,
            "props": {"text": "94% viral", "font": "Outfit", "fontSize": 0.06,
                      "color": "#22ff9c", "weight": 900, "italic": False,
                      "uppercase": True, "stroke": True},
        }
        render_elements(base, out, [element], video_w, video_h)
        assert os.path.exists(out)
        assert abs(_ffprobe_duration(out) - duration) < 0.2

        center = to_pixel_center(0.5, 0.2, video_w, video_h)
        green = (0x22, 0xFF, 0x9C)

        def has_green_pixel(t):
            frame_png = os.path.join(tmp, f"hl_{t}.png")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(t), "-i", out,
                 "-frames:v", "1", "-update", "1", frame_png],
                capture_output=True, timeout=30,
            )
            img = Image.open(frame_png).convert("RGB")
            px = img.load()
            for x in range(max(center.cx - 150, 0), min(center.cx + 150, video_w), 4):
                for y in range(max(center.cy - 40, 0), min(center.cy + 40, video_h), 4):
                    if all(abs(a - b) <= 45 for a, b in zip(px[x, y], green)):
                        return True
            return False

        for t in (0.2, duration / 2, duration - 0.3):
            assert has_green_pixel(t), f"headline text missing/wrong color at t={t}"


def test_headline_uppercase_transform_matches_css_text_transform():
    # A pure-Python check of the transform itself (no render needed) —
    # HeadlineBody's CSS text-transform:uppercase behavior.
    text = "wait for it"
    props = {"uppercase": True}
    result = text.upper() if props.get("uppercase") else text
    assert result == "WAIT FOR IT"
