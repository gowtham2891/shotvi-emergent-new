# Burn-in / Caption Pipeline — Invariants (do not break)

Hard-won rules from the preview/export parity ("burn-in") project. Each was
established empirically and has a test or a documented rationale. Breaking one
silently reintroduces a shipped bug. Read before touching the caption or overlay
render path.

## 1. `ass=` filter ONLY — `subtitles=` is FORBIDDEN
Caption burn-in (`services/caption_renderer.py :: burn_captions`) must use ffmpeg's
`ass=` filter. The `subtitles=` filter **mis-shapes Telugu below-base (vattu/ottu)
conjuncts** on the production libass build — e.g. `ప్ర` decomposes — while `ass=`
shapes them correctly (same binary, same font; proven against a real shipped export).
Guarded by `tests/test_caption_shaping.py :: test_burn_captions_uses_ass_filter_not_subtitles`
(intercepts the real `-vf` arg). Never weaken that guard; never switch filters.

## 2. Single-pass compositing
Overlay elements (progress/logo/headline/sticker) each prepare a layer (PNG, or a
short clip for the animated progress bar) with **zero** video encoding, and
`services/overlay_renderer.py :: render_elements` composites them in **one** final
full-resolution `libx264` pass. The full-res re-encode dominates cost (~19s of ~23s),
so per-element passes would stack ~linearly. Do not add per-element encode passes.
Captions are their own separate pass (after overlays); keep it that way.

## 3. Bundled caption fonts + calibration are SPEC
Caption fonts are bundled OFL files resolved via the `ass` filter's `fontsdir`
(`services/fonts.py :: CAPTION_FONTS / CAPTION_FONTS_DIR`) — **never** host fontconfig.
Default Noto Sans Telugu; Ramabhadra/Mandali selectable. The cap-height coefficients
`k` (Latin cap-px per point, **measured via the `ass` filter** on the bundled files)
are the calibration spec:

    Noto Sans Telugu = 0.495   Ramabhadra = 0.660   Mandali = 0.660

`caption_font_size` (services/caption_renderer.py) anchors each preset on Noto at its
current nominal size; the others scale to match Noto's cap-height. **Do NOT bump the
Noto anchor sizes** — the editor preview renders system Noto at ~31px cap @ nominal 62,
matching this bundled-Noto export, so current sizing already gives preview/export size
parity (rationale + measurement: `telugu_font_samples/PREVIEW_vs_export_size.png`).
These `k` values supersede the Phase-A `subtitles`-filter numbers (that filter is
forbidden — see §1). Suranna/Gidugu were dropped from captions (too light).

## 4. Normalized 0–1 coords → pixels ONLY in `canvas_coords`
The editor stores every position as a 0–1 **center** fraction; payloads stay normalized
end-to-end (never pixels). The single server-side conversion point is
`services/canvas_coords.py :: to_pixel_center(x, y, video_width, video_height)`. Caption
X/Y positioning (`\an5\pos` in `generate_ass_karaoke`) and every overlay element convert
there — no other file does normalized→pixel math. When emitting `\pos`, `PlayResX/Y`
must equal the same `video_width/video_height` used for the conversion so `\pos` lands at
literal output pixels on every aspect ratio (this is structural in `generate_ass_karaoke`).

## 5. The caption-path regression gate (byte-identical / SSIM ≈ 1.0)
Any change to the caption render path must prove that drafts which do **not** use the new
behavior render **identically to before**. Pattern (used for Stage 6, reproduce it):
render caption-only exports with the new fields unset across `{single, multi-line} ×
{≥2 presets} × {9:16, 1:1}`, on `HEAD` vs the working tree via `git stash`, and assert
**per-frame SSIM ≥ 0.999** (target 1.0 / `.ass` byte-identical, frame max-diff 0). New
behavior (positioned captions, new fonts, etc.) is gated **visually** instead, via labeled
grids in `telugu_font_samples/`. The clean way to keep the gate trivially passable is to
leave the default code path untouched and branch only when the new field is provided.
