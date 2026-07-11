"""
ClipForge AI — Canvas Coordinate Conversion
=============================================
The ONE place normalized (0-1) EditDocument coordinates convert to render-
resolution pixels. Every overlay element (progress bar, logo, headline,
sticker) must go through this module — no other file should do its own
normalized-to-pixel math.

Frontend anchor convention (matches the editor canvas's positioning wrapper,
ElementRenderer.jsx / StaticElementLayer.jsx): element.x/y is the element's
CENTER point, expressed as a fraction of canvas width/height —
`left: x*100%, top: y*100%, transform: translate(-50%,-50%)`. width/height-
type props (e.g. the progress bar's `width`/`height`) are fractions of the
render's actual dimensions at whatever aspect ratio was selected — NOT the
frontend's fixed-editor-canvas-specific `canvasW = canvasH*9/16` shortcut,
which only holds because the *editor's own preview* is always a 9:16 box.
On the backend, a clip can render at 9:16, 1:1, or 16:9, so "92% width"
means 92% of that render's actual width, whichever aspect was chosen.

Captions are a deliberate exception (see caption_renderer.py) — they use
their own long-standing percent-of-frame formula for backward compatibility,
not this center-fraction convention.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PixelCenter:
    cx: int
    cy: int


def to_pixel_center(x: float, y: float, video_width: int, video_height: int) -> PixelCenter:
    """Normalized center-fraction (0-1) -> pixel center point."""
    return PixelCenter(cx=round(x * video_width), cy=round(y * video_height))


def to_pixel_size(width_frac: float, height_frac: float,
                   video_width: int, video_height: int) -> tuple:
    """Normalized width/height fractions -> (pixel_width, pixel_height),
    relative to the actual render dimensions at whatever aspect ratio was
    selected for this export."""
    return round(width_frac * video_width), round(height_frac * video_height)


def center_to_topleft(cx: int, cy: int, width: int, height: int) -> tuple:
    """Center-anchored pixel point -> top-left corner, for FFmpeg primitives
    (overlay/drawbox/drawtext) that all anchor at their top-left corner.
    Pass the overlay's ACTUAL width/height (after scale and rotation, if
    any) — a rotated image's bounding box grows, and the center must stay
    fixed relative to the new, larger box."""
    return cx - width // 2, cy - height // 2
