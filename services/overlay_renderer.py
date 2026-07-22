"""
ClipForge AI — Canvas Overlay Renderer
========================================
Burns EditDocument overlay elements (progress bar, logo, headline) onto a
clip, closing the preview/export parity gap — these elements exist in the
editor's draft today but the render pipeline has always ignored them. Runs
as its own FFmpeg pass, appended after _apply_canvas (format/background)
and before caption burn-in, so it never touches the existing, working
caption path.

Performance-driven architecture: the full-resolution libx264 re-encode
dominates render_progress_bar's cost (~19s of ~23s for a 50s 1080x1920
clip) and is essentially the SAME cost regardless of how much gets
composited in that one pass — so with N element types each getting their
own re-encode pass, cost stacks ~linearly with N. Every element type
therefore prepares its own layer (a static PNG, or for the one genuinely
time-varying element — the progress bar — a short animated clip) WITHOUT
encoding the main video, and render_elements() composites every prepared
layer in exactly ONE final full-resolution pass, regardless of how many
elements are present.

Animation technique note: FFmpeg 8.0.1's drawbox/crop filters accept `t`
in width/position expressions without a parse error, but empirically do
NOT re-evaluate it per frame in this build (confirmed with a controlled
frame-sequence test — width stayed frozen at its t=0 value for the whole
clip). The progress bar's fill is instead computed in PIL, one frame per
tick — directly inspectable/testable — encoded once to a small lossless
clip, then composited like any other layer.

Stage 1: progress bar. Stage 3: logo (a synthetic avatar-circle +
handle-text widget — see _prepare_logo_layer for the approved scope note
on why this isn't an uploaded image). Stage 4: headline (bundled Outfit
variable font via services/fonts.py, drop shadow + optional stroke,
matching HeadlineBody's CSS spec) — follows the same
_prepare_<type>_layer(...) -> Layer pattern. (Stage 2, the sticker
element, was removed as a product decision — a burned emoji added no
value for the Telugu virality use case and was a recurring bug source.)
"""

import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from services.canvas_coords import to_pixel_center, to_pixel_size, center_to_topleft
from services.fonts import get_font_path

BAR_FPS = 15  # a slow linear reveal doesn't need more; keeps frame count low

# ── User image overlays (Stage: "image" elements) ─────────────────────────
# An image element's props carry an OPAQUE image_id — never a path. The id is
# the exact basename the upload endpoint minted for this clip's video:
# {video_id}_useroverlay_{8 hex}.png|.jpg. resolve_image_overlays() is the
# ONLY place an id becomes a filesystem path, and it pins the id to the
# rendering job's own video_id — so a payload can never reference another
# user's uploads (ownership rides the video, exactly like every other
# rerender artifact) and can never traverse (the regex admits no separators).
_IMAGE_ID_TEMPLATE = r"{video_id}_useroverlay_[0-9a-f]{{8}}\.(?:png|jpg)"


def valid_overlay_image_id(image_id, video_id: str) -> bool:
    """True iff image_id is a well-formed overlay-image basename minted for
    THIS video. Shared by the API boundary (422 early) and the worker-side
    resolver (defense in depth)."""
    if not isinstance(image_id, str) or not video_id:
        return False
    pattern = _IMAGE_ID_TEMPLATE.format(video_id=re.escape(video_id))
    return re.fullmatch(pattern, image_id) is not None


def resolve_image_overlays(elements: list, video_id: str, outputs_dir: str) -> list:
    """Worker-side pre-pass: validate each image element's image_id against
    the job's own video_id and inject the resolved absolute path
    (props._resolved_path) for _prepare_image_layer. Invalid ids and missing
    files are DROPPED with a warning, never rendered and never an error —
    the same forward/backward-safety stance render_elements takes for
    unknown element types. Non-image elements pass through untouched;
    with no image elements the input list is returned as-is (identity), so
    existing payloads take a byte-identical code path."""
    if not elements or not any(
        isinstance(el, dict) and el.get("type") == "image" for el in elements
    ):
        return elements
    resolved = []
    for el in elements:
        if not isinstance(el, dict) or el.get("type") != "image":
            resolved.append(el)
            continue
        image_id = (el.get("props") or {}).get("image_id")
        if not valid_overlay_image_id(image_id, video_id):
            print(f"  [Overlay] Dropping image element {el.get('id')!r}: "
                  f"image_id {image_id!r} is not a valid overlay image for this video",
                  flush=True)
            continue
        path = os.path.join(outputs_dir, image_id)
        if not os.path.exists(path):
            print(f"  [Overlay] Dropping image element {el.get('id')!r}: "
                  f"{image_id!r} not found in outputs", flush=True)
            continue
        resolved.append({**el, "props": {**el["props"], "_resolved_path": path}})
    return resolved


@dataclass
class Layer:
    """A prepared, ready-to-composite overlay layer."""
    path: str          # image (PNG) or video (mov) file
    is_video: bool
    width: int          # pixel dimensions AFTER scale/rotation
    height: int
    ox: int              # top-left position for `overlay=x=ox:y=oy`
    oy: int


def _ffprobe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rotated_bbox(w: int, h: int, rotation_deg: float) -> tuple:
    theta = math.radians(rotation_deg)
    rw = abs(w * math.cos(theta)) + abs(h * math.sin(theta))
    rh = abs(w * math.sin(theta)) + abs(h * math.cos(theta))
    return round(rw), round(rh)


def _rotate_png_if_needed(img: Image.Image, rotation_deg: float) -> Image.Image:
    if not rotation_deg:
        return img
    # expand=True grows the canvas to the new bounding box, keeping the
    # rotation centered — matches to_pixel_center's center-anchor semantics.
    return img.rotate(-rotation_deg, expand=True, resample=Image.BICUBIC)


# ══════════════════════════════════════════════════════════════════════════
# Per-type layer preparation — pure "produce pixels", no video encoding.
# ══════════════════════════════════════════════════════════════════════════

def _draw_bar_frame(bar_w: int, bar_h: int, fill_rgb: tuple, frac: float) -> Image.Image:
    """One frame: translucent white track (full width) + a solid fill from
    the left edge out to `frac` of the width — matches ProgressBody's CSS
    (fill's left edge fixed, only the right edge grows)."""
    img = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = bar_h / 2

    draw.rounded_rectangle([0, 0, bar_w - 1, bar_h - 1], radius=radius,
                            fill=(255, 255, 255, round(0.18 * 255)))

    fill_w = max(round(bar_w * min(frac, 1.0)), 0)
    if fill_w > 0:
        fill_radius = min(radius, fill_w / 2)
        draw.rounded_rectangle([0, 0, fill_w - 1, bar_h - 1], radius=fill_radius,
                                fill=(*fill_rgb, 255))
    return img


def _prepare_progress_layer(element: dict, video_width: int, video_height: int,
                            tmp_dir: str, clip_duration: float) -> Layer:
    """
    Progress bar: the one genuinely time-varying element. Frames are drawn
    in PIL (see module docstring for why, not FFmpeg expressions) and
    encoded once to a small lossless (qtrle) clip — this encode is cheap
    (~2s for an ~800-frame bar at ~1000x40px) because it's a tiny
    resolution, unlike the final full-video composite.
    """
    p = element.get("props", {})
    fill_rgb = _hex_to_rgb(p.get("color", "#7c3aed"))
    width_frac = p.get("width", 0.92)
    height_frac = p.get("height", 0.006)
    scale = element.get("scale", 1) or 1
    rotation = element.get("rotation", 0) or 0

    bar_w, bar_h = to_pixel_size(width_frac, height_frac, video_width, video_height)
    bar_w = max(round(bar_w * scale), 2)
    bar_h = max(round(bar_h * scale), 2)

    n_frames = max(round(clip_duration * BAR_FPS), 1)
    frames_dir = os.path.join(tmp_dir, "progress_frames")
    os.makedirs(frames_dir, exist_ok=True)
    for i in range(n_frames):
        t = i / BAR_FPS
        frame = _draw_bar_frame(bar_w, bar_h, fill_rgb, t / clip_duration)
        frame.save(os.path.join(frames_dir, f"frame_{i:06d}.png"))

    bar_clip = os.path.join(tmp_dir, "progress_bar.mov")
    r = subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(BAR_FPS),
         "-i", os.path.join(frames_dir, "frame_%06d.png"),
         "-c:v", "qtrle", bar_clip],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(f"[Overlay] Progress bar frame encode failed: {r.stderr[-500:]}")

    # Rotation is a static angle (not time-varying), applied once to the
    # whole bar clip via FFmpeg's rotate filter during final compositing
    # (kept as a video-level op since bar_clip is a video, not a PNG).
    out_w, out_h = (bar_w, bar_h) if not rotation else _rotated_bbox(bar_w, bar_h, rotation)
    center = to_pixel_center(element.get("x", 0.5), element.get("y", 0.965), video_width, video_height)
    ox, oy = center_to_topleft(center.cx, center.cy, out_w, out_h)

    return Layer(path=bar_clip, is_video=True, width=out_w, height=out_h, ox=ox, oy=oy)


def _draw_gradient_circle(diameter: int, color1: tuple, color2: tuple) -> Image.Image:
    """A diagonal (top-left -> bottom-right) gradient-filled circle,
    matching CSS `bg-gradient-to-br from-[#7c3aed] to-[#a78bfa]`."""
    size = max(diameter, 1)
    square = Image.new("RGBA", (size, size))
    px = square.load()
    denom = max(2 * (size - 1), 1)
    for y in range(size):
        for x in range(size):
            t = (x + y) / denom
            px[x, y] = (
                round(color1[0] + (color2[0] - color1[0]) * t),
                round(color1[1] + (color2[1] - color1[1]) * t),
                round(color1[2] + (color2[2] - color1[2]) * t),
                255,
            )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    square.putalpha(mask)
    return square


def _prepare_logo_layer(element: dict, video_width: int, video_height: int,
                        tmp_dir: str) -> Layer:
    """
    Logo: the synthetic avatar-circle + handle-text widget LogoBody renders
    today (a decorative placeholder, not an uploaded image — see the
    approved Phase 1 scope note; props.logo_image_path is reserved on the
    schema for a future real-upload feature but not consumed here).
    Matches LogoBody.jsx exactly: circle diameter = fontSize*canvasH*1.8,
    gradient #7c3aed -> #a78bfa (bg-gradient-to-br), avatar letter at
    fontSize*canvasH*0.9 bold white centered in the circle, handle text at
    fontSize*canvasH semibold white/90% with a soft drop shadow.
    """
    p = element.get("props", {})
    text = p.get("text", "@rahul_creator")
    avatar = p.get("avatar", "R")
    font_name = p.get("font", "Manrope")
    font_size_frac = p.get("fontSize", 0.02)
    scale = element.get("scale", 1) or 1
    rotation = element.get("rotation", 0) or 0

    base_size = font_size_frac * video_height * scale
    circle_d = max(round(base_size * 1.8), 4)
    gap = max(round(base_size * 0.3), 2)  # Tailwind gap-1.5, proportional

    font_path = get_font_path(font_name)
    avatar_font = ImageFont.truetype(font_path, max(round(base_size * 0.9), 6))
    text_font = ImageFont.truetype(font_path, max(round(base_size), 6))
    try:
        avatar_font.set_variation_by_axes([700])  # font-bold
        text_font.set_variation_by_axes([600])    # font-semibold
    except (AttributeError, OSError):
        pass  # non-variable fallback font — render at its one built-in weight

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_bbox = probe.textbbox((0, 0), text, font=text_font)
    text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]

    pad = 4  # headroom so the drop shadow isn't clipped at the canvas edge
    canvas_w = circle_d + gap + text_w + pad * 2
    canvas_h = max(circle_d, text_h) + pad * 2
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    circle = _draw_gradient_circle(circle_d, (0x7C, 0x3A, 0xED), (0xA7, 0x8B, 0xFA))
    circle_y = pad + (canvas_h - pad * 2 - circle_d) // 2
    img.paste(circle, (pad, circle_y), circle)

    draw = ImageDraw.Draw(img)
    avatar_bbox = draw.textbbox((0, 0), avatar, font=avatar_font)
    aw, ah = avatar_bbox[2] - avatar_bbox[0], avatar_bbox[3] - avatar_bbox[1]
    ax = pad + (circle_d - aw) / 2 - avatar_bbox[0]
    ay = circle_y + (circle_d - ah) / 2 - avatar_bbox[1]
    draw.text((ax, ay), avatar, font=avatar_font, fill=(255, 255, 255, 255))

    text_x = pad + circle_d + gap
    text_y = pad + (canvas_h - pad * 2 - text_h) / 2 - text_bbox[1]
    draw.text((text_x + 1, text_y + 2), text, font=text_font, fill=(0, 0, 0, 150))  # soft drop shadow
    draw.text((text_x, text_y), text, font=text_font, fill=(255, 255, 255, 230))    # white/90%

    img = _rotate_png_if_needed(img, rotation)
    out_path = os.path.join(tmp_dir, f"logo_{element.get('id', id(element))}.png")
    img.save(out_path)

    center = to_pixel_center(element.get("x", 0.16), element.get("y", 0.07), video_width, video_height)
    ox, oy = center_to_topleft(center.cx, center.cy, img.width, img.height)
    return Layer(path=out_path, is_video=False, width=img.width, height=img.height, ox=ox, oy=oy)


def _prepare_headline_layer(element: dict, video_width: int, video_height: int,
                            tmp_dir: str) -> Layer:
    """
    Headline: static styled text, matching HeadlineBody.jsx — font/weight
    via the shared fonts.py lookup + variable-font weight axis, optional
    uppercase transform, optional 1.5px black stroke (PIL's native
    stroke_width/stroke_fill — same call draws fill+outline correctly
    layered), and a soft drop shadow approximated with a blurred, offset
    duplicate of the text (real CSS text-shadow blur, not just an offset
    copy — cheap here since the canvas is just the headline's own
    bounding box, not the full video).

    1.5px stroke and the CSS text-shadow's "4px 18px" offset/blur are both
    fixed CSS-pixel values inside the editor's fixed 640-tall canvas —
    scaled here by video_height/640 to stay proportionally correct at any
    render resolution, consistent with the coordinate contract.
    letter-spacing (0.02em) is not reproduced — a subtle, purely cosmetic
    gap PIL has no native support for; not worth hand-spacing characters
    for the one property no Inspector control ever changes anyway.
    """
    p = element.get("props", {})
    text = p.get("text", "")
    if p.get("uppercase", False):
        text = text.upper()
    font_name = p.get("font", "Outfit")
    font_size_frac = p.get("fontSize", 0.06)
    color = _hex_to_rgb(p.get("color", "#22ff9c"))
    weight = p.get("weight", 900)
    stroke = p.get("stroke", False)
    scale = element.get("scale", 1) or 1
    rotation = element.get("rotation", 0) or 0

    editor_canvas_h = 640  # HeadlineBody's fixed-px CSS values are relative to this
    px_ratio = video_height / editor_canvas_h

    font_size = max(round(font_size_frac * video_height * scale), 6)
    font_path = get_font_path(font_name)
    font = ImageFont.truetype(font_path, font_size)
    try:
        font.set_variation_by_axes([weight])
    except (AttributeError, OSError):
        pass  # non-variable fallback font — render at its one built-in weight

    stroke_w = max(round(1.5 * px_ratio), 1) if stroke else 0
    shadow_offset = max(round(4 * px_ratio), 1)
    shadow_blur = max(round(18 * px_ratio / 3), 1)  # blur radius, not CSS blur-px 1:1

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    pad = stroke_w + shadow_blur * 2 + shadow_offset + 4
    canvas_w = text_w + pad * 2
    canvas_h = text_h + pad * 2
    draw_x, draw_y = pad - bbox[0], pad - bbox[1]

    # Shadow layer: solid black text, blurred, then offset-composited
    # behind the main text.
    shadow_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow_layer).text(
        (draw_x, draw_y), text, font=font, fill=(0, 0, 0, 255),
        stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
    shadow_alpha = shadow_layer.split()[3].point(lambda a: round(a * 0.55))
    shadow_layer.putalpha(shadow_alpha)

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    img.alpha_composite(shadow_layer, (0, shadow_offset))

    fg = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    ImageDraw.Draw(fg).text(
        (draw_x, draw_y), text, font=font, fill=(*color, 255),
        stroke_width=stroke_w, stroke_fill=(0, 0, 0, 217),  # rgba(0,0,0,0.85)
    )
    img.alpha_composite(fg)

    img = _rotate_png_if_needed(img, rotation)
    out_path = os.path.join(tmp_dir, f"headline_{element.get('id', id(element))}.png")
    img.save(out_path)

    center = to_pixel_center(element.get("x", 0.5), element.get("y", 0.14), video_width, video_height)
    ox, oy = center_to_topleft(center.cx, center.cy, img.width, img.height)
    return Layer(path=out_path, is_video=False, width=img.width, height=img.height, ox=ox, oy=oy)


def _prepare_image_layer(element: dict, video_width: int, video_height: int,
                         tmp_dir: str) -> Optional[Layer]:
    """
    User-uploaded image overlay. Sizing mirrors ImageBody.jsx exactly: the
    element stores a HEIGHT fraction of the canvas (props.height, same
    fraction-of-height convention as fontSize on logo/headline); width
    follows from the image's own natural aspect ratio (the preview <img>
    keeps `width: auto`), so preview and burn derive width from the same
    ratio. element.scale multiplies uniformly (TransformBox), rotation goes
    through the shared _rotate_png_if_needed, and position converts through
    the SAME to_pixel_center/center_to_topleft as every other overlay.
    props.opacity (0-1) multiplies the alpha channel, matching CSS opacity.

    props._resolved_path is injected server-side by resolve_image_overlays
    (never client-supplied — the client only ever sends the opaque
    image_id). No path here → the element was not resolved → skip.
    """
    p = element.get("props", {})
    src = p.get("_resolved_path")
    if not src or not os.path.exists(src):
        print(f"  [Overlay] Skipping image element {element.get('id')!r}: "
              f"no resolved source image", flush=True)
        return None

    height_frac = p.get("height", 0.18)
    opacity = p.get("opacity", 1)
    scale = element.get("scale", 1) or 1
    rotation = element.get("rotation", 0) or 0

    img = Image.open(src).convert("RGBA")
    target_h = max(round(height_frac * video_height * scale), 2)
    target_w = max(round(target_h * img.width / img.height), 2)
    img = img.resize((target_w, target_h), Image.LANCZOS)

    try:
        opacity = float(opacity)
    except (TypeError, ValueError):
        opacity = 1.0
    opacity = min(max(opacity, 0.0), 1.0)
    if opacity < 1.0:
        alpha = img.split()[3].point(lambda a: round(a * opacity))
        img.putalpha(alpha)

    img = _rotate_png_if_needed(img, rotation)
    out_path = os.path.join(tmp_dir, f"image_{element.get('id', id(element))}.png")
    img.save(out_path)

    center = to_pixel_center(element.get("x", 0.5), element.get("y", 0.5),
                             video_width, video_height)
    ox, oy = center_to_topleft(center.cx, center.cy, img.width, img.height)
    return Layer(path=out_path, is_video=False, width=img.width, height=img.height, ox=ox, oy=oy)


_PREPARERS = {
    "progress": lambda el, vw, vh, tmp, dur: _prepare_progress_layer(el, vw, vh, tmp, dur),
    "logo": lambda el, vw, vh, tmp, dur: _prepare_logo_layer(el, vw, vh, tmp),
    "headline": lambda el, vw, vh, tmp, dur: _prepare_headline_layer(el, vw, vh, tmp),
    "image": lambda el, vw, vh, tmp, dur: _prepare_image_layer(el, vw, vh, tmp),
}


# ══════════════════════════════════════════════════════════════════════════
# Orchestration — exactly one full-resolution encode, however many layers.
# ══════════════════════════════════════════════════════════════════════════

def render_elements(input_path: str, output_path: str, elements: list,
                     video_width: int, video_height: int) -> str:
    """
    Burn every visible, supported element onto input_path in exactly ONE
    FFmpeg composite pass, regardless of how many elements are present —
    see module docstring for why this matters. Unsupported/invisible
    elements are skipped (not an error). Returns input_path unchanged
    (zero FFmpeg calls) if there's nothing to burn.

    A visible element whose type is not in _PREPARERS (e.g. a retired
    `sticker` element left in an old draft, or a future type an older
    backend doesn't understand) is skipped with a logged warning rather
    than crashing the render — old payloads stay forward/backward safe.
    """
    supported = []
    for el in (elements or []):
        if not el.get("visible", True):
            continue
        etype = el.get("type")
        if etype == "image" and not (el.get("props") or {}).get("_resolved_path"):
            # Image elements must arrive through resolve_image_overlays (which
            # validates ownership and injects the path). An unresolved one is
            # skipped like an unknown type — never an error, and never a
            # reason to spin up the composite pass.
            print(f"  [Overlay] Skipping unresolved image element "
                  f"(id={el.get('id')!r}) — not burned", flush=True)
            continue
        if etype in _PREPARERS:
            supported.append(el)
        else:
            print(f"  [Overlay] Skipping unsupported element type {etype!r} "
                  f"(id={el.get('id')!r}) — not burned", flush=True)
    if not supported:
        return input_path

    with tempfile.TemporaryDirectory(prefix="overlay_") as tmp_dir:
        duration = _ffprobe_duration(input_path)
        if duration <= 0:
            raise RuntimeError(f"[Overlay] Could not determine duration of {input_path!r}")

        layers = []
        for el in supported:
            layer = _PREPARERS[el["type"]](el, video_width, video_height, tmp_dir, duration)
            if layer is not None:
                layers.append(layer)

        if not layers:
            return input_path

        return _composite_layers(input_path, output_path, layers, duration)


def _composite_layers(input_path: str, output_path: str, layers: list, duration: float) -> str:
    """One ffmpeg call: every layer becomes an input + an overlay node in a
    single filter_complex chain, ending in one full-resolution encode."""
    cmd = ["ffmpeg", "-y", "-i", input_path]
    for layer in layers:
        if layer.is_video:
            cmd += ["-i", layer.path]
        else:
            # A plain PNG input is otherwise a single frame — -loop 1 holds
            # it as an infinite still (shortest=1 below then bounds each
            # stage back down to the base video's own length; -t is a
            # second, independent safety net against ever hanging on an
            # unbounded encode if that chain logic is ever wrong).
            cmd += ["-loop", "1", "-i", layer.path]

    chain_parts = []
    current = "[0:v]"
    for idx, layer in enumerate(layers, start=1):
        next_label = f"[v{idx}]"
        chain_parts.append(
            f"{current}[{idx}:v]overlay=x={layer.ox}:y={layer.oy}:shortest=1{next_label}"
        )
        current = next_label

    cmd += [
        "-filter_complex", ";".join(chain_parts),
        "-map", current, "-map", "0:a?",
        "-t", str(duration),
        "-c:v", "libx264", "-c:a", "aac", "-preset", "fast", "-crf", "23",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"[Overlay] Composite failed: {r.stderr[-500:]}")
    return output_path


# ══════════════════════════════════════════════════════════════════════════
# Backward-compatible direct entry point (used by Stage 1's own tests).
# ══════════════════════════════════════════════════════════════════════════

def render_progress_bar(input_path: str, output_path: str, element: dict,
                         video_width: int, video_height: int) -> str:
    """Single-element convenience wrapper around the shared pipeline —
    kept so existing direct callers/tests don't need an elements list."""
    element = {**element, "type": "progress"}
    return render_elements(input_path, output_path, [element], video_width, video_height)
