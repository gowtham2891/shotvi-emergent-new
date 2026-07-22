# DIAGNOSIS: Exported captions silently fall back to Nirmala UI instead of the chosen font

> **RESOLVED 2026-07-13** — fix shape (b→a hybrid: flat canonical fontsdir) implemented.
> The three caption .ttfs now live byte-identically (md5-verified) as immediate children of
> `services/assets/fonts/captions/` (licenses in `captions/licenses/`), and
> `CAPTION_FONTS_DIR` points there. Verified via libass's own log on the production burn
> command: `fontselect: (Ramabhadra, 700, 0) -> Ramabhadra`, `(Noto Sans Telugu, 700, 0) ->
> NotoSansTelugu-Regular`, `(Mandali, 700, 0) -> Mandali` — no Arial/Nirmala fallback.
> Regression-guarded by `tests/test_caption_font_resolution.py` (layout flatness, internal
> family-name == ASS Fontname, and a real-burn fontselect probe).

**Date:** 2026-07-13 · **Scope:** read-only diagnosis, no code changed.
**Symptom:** editor preview renders the chosen caption font (e.g. Ramabhadra) correctly; the exported .mp4 renders a different, lighter font. Earlier, "Noto Sans Telugu" and "Ramabhadra" exports of the same clip were visually identical.

---

## ROOT CAUSE

**The hypothesis is confirmed in mechanism but NOT in the suspected sub-cause.** There is no
name mismatch. Every ASS `Fontname` exactly equals the .ttf's internal family name. The bug is
**hypothesis (b): fontsdir points somewhere the chosen .ttf isn't** — one level too high.

`services/fonts.py:63` hands libass the **parent** directory:

```python
CAPTION_FONTS_DIR = FONTS_DIR        # = services/assets/fonts
```

but the .ttf files live one level **below** it, in per-font subdirectories
(`services/assets/fonts/ramabhadra/Ramabhadra-Regular.ttf`, etc.). **libass's `fontsdir` scan is
non-recursive** — it `fopen()`s each directory entry as if it were a font *file*. Every entry in
`services/assets/fonts/` is a subdirectory, every fopen fails, **zero bundled fonts are loaded**,
and libass silently falls back to the system font provider (DirectWrite on this machine), which
resolves the Telugu glyphs to **Nirmala UI** — the lighter font the owner saw.

Empirical proof — a probe burn with the production wiring (`fontsdir` = the parent
`services/assets/fonts`), ffmpeg 8.0.1 / libass 0.17.4, `-v verbose`:

```
Loading font file 'd:/clipforge-ai/shotvi-emergent-new/services/assets/fonts\mandali'
ass_read_file(...fonts\mandali): fopen failed
Loading font file '...fonts\manrope'           → fopen failed
Loading font file '...fonts\noto-sans-telugu'  → fopen failed
Loading font file '...fonts\outfit'            → fopen failed
Loading font file '...fonts\ramabhadra'        → fopen failed
Using font provider directwrite (with GDI)
fontselect: (Ramabhadra, 700, 0) -> Arial-BoldMT, 0, Arial-BoldMT
Glyph 0xC2A not found, selecting one more font for (Ramabhadra, 700, 0)
fontselect: (Ramabhadra, 700, 0) -> NirmalaUI-Bold, 1, NirmalaUI-Bold
```

Control — identical ASS, `fontsdir` pointed at a **flat** directory containing
`Ramabhadra-Regular.ttf` directly:

```
Loading font file 'flatfonts\Ramabhadra-Regular.ttf'      ← loads, no fopen failure
fontselect: (Ramabhadra, 700, 0) -> Ramabhadra, 0, Ramabhadra   ← correct font selected
```

So the name matching works perfectly the moment libass can actually see the file. The directory
layout is the entire bug.

Note: the comment at `services/fonts.py:60-62` ("libass indexes the tree") documents the wrong
assumption — libass does **not** index a tree, only a single flat directory.

---

## 1. ASS GENERATION — Fontname is derived correctly (not the bug)

`generate_ass_karaoke` (`services/caption_renderer.py`) derives the Style `Fontname` from the
chosen font, not hardcoded:

```python
font_family, _ = get_caption_font(caption_font)          # line 515 — deterministic family name
...
Style: Default,{font_family},{font_size},...             # line 556 — written into the ASS
```

`get_caption_font` (`services/fonts.py:66-73`) passes the frontend value through **verbatim** when
it's a known key, falling back to the default otherwise:

```python
CAPTION_FONTS = {
    "Noto Sans Telugu": ...noto-sans-telugu/NotoSansTelugu-Regular.ttf,
    "Ramabhadra":       ...ramabhadra/Ramabhadra-Regular.ttf,
    "Mandali":          ...mandali/Mandali-Regular.ttf,
}
```

Frontend font id → ASS Fontname mapping (frontend sends the same strings —
`frontend/src/api/renders.js:33` `CAPTION_FONTS = ["Noto Sans Telugu", "Ramabhadra", "Mandali"]`,
serialized as `caption_font` verbatim):

| Frontend font id | ASS `Fontname` written |
|---|---|
| `Noto Sans Telugu` (or omitted) | `Noto Sans Telugu` |
| `Ramabhadra` | `Ramabhadra` |
| `Mandali` | `Mandali` |

The per-style `font_name` entries in `STYLES` (e.g. `"Noto Sans Telugu SemiBold"` at
`caption_renderer.py:41`) are **dead** — never written to the ASS (Stage 5 decoupled font from
preset, per the docstring at line 471-474).

The worker log line the owner saw ("Generating captions [bold-yellow / Ramabhadra]",
`caption_renderer.py:713`) prints `caption_font` *after* it passed the known-key check — so the
correct name genuinely reached the ASS. The failure is at libass load time, exactly as suspected.

## 2. FONT FILES — internal family names (read from the TTF `name` tables directly)

Read with a raw name-table parser (fontTools unavailable; names below are from the Windows/en-US
platform=3 records, **not** guessed):

| File (under `services/assets/fonts/`) | Family (id 1) | Full name (id 4) | PostScript (id 6) |
|---|---|---|---|
| `noto-sans-telugu/NotoSansTelugu-Regular.ttf` | `Noto Sans Telugu` | `Noto Sans Telugu Regular` | `NotoSansTelugu-Regular` |
| `ramabhadra/Ramabhadra-Regular.ttf` | `Ramabhadra` | `Ramabhadra` | `Ramabhadra` |
| `mandali/Mandali-Regular.ttf` | `Mandali` | `Mandali` | `Mandali` |

## 3. THE MATCH — all three PASS on the string level

| Font | ASS `Fontname` | Internal family name | Exact match |
|---|---|---|---|
| Noto Sans Telugu | `Noto Sans Telugu` | `Noto Sans Telugu` | **PASS** |
| Ramabhadra | `Ramabhadra` | `Ramabhadra` | **PASS** |
| Mandali | `Mandali` | `Mandali` | **PASS** |

There are **no FAIL rows in the name table** — the control burn proves libass matches
`Ramabhadra` → `Ramabhadra-Regular.ttf` instantly once the file is loadable. The FAIL is
upstream: **none of the three files is ever loaded**, because `fontsdir` doesn't contain them —
it contains only the sub*directories* that contain them.

## 4. FONTSDIR WIRING — the actual defect

`burn_captions` (`services/caption_renderer.py:631-657`) builds:

```python
from services.fonts import CAPTION_FONTS_DIR
...
"-vf", f"ass='{ass_filter}':fontsdir='{fonts_dir}'",
```

with `fonts_dir` = `CAPTION_FONTS_DIR` = `d:/clipforge-ai/shotvi-emergent-new/services/assets/fonts`
(escaped to `d\:/...` for the filter arg). The path **is** absolute and correct in the worker's
runtime context — it derives from `services/fonts.py`'s own `__file__`, independent of CWD, and
the export path (`api/worker.py:335` → `render_captions_for_clip` → `burn_captions`) uses this
single code path. The directory exists and libass receives it — the verbose log shows libass
enumerating exactly its five entries. But those entries are directories
(`mandali/ manrope/ noto-sans-telugu/ outfit/ ramabhadra/`), each fopen fails, and the requested
`.ttf` is therefore **not** in fontsdir in the sense libass cares about (immediate children only).

Why the test suite missed it: `tests/test_caption_font.py` asserts the Fontname **string** in the
generated ASS text; it never runs a burn, so libass's failure to load the files was invisible.

## 5. PREVIEW vs EXPORT DIVERGENCE

The preview loads fonts by URL, not by directory scan: `frontend/public/fonts.css` declares
`@font-face { font-family: "Ramabhadra"; src: url("/fonts/Ramabhadra-Regular.ttf") }` (fetched
via `<link>` from `public/index.html`), and the caption element sets `font-family: "Ramabhadra",
"Noto Sans Telugu", sans-serif` (`captionStylePreview.js:155-159`). The browser is *told the
file path directly*, so the CSS family name only has to match its own `@font-face` declaration —
resolution can't miss. The burn instead matches by *name lookup over a scanned directory*: libass
must first discover the .ttf by enumerating `fontsdir`, then match the ASS Fontname against the
discovered fonts' internal names. The frontend and backend even use **byte-identical files**
(md5-verified: `frontend/public/fonts/*.ttf` ≡ `services/assets/fonts/*/*.ttf`) and the same
family strings — the sole divergence is that the browser's mechanism binds name→file explicitly,
while libass's discovery step comes up empty because the files sit one directory level deeper
than the scan reaches. Same fonts, same names, one loader that never finds the files.

---

## WHY BOTH EARLIER EXPORTS LOOKED IDENTICAL — CONFIRMED

Both "Noto Sans Telugu" and "Ramabhadra" exports fell back to the **same** system font. With zero
fonts loaded from fontsdir, every request takes the identical DirectWrite fallback path: Latin
glyphs → Arial, Telugu glyphs (e.g. U+0C2A ప, "Glyph 0xC2A not found") → **Nirmala UI** — the only
Telugu-capable font Windows ships. The requested family name only changes the string in the failed
lookup; the substituted font is the same either way, hence pixel-identical Telugu output. (On a
Linux container without a Telugu system font this same bug would render tofu instead.) This also
matches "lighter font": Nirmala UI's Telugu is visibly lighter than Ramabhadra's dense strokes.

## FIX SHAPE (sketch only — not implemented)

**(b) fix fontsdir — the ASS strings and the .ttf files are both already correct.** Give libass a
flat directory whose *immediate* children are the .ttf files: either point `CAPTION_FONTS_DIR` at
a flat `fontsdir` staging directory containing (copies of) the five .ttfs, or have the burn step
assemble/verify such a flat dir at render time from `CAPTION_FONTS`' known file paths. Nothing
moves on the ASS-Fontname side and the source .ttf files stay untouched; additionally, a burn-time
guard (fail loudly if any `CAPTION_FONTS` path is not an immediate child of the dir passed to
`fontsdir`) plus one shaping-style test that actually runs ffmpeg and greps for `fopen failed` /
`fontselect` fallback lines would prevent silent regression.
