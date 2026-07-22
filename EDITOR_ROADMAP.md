# Editor Roadmap — single-speaker talking-head focus

> Scope: **one speaker, talking to camera.** Vertical 9:16 clips cut from long-form Telugu video.
> This narrows the product a lot, and that's good — it kills the most expensive item on the old
> roadmap and concentrates everything into the editor.

---

## What the narrowed scope changes

| Previously "must-have" | Now |
|---|---|
| **Multi-speaker active-speaker reframe** (TalkNet-ASD integration) | ❌ **Dropped.** One speaker → a smoothed centre crop is genuinely fine. This was the single largest L-effort task on the roadmap. |
| Speaker diarization plumbing | ❌ Dropped (was only needed to pick the active face) |
| Dynamic layout switch / split-screen | ❌ Dropped |
| Genre-specific reframing models | ❌ Dropped |

**What replaces them:** for a static talking head, retention comes from *pacing and motion you add in
post* — punch-ins, tight cuts, caption energy. That is all editor work. See Tier 1.

---

## What your editor already has (verified in code)

**Inspector sections:** Caption Preset · Font · Size · Position · Background Pill · Background Fill ·
Animation *(disabled)* · Canvas Aspect · Elements · Headline · Image Size · My Style · Burn-in Captions

**Element types:** caption · logo · headline · progress · image

**Toolbar:** Add element · Fit to viewport · Zoom in · Zoom out *(that's all — no undo/redo buttons,
no align, no duplicate)*

**Under the hood (strong foundation):** normalized 0–1 coords end-to-end · single document model
shared by drafts/undo/export · gesture-coalesced undo · autosave with stale-write guards · editable
word-level transcript with split/merge · line realignment · Telugu ⇄ Tanglish toggle · WYSIWYG
preview using the same .ttf files as the burn.

**The architecture is genuinely good.** Everything below is additive, not a rewrite.

---

## ⚠️ One hard dependency, before anything in Tier 1

**Fix the caption-sync defect first** (`PRODUCT_REVIEW.md` blocker #4 — captions are timed to the
raw clip start while the cutter uses an energy-refined start, so every clip is off by up to 0.5s).

Why it blocks this roadmap: **auto-zoom and filler-removal both change the clip's timeline.** If you
build timeline-mutating features on top of a timeline that's already misaligned, the errors compound
and become very hard to debug. Fix sync → then build.

---

## 🟥 TIER 1 — Output quality (what actually makes talking-head clips perform)

### 1. Auto-zoom / punch-ins ⭐ the single highest-impact feature
A locked-off talking head is visually static; viewers drop. Every serious tool solves this with
periodic scale changes on speech beats. Submagic ships "auto-zoom"; it's the defining talking-head feature.

- **What to build:** subtle scale in/out at sentence or emphasis boundaries (e.g. 1.0 → 1.12 over
  ~0.4s, hold, release). Auto-generate from the word timestamps you already have, then let the user
  add/remove/adjust punch points on the timeline.
- **Seam already reserved:** `crop_keyframes: List[dict] = []` exists in `api/models.py:110` and in
  `docs/SHOTVI_SPEC.md:342` as `[{time, x, y, w, h, tracked_subject}]` — **but `api/worker.py` never
  reads it.** The contract is stubbed; the renderer is not.
- **Render approach:** FFmpeg `crop` accepts expressions in `t`, so an animated crop fits inside your
  existing single-pass filter chain — no extra encode. (Validate `crop_box` first — it's the P0
  injection hole.)
- **Effort:** M (renderer) + M (timeline keyframe UI). **Best value-per-hour on this list.**

### 2. Filler-word + silence removal
Tightens pacing, which matters more on talking heads than anything except the hook. Universal across
Opus (Starter) and Submagic (Pro).

- You already have **word-level timestamps + energy analysis** (`refine_boundary`) — the hard inputs exist.
- Build a cut-list → render with `select`/`aselect` + `setpts`/`asetpts`.
- **In the editor:** show removed spans struck-through in the transcript with one-click restore
  (text-based editing, like Descript). Your `EditableTranscript` is the natural home.
- ⚠️ Cutting changes the timeline → **caption timings must be remapped.** Hence the sync dependency above.
- **Effort:** M–L.

### 3. Keyword emphasis in captions
Replix ships it; Opus ships keyword highlight *even on the free tier*. On single-speaker clips the
captions carry most of the visual energy.

- **Cheapest high-impact item here.** You fully control the ASS output — emphasis is just override
  tags (colour / scale / weight) on selected words.
- Have Gemini tag 1–2 emphasis words per line during selection; let the user toggle any word in the
  transcript.
- **Effort:** S–M. Do this first for a quick visible win.

### 4. Caption animation — un-disable it
Your Inspector has an **Animation** section that is disabled because "the burn can't render it."
**That's only partly true.** ASS supports `\t` (animated transforms), `\move`, and `\fad` — enough for
pop-in, fade, slide-up, and scale-punch word reveals. Replix sells "caption animation" as a paid feature.

- Start with 3 presets: **pop** (scale 0.8→1.0 via `\t`), **fade** (`\fad`), **slide-up** (`\move`).
- **Effort:** M. Turns a visibly disabled control into a paid differentiator.

### 5. Auto hook title (nearly free)
`clip_selector` already produces `hook_text` and a hook score — you use them **only for ranking**.
You already have a **headline element**. Auto-populate the headline with `hook_text` on clip open,
user-editable. Opus sells this as "AI hook title"; Submagic as "AI hook titles."
- **Effort:** S. Probably the best effort-to-value ratio in the entire document.

---

## 🟦 TIER 2 — Editor UI / ergonomics (the "editor UI" ask)

These don't change output quality; they change whether the tool feels professional.

### 6. Real waveform + word ticks on the timeline
`TimelineRow.jsx` currently renders **120 bars from `Math.sin(i*0.35)`** — decorative, not audio.
Clipdify's editor shows a genuine filmstrip timeline with a frame ruler; next to it yours reads as a
placeholder.
- Decode audio via WebAudio → render real peaks. Overlay **word ticks** from timestamps you already have.
- On a talking head, the waveform *is* the edit map (pauses = cut points, peaks = punch-in points) —
  it directly serves Tier 1 features #1 and #2.
- **Effort:** M.

### 7. Preset gallery with live preview, export-gated ⭐ steal from Replix
Replix's best mechanic: free users can **preview every premium preset, font, animation and glow in
the editor** — only **export** is gated. You feel the value, then hit the wall.
- You already render presets live in the canvas. Show the full gallery to everyone; gate the export.
- **Effort:** S once you have tiers. Best conversion mechanic available to you.

### 8. Basic editor ergonomics that are simply missing
All cheap, all expected in a CapCut-class tool, all easy given your architecture:
- **Multi-select + group transform** — `selectedElementId` (a single string) → `selectedIds: Set`;
  add shift-click and marquee. Nudge/drag/delete operate on the set.
- **Align & distribute buttons** — trivial with normalized coords; you already draw smart guides.
- **Duplicate / copy-paste / z-order hotkeys** — `Ctrl+D`, `Ctrl+C/V`, `[` / `]`. Your keymap is
  centralized and pure (`editorKeymap.js`), so this is a small, well-contained change.
- **Undo/redo buttons in the toolbar** — the history store is already solid; there's just no UI for it.
  Keyboard-only undo is invisible to most users.
- **Effort:** S each.

### 9. Fix the WYSIWYG zoom bug
`ElementRenderer.jsx` reads `getBoundingClientRect().height` *after* the `scale(zoom)` wrapper, so
element font sizes scale by `zoom²`. At the default fit zoom (~0.85) captions preview ~10–15% off
their true export size — the preview lies, which undermines the entire WYSIWYG promise.
- Thread the unscaled `STAGE_DIMS.h` down instead. **Effort: S.** (Also: pill padding/radius are in
  absolute px while text scales as a fraction of canvas height — same class of bug.)

---

## 🟩 TIER 3 — Later

- **B-roll / image insert on keywords** — your `image` element exists; auto-suggest placement from
  transcript keywords. (ButterCut and Opus both ship this; heavier because it needs a stock library.)
- **Emoji in captions** — ⚠️ blocked: your bundled Telugu fonts have **no emoji coverage**, so emoji
  currently render as tofu. Needs a fallback font chain first.
- **Full brand kit** — extend "My Style" from caption-only to a whole layout template (headline +
  logo + progress placement).
- **Virality score surfaced in the UI** — you compute it; show it on the clip card.

---

## Suggested build order

1. **Caption sync fix** — unblocks everything timeline-related *(blocker)*
2. **Auto hook title** — S, immediate visible value
3. **Keyword emphasis** — S–M, biggest caption-energy win
4. **WYSIWYG zoom fix + editor ergonomics** (multi-select, align, duplicate, undo buttons) — S each, makes it feel professional
5. **Auto-zoom / punch-ins** — M+M, *the* talking-head feature
6. **Real waveform + word ticks** — M, and it makes #5 and #7 usable
7. **Caption animation presets** — M, un-disables a paid feature
8. **Filler/silence removal** — M–L, do last in Tier 1 (most invasive to the timeline)
9. **Preset gallery + export gating** — ship alongside tiers/metering

---

## Why this is the right bet for your position

Replix (your closest Telugu competitor) **cannot clip long-form** — it only captions a Reel you
already have. Clipdify and ButterCut clip, but their Telugu caption quality is unproven and their
editors are generic.

**The intersection you own is: long-form Telugu → talking-head Shorts, with captions that render
correctly and an editor that adds real production value (punch-ins, tight pacing, caption energy).**

Everything in Tier 1 pushes directly on that. None of it requires the multi-speaker machinery you
just descoped.
