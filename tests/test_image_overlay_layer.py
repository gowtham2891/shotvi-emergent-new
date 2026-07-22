"""
SPRINT 3 gate — image overlay layer geometry + caption-path neutrality.

The WYSIWYG contract: _prepare_image_layer must map editor state to burn
pixels with the SAME transform every other overlay uses —
to_pixel_center(x, y, vw, vh) for position, center_to_topleft for the
overlay anchor, height-fraction × video_height (× scale) for size with
width following the image's natural aspect ratio (the preview <img> is
`height: fraction*canvasH; width: auto`). Opacity multiplies the alpha
channel exactly like CSS opacity.

Caption-path neutrality (BURNIN_NOTES §5): this sprint touches NOTHING in
services/caption_renderer.py — the image stage rides render_elements'
existing single composite pass, before captions. The no-op guarantees below
pin the pre-existing payload path to byte-identical behavior (zero ffmpeg
calls, identity element list), and the full caption test suite continues to
gate the caption render itself.
"""

import os
import subprocess
import sys
import tempfile

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.canvas_coords import to_pixel_center, center_to_topleft
from services.overlay_renderer import (
    _prepare_image_layer,
    render_elements,
    resolve_image_overlays,
)


def _ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")


def _write_png(path, size=(200, 100), color=(255, 0, 0, 255)):
    Image.new("RGBA", size, color).save(path)
    return path


def _image_element(src, *, x=0.5, y=0.5, height=0.2, opacity=1, scale=1, rotation=0):
    return {
        "id": "el_image_1",
        "type": "image",
        "x": x, "y": y,
        "scale": scale, "rotation": rotation,
        "visible": True,
        "props": {"image_id": "irrelevant", "_resolved_path": src,
                  "height": height, "opacity": opacity},
    }


# ── Geometry: the same transform as every other overlay ──────────────────────

def test_layer_size_is_height_fraction_of_video_height_width_by_natural_ratio(tmp_path):
    src = _write_png(tmp_path / "img.png", size=(200, 100))  # 2:1 natural ratio
    el = _image_element(str(src), height=0.2)
    layer = _prepare_image_layer(el, 1080, 1920, str(tmp_path))
    assert layer.height == round(0.2 * 1920)          # 384
    assert layer.width == round(layer.height * 2)     # natural 2:1 → 768


def test_layer_position_uses_shared_center_transform(tmp_path):
    src = _write_png(tmp_path / "img.png", size=(100, 100))
    el = _image_element(str(src), x=0.25, y=0.75, height=0.1)
    layer = _prepare_image_layer(el, 1080, 1920, str(tmp_path))
    center = to_pixel_center(0.25, 0.75, 1080, 1920)
    assert (layer.ox, layer.oy) == center_to_topleft(center.cx, center.cy,
                                                     layer.width, layer.height)


def test_scale_multiplies_uniformly(tmp_path):
    src = _write_png(tmp_path / "img.png", size=(100, 50))
    base = _prepare_image_layer(_image_element(str(src), height=0.1),
                                1080, 1920, str(tmp_path))
    scaled = _prepare_image_layer(_image_element(str(src), height=0.1, scale=2),
                                  1080, 1920, str(tmp_path))
    assert scaled.height == round(0.1 * 1920 * 2)
    assert scaled.width / scaled.height == pytest.approx(base.width / base.height, abs=0.02)


def test_size_scales_with_render_aspect_like_other_overlays(tmp_path):
    # Height fraction is relative to the ACTUAL render height, per aspect —
    # same rule to_pixel_size enforces for progress/logo/headline.
    src = _write_png(tmp_path / "img.png", size=(100, 100))
    h_916 = _prepare_image_layer(_image_element(str(src), height=0.2), 1080, 1920, str(tmp_path)).height
    h_11 = _prepare_image_layer(_image_element(str(src), height=0.2), 1080, 1080, str(tmp_path)).height
    h_169 = _prepare_image_layer(_image_element(str(src), height=0.2), 1920, 1080, str(tmp_path)).height
    assert h_916 == round(0.2 * 1920)
    assert h_11 == h_169 == round(0.2 * 1080)


def test_opacity_multiplies_alpha_channel(tmp_path):
    src = _write_png(tmp_path / "img.png", size=(50, 50), color=(0, 255, 0, 255))
    el = _image_element(str(src), opacity=0.5)
    layer = _prepare_image_layer(el, 1080, 1920, str(tmp_path))
    burned = Image.open(layer.path).convert("RGBA")
    center_alpha = burned.getpixel((burned.width // 2, burned.height // 2))[3]
    assert center_alpha == pytest.approx(128, abs=2)


def test_rotation_grows_bbox_but_keeps_center(tmp_path):
    src = _write_png(tmp_path / "img.png", size=(200, 100))
    el = _image_element(str(src), x=0.5, y=0.5, height=0.1, rotation=45)
    layer = _prepare_image_layer(el, 1080, 1920, str(tmp_path))
    unrotated = _prepare_image_layer(_image_element(str(src), height=0.1),
                                     1080, 1920, str(tmp_path))
    assert layer.width > unrotated.width or layer.height > unrotated.height
    # Center stays fixed relative to the grown box (shared invariant).
    center = to_pixel_center(0.5, 0.5, 1080, 1920)
    assert (layer.ox, layer.oy) == center_to_topleft(center.cx, center.cy,
                                                     layer.width, layer.height)


def test_missing_resolved_path_is_skipped_not_a_crash(tmp_path):
    el = _image_element(str(tmp_path / "nope.png"))
    assert _prepare_image_layer(el, 1080, 1920, str(tmp_path)) is None
    el2 = _image_element(None)
    el2["props"].pop("_resolved_path")
    assert _prepare_image_layer(el2, 1080, 1920, str(tmp_path)) is None


# ── Caption-path neutrality: pre-existing payloads take identical paths ──────

def test_render_elements_without_image_elements_is_untouched_noop():
    # None/[] and unresolved image elements produce ZERO ffmpeg calls and
    # return the input unchanged — the caption-only export path is
    # byte-identical to before this sprint.
    for elements in (None, [],
                     [{"type": "image", "visible": False, "props": {}}],
                     [{"type": "image", "visible": True, "props": {}}]):
        assert render_elements("in.mp4", "out.mp4", elements, 1080, 1920) == "in.mp4"
    assert not os.path.exists("out.mp4")


def test_resolver_identity_object_for_legacy_payloads():
    legacy = [{"type": "progress", "props": {}}, {"type": "headline", "props": {}}]
    assert resolve_image_overlays(legacy, "vid", "/x") is legacy


# ── End-to-end composite (ffmpeg) — burned pixels land where the editor says ──

@requires_ffmpeg
def test_image_overlay_burns_at_expected_position_and_survives_composite(tmp_path):
    vw, vh = 270, 480  # small 9:16 canvas keeps the encode fast
    base = str(tmp_path / "base.mp4")
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={vw}x{vh}:d=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", base],
        capture_output=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr[-300:]

    src = _write_png(tmp_path / "overlay.png", size=(100, 100), color=(255, 0, 0, 255))
    el = _image_element(str(src), x=0.5, y=0.25, height=0.2)
    out = str(tmp_path / "out.mp4")
    result = render_elements(base, out, [el], vw, vh)
    assert result == out

    frame = str(tmp_path / "frame.png")
    subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", out, "-frames:v", "1", frame],
                   capture_output=True, timeout=60)
    img = Image.open(frame).convert("RGB")

    # The overlay's center pixel (0.5, 0.25) must be red; a far corner black.
    cx, cy = round(0.5 * vw), round(0.25 * vh)
    r_, g_, b_ = img.getpixel((cx, cy))
    assert r_ > 180 and g_ < 80 and b_ < 80, f"expected red at overlay center, got {(r_, g_, b_)}"
    r2, g2, b2 = img.getpixel((10, vh - 10))
    assert r2 < 60 and g2 < 60 and b2 < 60, "canvas outside the overlay should stay black"
