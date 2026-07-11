# Known Issues / Follow-ups

Tracked deferrals — each is safe to ship without, but should be addressed later.

## Captions

### (a) Worker does not thread caption position / output dimensions to the burn
`api/worker.py` calls `render_captions_for_clip()` without `caption_position`,
`video_width`, or `video_height`, so caption burn uses the defaults (84 / 1080 / 1920).

Effect: the editor's per-clip caption Y (`captionY` in the rerender payload) and the real
output dimensions for non-9:16 formats (16:9, 1:1) do **not** yet flow to export — the
capability exists in `generate_ass_karaoke()`/`render_captions_for_clip()` but is unwired.

Fix: thread the payload's `captionY` (→ `caption_position`) and the resolved format
`width`/`height` (from `FORMAT_CONFIG`) into the `render_captions_for_clip()` call. This is
the payoff wiring that makes user caption positioning and correct non-9:16 canvases actually
reach the exported video.

**Stage 6 — RESOLVED for positioned captions.** `caption_x`/`caption_y` (0–1) now thread
`RerenderRequest → main.py → worker → render_captions_for_clip → generate_ass_karaoke`, and
the worker passes the real `target_w/target_h` **only when the caption was dragged**. An
untouched caption still uses the defaults on purpose (the regression gate requires it to be
byte-identical to today); positioned captions get real dims + `\pos`.

### (b) Dead `margin_bottom` fields in `STYLES` — RESOLVED (Commit 6)
Since `generate_ass_karaoke()` derived `MarginV` from `caption_position` (and
after Commit 4 no longer needs `MarginV` at all — every event carries an
explicit `\an5\pos`), the per-style `margin_bottom` values in
`services/caption_renderer.py :: STYLES` were dead code. **Removed in Commit 6.**
No other reader references them.

### (c) Caption vertical anchor mismatch (export bottom-anchored vs preview center-anchored) — RESOLVED (Commit 4)
Historically the export placed captions with ASS `\an2` (bottom-anchored
`MarginV`), while the editor preview centers the caption block via
`translate(-50%,-50%)`. The bottom stayed a stable ~10px below the `y·H` line
regardless of line count; the preview center stayed on it. So placement
matched for a single line but drifted for taller captions (single line ~15px
offset, wrapped 2-line ~52px offset on 1080×1920).

**Commit 4 resolves this for every caption — untouched and dragged alike.**
`generate_ass_karaoke` now emits an explicit `{\an5\pos(cx,cy)}` on every
karaoke event; the untouched default `(cx,cy)` is derived from the frontend's
own default (`x=0.5`, `y=0.82` — `CAPTION_DEFAULT_X_FRAC/Y_FRAC`) so preview
and export center at the same output pixel on every aspect ratio and every
line count. The dual-code-path drift is gone.

### (e) Caption drag range is unconstrained (can be dragged off-frame) — RESOLVED (Commit 5)
Historically the caption's on-canvas drag only clamped the CENTER point to a
uniform `(0.02, 0.98)`, so the rendered text bounding box could still spill
past the frame edge — especially on wide multi-word Telugu captions. Since
`\an5\pos` in the export uses the exact dragged coords (WYSIWYG), any preview
overflow reappeared 1:1 in the burn.

**Commit 5 clamps the caption drag range using the measured bounding box +
current video dims** (see `frontend/src/lib/clampToFrame.js`, wired into
`ElementRenderer.jsx`), so no edge of the caption box crosses the frame in
the editor — and, because the same `(caption_x, caption_y)` is what the burn
uses, none crosses in the export either. Oversized captions (text wider than
the frame) symmetric-overflow around center 0.5 rather than sliding entirely
off one edge.

### (d) Preview caption font is non-deterministic across machines — RESOLVED (Commit 3)
Historically the editor caption preview used the CSS chain
`"Noto Sans Telugu", "Nirmala UI", sans-serif` but **Noto Sans Telugu was
not loaded as a web font** — only Inter/Outfit/Manrope/JetBrains Mono were.
So the preview's Telugu font depended on what the viewer's machine had
installed: on a box with Noto Sans Telugu present, it matched the
deterministic bundled-Noto export; on a machine without it, the preview fell
back to Nirmala UI (or the OS default), which did NOT match the export.

**Commit 3 loads the three bundled OFL caption fonts (Noto Sans Telugu,
Ramabhadra, Mandali) as `@font-face` web fonts in `frontend/src/index.css`
from `/fonts/*.ttf`** — those paths are symlinks to
`services/assets/fonts/*/*.ttf`, the SAME `.ttf` files the backend hands to
libass via `fontsdir`. Byte-identical font files → identical shapes on
preview and export on every machine, regardless of what fonts the viewer's
OS has installed. The Nirmala UI fallback was removed from the CSS stack in
`data/captionStylePreview.js` so it can't silently drift the preview again.

### Correction — HONEST_baseline_prod_vs_stage5.png is mislabeled
The top panel of `telugu_font_samples/HONEST_baseline_prod_vs_stage5.png` is labeled
"current production (host fallback = Nirmala)" but actually renders **`Noto Sans Telugu
SemiBold`** (cap-height ~41px @ nominal 62), NOT the Nirmala fallback (~34px). The label was
based on a stale assumption from before Noto Sans Telugu was installed on this machine.
`PREVIEW_vs_export_size.png` (later) has the correct three-way comparison: system Noto (31px)
= bundled Noto (31px) ≠ Nirmala (34px) ≠ "Noto Sans Telugu SemiBold" (41px).
