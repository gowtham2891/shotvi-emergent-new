# DIAGNOSIS — TRUE COLOR EMOJI in Burned Captions (feasibility + positioning spike)

**Status:** Research only. **No app code changed. No git commands run.** All test
work lives in the session scratch dir
(`…/scratchpad/emoji_color/`); this file is the report.

**Question:** The owner wants real color emoji burned into karaoke captions. The only
known path is compositing color emoji **images** over the video. Is that feasible, what
is the best approach, and what does it really cost?

---

## Short answer (plain language)

**It works, and it works better than expected. Verdict: GO (with caveats).**

I burned `మీరు 🔥 super 😂 content` through the real caption path and got **true color
emoji, sitting in exactly the right place, inline with the Telugu and Latin text**, in
**one** ffmpeg command with **one** encode. Artifact:
`scratchpad/emoji_color/single_out.mp4` / frame `f_single_1.0.png`.

The hard part was supposed to be *positioning* — libass does the intra-line layout
internally and never tells us where each word lands. The solution turned out to be to
**stop trying to compute it and instead ask libass**:

1. Replace each emoji in the ASS with an **invisible placeholder box** that occupies the
   emoji's slot. libass lays the line out normally, around that box.
2. Render the **same ASS** once with that box turned **opaque and uniquely colored**, on a
   blank background — a "probe". Find the colored box with numpy. That rectangle is where
   libass put the emoji slot, exactly.
3. In the real burn, the box is invisible and we `overlay` the emoji PNG **onto the
   measured rectangle**.

Because both renders go through the *same real libass*, alignment is **exact by
construction** — not approximated, not re-derived. The proof: making the box transparent
does **not** move anything (`probe` and `final` had byte-identical ink extents
`x[400..681]`). Nothing is "computed to match" libass; libass tells us the answer.

Three findings make this much cheaper and safer than the prior diagnosis feared:

- **Emoji positions are static across the karaoke sweep.** The emoji rectangle was
  **pixel-identical (max diff 0)** at every karaoke frame while the text around it
  changed color. So we measure **once per caption line**, not per frame.
- **It works on wrapped multi-line captions for free.** In the multi-line test the
  caption wrapped to two lines and both emoji landed correctly on the **second** line —
  and I never computed the wrap. libass decided it, the probe read it back.
  (`f_multi_3.4.png`)
- **It removes the Linux landmine instead of inheriting it.** The emoji character never
  reaches libass at all (final ASS contains **0 emoji codepoints**), so there is **no
  font fallback** — verified: libass resolves only `NotoSansTelugu-Regular` from
  `fontsdir`, with **no** `Glyph 0x1F525 not found` and **no** Segoe fallback. Emoji
  become fully host-independent. This *fixes* the blank/tofu-on-Linux problem in
  `DIAGNOSIS_EMOJI.md` §3 rather than working around it.

The honest costs: it adds a **measure step** (~116 ms per caption line *that contains an
emoji* — typically ~0.3 s per clip, and **zero** for the ~99% of captions with no emoji),
a new **calibration constant**, a runtime dependency on numpy/PIL in the burn path, and —
to avoid re-introducing preview/export drift — a **frontend change** so the editor
preview draws the *same PNG* instead of the host's emoji font.

**Rough effort: 8–12 dev-days.**

---

## 1. The positioning crux — approaches ranked

| | Approach | Reliability | Effort | Verdict |
|---|---|---|---|---|
| **B** | **Placeholder box + probe render** | **Exact by construction** (uses real libass) | Medium | ✅ **CHOSEN — proven working** |
| A | Extract positions from libass directly | Exact in principle | High / blocked | ❌ Not viable here |
| C | Re-implement layout outside libass | Drift-prone | High | ❌ Rejected |

### A) Extract positions from libass — not viable, without forking

`ass_render_frame()` does return per-bitmap `x/y/w/h`, so this is sound *in theory*. It
fails on packaging, not on concept:

- **No Python binding exists.** `pip download libass` → *"No matching distribution
  found"*. (`ass` on PyPI is a subtitle **parser**, no renderer/layout.)
- **Our FFmpeg is a static build** (`8.0.1-full_build-www.gyan.dev`, `--enable-static`);
  libass is compiled **in**. There is no `libass.dll` to `ctypes` into.
- So this means shipping and version-pinning a **second, separate** libass alongside the
  one inside FFmpeg — and then *guaranteeing the two lay out identically*. If they ever
  diverge (different version, build flags, HarfBuzz/FriBidi, font provider), positions
  silently drift. That is a worse version of the very problem we are solving.

Approach B gets the same information out of **the exact binary that does the burn**, with
no new native dependency.

### B) Placeholder box + probe render — CHOSEN, proven

The mechanism, and the evidence for each step:

**1. An inline ASS drawing takes part in layout.** (`probe1.py`)
Adding a `{\p1}` box widened the line `x[437..643]` → `x[400..681]` and re-centered it —
i.e. libass treats it as a glyph and reserves its advance.

**2. Alpha does not affect layout — the load-bearing fact.** (`probe1.py`)

```
textonly   ink x[437..643]
probe      ink x[400..681]   <- box opaque  (magenta box detected x[494..555])
final      ink x[400..681]   <- box transparent, SAME extents, no magenta
```

The visible-box render and the invisible-box render are **geometrically identical**. So
what we measure in the probe is exactly what the burn does. This is why alignment is
exact rather than approximate.

**3. The probe is unambiguous.** In the probe the *text* is also set to alpha `FF` — so
the probe frame contains **only** the boxes on black. Each emoji slot gets its own color,
so multiple emoji per line are separable, and there is no possible collision with the
yellow karaoke highlight.

**4. Placement is calibrated, and errors are bounded.** (`probe3.py`, `probe4.py`,
`probe5.py`) Shifting the drawing's own coordinates is **exactly 1:1** in output pixels
(D=20→+20px, D=40→+40px, D=60→+60px), which gives clean vertical control. `\pbo` is
**not** usable (16 units moved the box only 8px — non-linear). With the box locked to a
**1em square (S = font size)**, the drawing-origin→baseline offset is a stable
**0.85 × size**, and — usefully — **font-independent**:

```
font                   size   origin->baseline   k = off/size
Noto Sans Telugu         40         34             0.850
Noto Sans Telugu         62         53             0.855
Noto Sans Telugu         86         73             0.849
Ramabhadra               62         54             0.871
Mandali                  86         73             0.849
```

So: `S = round(1.0 × fs)`, `D = round((0.85 + 0.10) × fs)` places the box bottom 0.1em
below the baseline (the standard Twemoji inline convention).

> **Why the 0.85 constant is low-risk:** the box both **reserves** the space *and*
> **receives** the emoji. So even if 0.85 is slightly off, the emoji still lands exactly
> in the slot that was reserved for it — it can never overlap or gap against the text.
> A wrong constant costs a **1–2px cosmetic baseline nudge**, not a structural
> misalignment. (Locking `S = fs` matters: the offset only stays a clean constant at a
> fixed `S/fs` ratio — `probe5.py` shows it goes non-linear if `S` floats.)

**5. Karaoke is layout-static — confirmed empirically.** (`probe2.py`, `verify.py`)
Box position under all three karaoke colors:

```
unspoken white     box=(412,1472,473,1531)  IDENTICAL
highlight yellow   box=(412,1472,473,1531)  IDENTICAL
spoken grey        box=(412,1472,473,1531)  IDENTICAL
```

And in the finished video, the emoji rectangle across the sweep:

```
t=1.0s maxdiff=0  STATIC      t=2.2s maxdiff=0  STATIC
t=1.6s maxdiff=0  STATIC      t=3.0s maxdiff=0  STATIC
   (control: text region maxdiff=255 at t=3.0 -> the sweep IS live)
```

Karaoke changes **color only, never layout** — as the spec assumed. **One probe per line
is sufficient**, and the emoji correctly does *not* tint with the highlight.

### C) Re-implement layout outside libass — rejected

Not needed, and it is precisely the drift-prone WYSIWYG trap Stage 6 avoided: it would
mean reproducing libass's shaping, kerning, wrapping and `\an5` centering for Telugu
conjuncts in Python and hoping the two agree forever. Approach B makes it unnecessary.

---

## 2. The spike — what actually ran

Through the real caption path (`generate_ass_karaoke` / `burn_captions` mirrored into
`scratchpad/emoji_color/spike.py`, production geometry: 1080×1920, Noto Sans Telugu,
`bold-yellow` fs=62, `{\an5\pos(540,1574)}` at the default 0.5/0.82 anchor):

### ① Inline color emoji — **PASS** → `f_single_1.0.png`, `single_out.mp4`

`మీరు 🔥 super 😂 content` — both emoji render in **full color**, inline, baseline-aligned,
correctly spaced. Telugu and Latin unaffected. Measured slots:

```
slot 0 U+1F525 line0  rect x=375 y=1530 62x62  visible 0.20-3.50s
slot 1 U+1F602 line0  rect x=574 y=1530 62x62  visible 0.20-3.50s
```

**No placeholder residue:** a saturated-color scan of the final frame found `magenta=0`,
and the only 2 "cyan" pixels were at (588,1565)/(589,1581) — **inside 😂's own rect**, RGB
(79,163,237): the blue tears in the artwork, not a leak. The invisible box leaves
**nothing** behind.

### ② Multi-line (wrapped) caption, emoji on the second line — **PASS** → `f_multi_3.4.png`

An 8-word Telugu caption **wrapped to two visual lines**; 🔥 and 💯 both landed on the
**second** line, correctly inline (`y=1561`), with conjuncts (`అద్భుతమైన`,
`చేస్తున్నారు`) shaped correctly. **The wrap was never computed by me** — libass wrapped,
the probe measured the result. Wrap-agnostic by construction, which is exactly the
property this feature needs.

### ③ Single filtergraph — **PASS** (§3)

### ④ Failure modes observed

| Mode | Reality |
|---|---|
| **Color-space shift in the probe** | **Hit this.** ffmpeg auto-negotiates the `ass` filter into YUV; the RGB round-trip **range-compressed** the boxes (`255→235`, `0→16`), so exact color matching **failed**. Fix: classify by **nearest palette color** on bright pixels (probe contains only boxes ⇒ unambiguous). Must be tolerant in prod — the exact values may differ on a Linux ffmpeg build. |
| Off-by-N px | None structurally. Box is measured, not predicted. Residual is a ≤1–2px cosmetic baseline nudge from the 0.85 constant. |
| Drift on wrap | **None** — wrap handled by libass, read back by probe (case ②). |
| Wrong line | **None** — the measurement is a pixel rect; it cannot name the wrong line. |
| Timing edges | `enable='between(t,…)'` is inclusive and frame-quantized; tie the window to the **line's** start/end (all its karaoke events), not the word's. Emoji appear/disappear with their line. |
| Box you can't fill | Structurally prevented — see the fallback rule (§7). |

---

## 3. The single-filtergraph command (verbatim, this is what produced `single_out.mp4`)

**One** ffmpeg invocation, **one** libx264 encode. Text stays `ass=` + `fontsdir`; emoji
are `overlay` nodes in the *same* graph. No second pass, no re-encode.

```bash
ffmpeg -y \
  -i clip_vertical.mp4 \
  -i assets/emoji/1f525.png \
  -i assets/emoji/1f602.png \
  -filter_complex "
     [0:v]ass='<ass_path>':fontsdir='<fonts_dir>'[cap];
     [1:v]scale=62:62:flags=lanczos[e0];
     [cap][e0]overlay=x=375:y=1530:enable='between(t,0.200,3.500)'[v0];
     [2:v]scale=62:62:flags=lanczos[e1];
     [v0][e1]overlay=x=574:y=1530:enable='between(t,0.200,3.500)'[v1]
  " \
  -map "[v1]" -map "0:a?" \
  -c:v libx264 -preset fast -crf 23 -c:a aac \
  out.mp4
```

`x/y/w/h` come **only** from the probe measurement. `enable` is the line's visibility
window. With no emoji, this collapses back to today's exact `-vf ass=…` command.

**Probe cost** (`timing.py`): **116 ms per caption line**, on a `lavfi` color source — **no
video decode, no encode**. Only lines *containing* an emoji need probing:

```
clip with 10 caption lines -> ~1.2 s   (worst case: every line has an emoji)
clip with 20 caption lines -> ~2.3 s
reference: caption burn of the 4s test clip = 0.76 s (a real 30-60s clip burn is ~20s+)
```

Realistically 1–3 emoji lines per clip ⇒ **~0.1–0.4 s added**, against a ~20 s burn.
**Zero** cost when a clip has no emoji.

---

## 4. Feasibility verdict

### **GO — WITH CAVEATS.** Rough effort: **8–12 dev-days.**

The core mechanism is proven end-to-end and is *architecturally clean* (it defers to
libass rather than second-guessing it). The caveats are integration work, not unknowns.

| Work | Days |
|---|---|
| Emoji segmentation + slot model + asset manifest/resolver + fallback chain | 1.5 |
| ASS placeholder emission (probe/final variants) in `generate_ass_karaoke` | 1.0 |
| Probe render + measure module (ffmpeg lavfi + tolerant detection) | 1.5 |
| Filtergraph assembly in `burn_captions` (N overlays, enable windows, dedupe) | 1.5 |
| Asset bundling (Noto Color Emoji PNGs) + license + build step | 0.5 |
| Wire hardening + validation/normalization | 0.5–1.0 |
| **Preview parity — frontend renders the same PNG** (§10) | 1.5 |
| Regression gate (§5 byte-identical for no-emoji) + tests across presets/formats | 1.5 |
| Integration/QA buffer | 1.5 |

### Top risks

1. **Preview parity is a *required* part of the feature, not a follow-up.** Ship the burn
   without the frontend change and you trade "emoji look wrong" for "emoji are in the
   wrong place vs the editor" — a *new* drift class, on the exact axis Stage 6 fixed.
   The host emoji font reserves **1.373em** (Segoe, measured) vs our **1.0em** box ⇒
   **~23px per emoji** at fs=62, plus every OS differs (Segoe/Apple/Noto advances are
   not equal). Budget the 1.5 days in the same PR.
2. **A new calibration constant (0.85) joins the k-values as maintained spec.** It is
   coupled to `S = fs`. If someone changes the box ratio or the font-size path, it drifts
   — silently and only cosmetically, which is exactly the kind of bug that survives review.
   Pin it with a test that asserts the measured box sits on the baseline per (font, size).
3. **Filtergraph blow-up on emoji-dense captions.** Every emoji occurrence today = 1 input
   + 2 filter nodes. A caption-stuffed clip (20+ emoji) risks a very long command line
   (Windows) and input-count bloat. Mitigate: **dedupe by codepoint** (one input per
   distinct emoji, reuse via `split`), and cap emoji per clip.

---

## 5. Asset set — **recommend Noto Color Emoji**, on licensing

| | **Noto Color Emoji** ✅ | Twemoji (jdecked fork) |
|---|---|---|
| License | **OFL 1.1** (verified: repo `LICENSE`) | Graphics **CC-BY 4.0**, code MIT (verified: README) |
| Attribution in output | **None.** OFL governs the Font Software; it does not restrict rendered output | **Required.** "attribution is critical… from a legal perspective" |
| Fits repo | **Yes** — the 3 bundled caption fonts are already OFL (`licenses/OFL-*.txt`) | New license class |
| Raster size | **128px** — downscales cleanly across our 52–86px range | **72px only** — upscales (soft) at `big-bold` fs=86 |
| Look @62px | Gradients, slightly softer | Flatter/bolder | 

Visual comparison at real caption size: `COMPARE_twemoji_vs_noto.png` — **both read fine
at 62px**, so look is *not* the deciding factor. Two things are:

- **Licensing.** Twemoji's CC-BY attribution is a poor fit for a SaaS whose output is
  **redistributed by users** to TikTok/YouTube: the graphics are embedded in videos we
  don't control. Twemoji accepts an About/footer credit *for the app*, but that
  obligation arguably travels with the video. Noto's OFL has **no** output-side
  obligation and matches the OFL pattern already in `services/assets/fonts/captions/licenses/`.
- **Source resolution.** Noto's 128px assets cover our whole size range without upscaling;
  Twemoji's 72px raster would soften at fs=86. (Twemoji does ship SVG, which would fix
  this at bundle time — but doesn't fix the license.)

> ⚠️ Not legal advice — worth a lawyer's glance. But OFL is the lower-friction path **and**
> the one consistent with the repo's existing licensing.

---

## 6. Segmentation & codepoint→PNG mapping — **use `regex`, not a hand-rolled rule**

**Segmentation.** My first-pass per-codepoint regex (what the spike shipped) is **wrong on
every hard case** (`seg.py`):

```
family ZWJ 👩‍👧          -> 2 slots  *** WRONG (should be 1) ***
astronaut+skin 🧑🏽‍🚀    -> 3 slots  *** WRONG ***
thumbsup+skin 👍🏿       -> 2 slots  *** WRONG ***
flag 🇮🇳                 -> 2 slots  *** WRONG ***
```

**`regex` (`\X` grapheme clusters) + `\p{Extended_Pictographic}` gets all of them right**
(`seg2.py`), keeps Telugu clusters intact, and splits mixed text cleanly:

```
text  -> 'మీరు '     EMOJI -> 1f525
text  -> ' super '   EMOJI -> 1f469-200d-1f467
text  -> ' '         EMOJI -> 1f44d-1f3ff
text  -> ' ok'
```

**`regex` is already installed (2.5.148) but is only a transitive dep — declare it in
`requirements.txt`** if used. (`emoji` and `grapheme` are not installed; not needed.)

**Mapping — the trap.** Probing the real CDN shows there is **no derivable rule** for
VS16 (`FE0F`):

```
1f525.png                 200      2764-fe0f.png              404   <- ❤️ STRIPS fe0f
1f469-200d-1f467.png      200      2764.png                   200
1f44d-1f3ff.png           200      1f3f3-fe0f-200d-1f308.png  200   <- rainbow flag KEEPS fe0f
1f9d1-1f3fd-200d-1f680.png 200     1f441-fe0f-200d-1f5e8-fe0f 404   <- eye-speech STRIPS both
1f1ee-1f1f3.png           200      1f441-200d-1f5e8.png       200
```

Rainbow flag **keeps** `fe0f` while eye-in-speech-bubble **strips** it — both have ZWJ, so
even Twemoji's own documented "keep FE0F if ZWJ present" rule does **not** match its
shipped assets. **Do not hand-roll this.** Build a **manifest of the bundled asset
directory at load time** and resolve against it with a candidate chain, then fall back
(§7). Never assume a filename exists.

---

## 7. Fallback rule — "blank box" made structurally impossible

**Rule: resolve the asset FIRST; only emit a placeholder box once the PNG is in hand.**

A blank box can only happen if we reserve a slot we then fail to fill — so never reserve
one speculatively. Resolution order per emoji cluster:

1. **Exact** codepoints → manifest lookup.
2. **Strip `FE0F`** → lookup.
3. **Drop skin-tone modifier** (`1F3FB–1F3FF`) → base emoji.
4. **Drop ZWJ tail** → leading base emoji (👨‍👩‍👧 → 👨).
5. **No PNG?** → **do not emit a box.** Emit the emoji as **text**, so libass renders it via
   the bundled **monochrome Noto Emoji** font (`DIAGNOSIS_EMOJI.md` §4b) — legible flat
   glyph, deterministic across hosts.
6. **No mono glyph either?** → **drop the cluster entirely.** Emit nothing.

Never a box, never tofu. Steps 5–6 are the only place the old mono path survives, and it
degrades to *legible*, never *blank*.

> Caveat carried forward from `DIAGNOSIS_EMOJI.md` §4b: adding mono Noto Emoji to the
> **flat, non-recursive** `fontsdir` could shift glyph resolution for other codepoints. Add
> it as an **explicit extra family** referenced only by the fallback run — do not make it a
> global fallback. This does not disturb the k-value calibration or the flat-dir/no-symlink rules.

---

## 8. Wire / storage — mostly already safe; **verify, don't rebuild**

Better news than the `text_tanglish` gap. Verified empirically:

- **Redis + JSON round-trips emoji intact.** Mirroring `api/database.py:54/60` and
  `api/main.py:294` (`json.dumps` default `ensure_ascii=True`): astral chars store as
  escaped surrogate pairs (`🔥`) and `json.loads` restores them — **IDENTICAL**,
  ZWJ family included. Storage is **Redis**, so the classic MySQL `utf8` vs `utf8mb4`
  astral-plane trap **does not apply**.
- **`_escape_ass_text` passes emoji through verbatim** (confirmed against the real
  function) — so the placeholder swap **must happen before** escaping, on the segmented
  runs, not after.
- Transcript files already use `ensure_ascii=False` + `encoding='utf-8'`.
- Emoji never touch the ffmpeg command line (they live in the `.ass` and in asset
  filenames), so no Windows console-encoding exposure. *(Note: bare `print()` of emoji
  **does** crash on this host's `cp1252` stdout — the pipeline's own logging needs care.)*

**What's actually needed** (don't build now): **normalization** at the edit seam (VS16/ZWJ
forms vary by input method — normalize once, server-side, before resolution), and test
coverage asserting an emoji typed in the editor survives to the burned frame.

---

## 9. Preview parity — the preview must stop using the host's emoji font

Today (`DIAGNOSIS_EMOJI.md` §5) preview shows color emoji from the host font and the burn
shows a karaoke-tinted mono outline. The overlay path **auto-fixes the color and tint
axes**: the burn now shows real color emoji that **don't tint** during the sweep — which is
already what the preview does (CSS `color` doesn't affect color emoji). Those two
divergences disappear for free.

That leaves **geometry**, and it must be handled deliberately:

- The host emoji font reserves **1.373em** (Segoe, measured) vs our **1.0em** box ⇒ **~23px
  per emoji** at fs=62; text after each emoji shifts, and `\an5` centering shifts the whole
  line by roughly half that. Apple/Noto advances differ again — **the preview is currently
  host-dependent too**.
- **Chasing the host font is a dead end.** The fix is to make the preview use **our** box:
  render caption emoji in `ElementBodies.jsx :: CaptionBody` as an **`<img>` of the same
  bundled PNG**, `height/width: 1em`, `vertical-align: -0.1em` — the exact box the ASS
  placeholder reserves.

Then **neither** side uses a host emoji font, both use the same asset and the same 1em
box, and preview == export **by construction on every OS**. Same discipline as §4 of
BURNIN_NOTES (one anchor, one code path).

---

## 10. Linux-container deploy

**This approach makes emoji *easier* to deploy on Linux, not harder** — it is the only
option that removes the host-font dependency:

- ✅ **The §3 landmine in `DIAGNOSIS_EMOJI.md` is eliminated.** The emoji codepoint never
  reaches libass (final ASS: **0 emoji codepoints**; verified libass resolves only
  `NotoSansTelugu-Regular`, **no** `Glyph 0x1F525 not found`, **no** Segoe fallback). Emoji
  come from bundled PNGs via `overlay`. Nothing to install, nothing to fall back to,
  identical on every host. Placeholder boxes are ASS **drawings** — no font at all.
- ✅ `overlay` / `scale` / `ass` / `lavfi` are all standard; nothing exotic is required.
- ⚠️ **Probe detection must stay tolerant.** The pc↔tv range compression observed here
  (`255→235`) may differ on a Linux ffmpeg build — **never** exact-match colors;
  nearest-palette classification is mandatory (already the case).
- ⚠️ **numpy + PIL become burn-path runtime deps** in the worker image (present on this
  host; confirm in the container).
- ⚠️ The emoji asset dir must ship in the image and be path-resolved like `CAPTION_FONTS_DIR`.
- ℹ️ Font *provider* still differs (directwrite here, fontconfig there) — but that now only
  affects **text**, which `fontsdir` already pins deterministically.

---

## 11. Proposed amendment to `BURNIN_NOTES.md` §2 (exact wording)

> ## 2. Single-pass compositing
> Overlay elements (progress/logo/headline/sticker) each prepare a layer (PNG, or a short
> clip for the animated progress bar) with **zero** video encoding, and
> `services/overlay_renderer.py :: render_elements` composites them in **one** final
> full-resolution `libx264` pass. The full-res re-encode dominates cost (~19s of ~23s), so
> per-element passes would stack ~linearly. Do not add per-element encode passes. Captions
> are their own separate pass (after overlays); keep it that way.
>
> ### 2a. Amendment — color-emoji overlay inside the caption pass
> The caption pass MAY composite color-emoji PNGs with `overlay` filters **inside the same
> filtergraph as the `ass=` text burn**: one ffmpeg invocation, one `libx264` encode. This
> is **not** a second pass and does not weaken §2 — it adds filter nodes, not encodes.
> Binding rules:
>
> 1. **Text rendering is unchanged and `ass=`-only (§1).** Emoji are never rendered as text
>    on the color path; the emoji codepoint is **removed** from the ASS and replaced by an
>    invisible `{\p1}` placeholder drawing. libass must never see an emoji codepoint —
>    that is what makes emoji host-font-independent (no fallback, no tofu on Linux).
> 2. **Emoji positions come ONLY from a probe render of the real `ass=` path** — measured
>    placeholder-box rects. **Never** re-implement or approximate libass layout. Alignment
>    is exact by construction because probe and burn share one libass; alpha provably does
>    not affect layout.
> 3. **The probe renders 1 frame per caption line THAT CONTAINS AN EMOJI**, on a `lavfi`
>    color source — no decode, no encode. Karaoke changes color only, never layout
>    (verified), so per-caption emoji rects are **static** across the sweep. Never probe
>    per-frame.
> 4. **Probe detection must be tolerant** (nearest-palette on bright pixels). ffmpeg
>    negotiates `ass` into YUV and the RGB round-trip range-compresses colors
>    (`255→235`, `0→16` observed); exact color matching **will** break, and may differ per
>    host build.
> 5. **The emoji box is calibrated spec** (like the §3 k-values): box side `S = 1.0 × fs`,
>    drawing shift `D = round((0.85 + 0.10) × fs)`. The `0.85` origin→baseline constant is
>    only valid while `S = fs`. Do not float the box ratio.
> 6. **Resolve the PNG BEFORE emitting a placeholder.** A box is only ever emitted for an
>    emoji whose asset is already in hand; unresolved emoji fall back to the bundled
>    monochrome font, then to being dropped. **Never** a blank box or tofu.
> 7. **Captions with no emoji must be byte-identical** to today: same `.ass` bytes, same
>    single `-vf ass=…` command, no probe, no overlay nodes. Gated by §5.
> 8. **The editor preview must render the same PNG asset at the same 1em box**
>    (`<img>`, `height:1em`, `vertical-align:-0.1em`) — never the host emoji font, whose
>    advance differs (Segoe 1.373em vs our 1.0em ⇒ ~23px/emoji at fs=62) and varies per OS.

---

## 12. Artifacts (all in `…/scratchpad/emoji_color/`)

| File | What it proves |
|---|---|
| `single_out.mp4` / `f_single_1.0.png` | ✅ **Color emoji inline**, correct position, real path |
| `multiline_out.mp4` / `f_multi_3.4.png` | ✅ **Wrapped 2-line caption**, emoji on line 2, correct |
| `CMD_single_out.mp4.txt` | The single filtergraph command that produced it |
| `probe1.py` | Drawing takes part in layout; **alpha doesn't change layout** (the crux) |
| `probe2.py` | **Karaoke is layout-static**; `\pbo` unusable |
| `probe3.py` / `probe4.py` / `probe5.py` | Drawing shift is 1:1; **0.85 constant**, font-independent; `S=fs` lock |
| `spike.py` | Full pipeline: segment → probe → measure → single-filtergraph burn |
| `verify.py` | Emoji rect **maxdiff 0** across sweep; **zero placeholder residue** |
| `seg.py` / `seg2.py` | Naive regex fails all hard cases; `regex \X` fixes all |
| `emoji_metrics.py` | Segoe advance **1.373em** ⇒ the preview-parity gap |
| `timing.py` | Probe = **116 ms/line** |
| `COMPARE_twemoji_vs_noto.png` | Asset look at real caption size (62px) |
| `single_probe.ass` / `single_final.ass` | Probe vs final ASS; final has **0 emoji codepoints** |

**Environment:** FFmpeg 8.0.1 (gyan.dev, static, `--enable-libass`), libass 0.17.4,
FreeType 2.14.1, Python 3.11.4, numpy 2.0.1, PIL 12.3.0, `regex` 2.5.148.
