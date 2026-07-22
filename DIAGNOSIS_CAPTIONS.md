# DIAGNOSIS — Captions/Transcript Editor Features (Undo/Redo, Split, Text Editing)

Read-only investigation of `shotvi-emergent-new`. No code was modified; this file is the
only artifact created. Code traced statically; both test suites executed read-only.

Reference-repo comparison note: the `clipforge-ai` working tree at `D:\clipforge-ai` has all
tracked files deleted on disk, so the comparison below reads the reference code from that
repo's git HEAD via read-only `git show` (no state-changing git operations of any kind were
run; nothing in this repo's `.git` was touched).

---

## ISSUE 1 — Undo/Redo

**STATUS: NEVER BUILT.**

### Root cause (absence)
- `frontend/src/pages/Editor.jsx:95-100` — the two topbar buttons render the `Undo2` /
  `Redo2` icons with full hover styling but **no `onClick` handler at all**. They are
  decorative chrome.
- `frontend/src/store/useAppStore.js` (the only store, 866 lines) — contains **no history
  slice whatsoever**: no `past`/`future` arrays, no snapshot capture, no temporal middleware
  (no zundo or equivalent), no `undo`/`redo` actions. Repo-wide grep for
  `undo|redo|history|past:|future:|pushHistory` in `frontend/src` returns zero hits other
  than the two lucide icon imports.
- No keyboard binding either: the only global keydown handler in the app is
  `frontend/src/components/editor/CanvasArea.jsx:75-118`, which handles exactly Space
  (pan), Escape (deselect), Delete/Backspace (remove element), and Arrow keys (nudge).
  There is no Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y anywhere.

Answers to the specific questions:

1. **Where does the stack live?** Nowhere. There is no stack, no snapshots, no deltas.
2. **Actions that push to the stack:** none. **Actions that don't:** every editor mutation —
   `updateElement` (useAppStore.js:642), `updateElementProps` (:652), `addElement` (:659),
   `removeElement` (:669), `toggleElementVisibility` (:676), `bringForward` (:683),
   `sendBackward` (:691), `setCaptionPreset` (:707), `applyPositionPreset` (:729),
   `setExportSetting` (:470). All are plain `set()` calls.
3. **Did the new features / sticker removal break it?** No — there was never anything to
   break. `captionFont`, the size slider, and the background pill all live in the caption
   element's `props` and would be covered *if* a snapshot system existed; none does.
   `sanitizeDraftElements` (useAppStore.js:41-42) is purely a **draft-load filter** (applied
   only at useAppStore.js:382 inside `openClip`) that drops retired element types (the old
   `sticker`) from saved drafts. It never touches any snapshot/restore path because no such
   path exists. The failure mode is not capture-broken, restore-broken, or wiring-broken —
   it is **all three absent**.

### Blast radius
Every editor mutation is irreversible in the UI. Most dangerous: `Delete`/`Backspace` on a
selected overlay element (CanvasArea.jsx:95-97) permanently removes it with no recovery
short of manually re-adding and re-configuring it. The dead buttons also actively mislead —
the UI promises a capability that silently does nothing.

### Fix/build shape
New feature build, not a wiring fix. Add a history layer over the undoable state subset
(`elements`, `exportSettings`, and — once it exists — `transcriptEdits`): either zundo's
temporal middleware or a hand-rolled `past`/`future` slice with `pushSnapshot()` called from
the mutation actions, with drag/slider coalescing (commit one snapshot on pointerup, not per
pointermove). Then wire the two existing buttons plus a Ctrl+Z/Ctrl+Shift+Z keydown.
Moderate structural work (roughly 1–2 focused days including tests), touching the store and
2–3 components.

---

## ISSUE 2 — Split at playhead

**STATUS: NEVER BUILT (frontend). The backend half is fully present and tested.**

### Root cause (absence)
The chain breaks at the very first link:

- `frontend/src/components/editor/TimelineRow.jsx:78-83` — the Split button
  (`data-testid={EDITOR.splitBtn}`, Scissors icon) has **no `onClick` handler**. Clicking it
  does nothing by construction. Same dead-chrome pattern as the Undo/Redo buttons.

Nothing exists downstream of it either:

1. **UI → handler:** absent (TimelineRow.jsx:78-83, no handler).
2. **Store mutation / `lineSplits` state:** absent — `useAppStore.js` defines no
   `transcriptEdits` and no `lineSplits`. The string `lineSplits` appears in the frontend
   only as a parameter/comment in `api/renders.js:76` and as "future feature" comments in
   `lib/captionLines.js:8-11`.
3. **Preview re-render:** the caption preview does **not** read `lineSplits`.
   `frontend/src/components/editor/ElementBodies.jsx:59` calls
   `buildCaptionLines(transcript, wordsPerLine)`; `buildCaptionLines`
   (`lib/captionLines.js:48-50`) → `groupWordsIntoLines` (:29-45) is pure modulo chunking
   (every N words) with no split-point parameter. Its own header comment (captionLines.js:8-11)
   states it is "the intended foundation for the future Enter-to-split-lines (lineSplits)
   feature" — i.e., deliberately not built yet.
4. **Autosave/reload:** the break extends to persistence. Drafts persist
   `getEditDocument()` (useAppStore.js:436-460), which has no `transcriptEdits` field, and
   draft restore (useAppStore.js:377-389) reads back only `elements` and `exportSettings`.
   So even an in-memory split (if one existed) would be lost on refresh. The backend draft
   store itself needs **no change** — `PATCH /jobs/{job}/clips/{clip}/draft`
   (api/main.py:283-298) stores arbitrary JSON in Redis (7-day TTL).

Meanwhile the backend export path is **completely ready**: `TranscriptEdits.lineSplits`
(api/models.py:42), `RerenderRequest.transcript_edits` (api/models.py:55), forwarded by
api/main.py:266, threaded through api/worker.py:203/342/356-371 (including the
multi-segment skip + `transcript_edits_skipped_multi_segment` warning), and applied in
services/caption_renderer.py:814-817 via `group_words_with_splits`
(services/apply_transcript_edits.py:82-…). Covered by `tests/test_apply_transcript_edits.py`
(passing).

Cross-link to Issue 3 confirmed: **the absence of `transcriptEdits` from the store IS the
root cause here** — "split at playhead" is precisely the `lineSplits` third of the missing
transcript-edits frontend.

### Blast radius
Split is unusable in both preview and export. Also leaves dead code behind: the
multi-segment warning toast handler in useAppStore.js:536-539 can never fire (nothing ever
sends `transcript_edits`), and `buildRerenderRequest`'s `transcriptEdits` passthrough
(renders.js:76, :110) has no caller that supplies it.

### Fix/build shape
Medium frontend feature; zero backend change. Add a `transcriptEdits` slice
(`{wordEdits, mergedGroups, lineSplits}`) to the store; Split's onClick computes the raw
word index at the playhead and appends to `lineSplits`; extend
`buildCaptionLines`/`groupWordsIntoLines` to accept forced split points (the module was
shaped for exactly this); include `transcriptEdits` in `getEditDocument()` and pass it in
`startExport`'s `buildRerenderRequest` call; restore it in `openClip`'s draft-load. Must
mirror the backend's index semantics (`rawIndex` per
services/apply_transcript_edits.py:82-110) to avoid drift.

---

## ISSUE 3 — Caption text editing

**VERDICT: (b) PARTIALLY PRESENT — the backend half and a frontend request-builder
passthrough exist; the store schema, all UI, and the store→export wiring are entirely
absent.** "Never ported" is half-true: the frontend editing half was never built here — and
(see comparison below) it does not exist in the accessible `clipforge-ai` reference either.

### 1. Frontend inventory
- **No text-edit affordance exists anywhere.** The transcript word chips
  (TimelineRow.jsx:174-196) are buttons whose sole handler is `seek(w.start + 0.02)` —
  click-to-jump only, and the panel label says exactly that ("Click a word to jump",
  TimelineRow.jsx:151). No `contentEditable`, no edit modal, no inline input on any
  transcript word. The only text inputs in the editor are Inspector element-prop fields
  (headline text, colors, sizes — Inspector.jsx:272/333/374/380/398/448) and the AppShell
  search box.
- **The store defines no `transcriptEdits` at all** — not defined-but-empty, *absent*.
  `useAppStore.js` has zero occurrences of `transcriptEdits`/`wordEdits`/`mergedGroups`/
  `lineSplits`. `getEditDocument()` (useAppStore.js:436-460) does not include it.

### 2. Export path — what is actually serialized today (BUG-003 confirmed)
`getEditDocument()` (useAppStore.js:436-460) returns exactly:
`version(=1), clipId, elements, exportSettings, style, captionFont, captionX, captionY,
captionFontSize, captionPill`.

`startExport` (useAppStore.js:481-527) calls `buildRerenderRequest` with:
`style, format, background, bgColor, useAutocrop, captionFont, captionX, captionY,
captionFontSize, captionPill, elements` (useAppStore.js:505-518) — **`transcriptEdits` is
not passed**.

`buildRerenderRequest` (api/renders.js:64-151) produces:
`style, format, background, bg_color, use_autocrop, trim_start, trim_end, crop_mode` always;
conditionally `crop_box, selected_subject, caption_font, caption_x, caption_y,
caption_font_size, caption_pill, elements` — and conditionally `transcript_edits`
(renders.js:110) **only if a `transcriptEdits` arg is supplied, which its single caller
never does**. So the field exists in the builder, unused, and `transcript_edits` never
appears in any real export payload. **BUG-003 is CONFIRMED: transcriptEdits is absent from
export — by omission at the call site, with the serialization hook already in place.**

### 3. Backend
Fully built and the *only* tested half of the feature:
- `TranscriptEdits` pydantic model — api/models.py:39-42 (`wordEdits`, `mergedGroups`,
  `lineSplits`); `RerenderRequest.transcript_edits: Optional[TranscriptEdits]` —
  api/models.py:55.
- Endpoint forwards it: api/main.py:266.
- Worker threads it to the caption render: api/worker.py:203, :342, :356-371 (with the
  multi-segment structural-edit skip + warning).
- Application logic: `services/apply_transcript_edits.py` implements all three edit kinds;
  `services/caption_renderer.py:719-750` applies `wordEdits` (multi-segment-safe) and
  :814-817 applies `lineSplits` grouping **before writing ASS events** — so yes, edited word
  text would be burned if it ever arrived. Today `transcript_edits` is always `None`, so the
  backend renders purely from the original transcript JSON.
- KNOWN_ISSUES.md §(f) even documents multi-segment edit-skip behavior as if "the transcript
  editor" existed — the docs and warning plumbing were carried over ahead of the UI.

### 4. Transcript JSON shape (groundwork for the editing build)
Stored at `storage/uploads/{video_id}_audio_transcript.json` (verified on a real file):

- Top level: `text`, `language`, `language_probability`,
  `segments: [{id, start, end, text}]`, `sentences: [{id, text, start, end}]`,
  `word_timestamps: [...]`, `total_segments`, `total_sentences`, `total_words`,
  `asr_model` (= `sarvam/saaras:v3 (batch) + ctc-forced-aligner/mms-300m`),
  `processing_time_seconds`.
- **Per word (`word_timestamps[i]`): exactly `{word, start, end}`** — times rounded to 3
  decimals on the original video's global timeline (services/transcriber.py:309-325).
- No `word_tanglish` or any transliteration/edit field exists yet anywhere in the shape —
  the planned `word` / `word_tanglish` / edit attachments are green-field additions.
- Frontend normalizes to `{text, start, end}` clip-local (api/transcripts.js:40-59), passing
  Telugu strings through verbatim (backend word boundaries authoritative).

### 5. Comparison with clipforge-ai (D:\clipforge-ai, read at git HEAD)
The reference was accessible and was compared. Result — **there is nothing there to port**:

- `TimelineRow.jsx`, `Editor.jsx`, `captionLines.js` at clipforge-ai HEAD are byte-identical
  (modulo CRLF) to this repo — same handler-less Split button, same handler-less Undo/Redo
  buttons, same modulo-only line grouping.
- `useAppStore.js` / `api/renders.js` differ by ~90 / ~47 real lines, and every difference
  makes `shotvi-emergent-new` **newer** (captionFont/fontSize/pill serialization,
  `sanitizeDraftElements`, export-warning toast). clipforge-ai HEAD's store also contains
  zero `transcriptEdits`/undo/history.
- clipforge-ai HEAD's **backend** likewise already has `apply_transcript_edits.py`, the
  `TranscriptEdits` model, and `tests/test_apply_transcript_edits.py`.

So the frontend transcript-editing UI is missing in **both** repos at their current
snapshots. If it ever existed in clipforge-ai it is not at HEAD (history was not searched,
per the no-git-archaeology constraint). The feature appears to have been built
backend-first, with the frontend half never implemented anywhere accessible.

### Blast radius
No user can correct ASR errors (word text), merge, or split caption lines — a core gap for
a Telugu-first product where ASR word errors are common. It also strands working backend
code and its test suite, and makes KNOWN_ISSUES.md §(f) describe UI that doesn't exist.

### Fix/build shape
New feature build (largest of the three): a transcript-edit UI (inline word editing in the
TimelineRow chips or a dedicated panel), a `transcriptEdits` store slice with the backend's
ref/index semantics, preview integration (word text overrides + split-aware line grouping),
and the one-line export wiring (`transcriptEdits: …` added to the `buildRerenderRequest`
call at useAppStore.js:505-518) plus draft persistence. Backend needs nothing for parity;
`word_tanglish` support would be a separate backend extension.

---

## CONNECTED OR INDEPENDENT

**Issues 2 and 3 are the same defect.** "Split at playhead" is the `lineSplits` third of the
missing frontend `transcriptEdits` feature; both reduce to: the store has no
`transcriptEdits` slice, no UI mutates one, and `startExport` never sends one — against a
backend that fully supports all of it. Fixing Issue 3's store/wiring gap creates the rails
Issue 2's button needs; neither can be fixed without the other's foundation.

**Issue 1 is mechanically independent** — an absent history system has nothing to do with
the transcript-edits schema, and no store refactor or the sticker removal broke it (nothing
existed before those changes; the reference repo without them has the identical absence).
But all three share one *pattern*, which explains the bug reports: the editor chrome was
built as a static mock first (styled, icon'd, test-id'd buttons with no handlers —
Editor.jsx:95-100 and TimelineRow.jsx:78-83 are structurally identical dead buttons), and
the features behind three of those buttons were never implemented. The reports of "broken"
features are users clicking mock UI.

## RECOMMENDED ORDER

1. **Build the `transcriptEdits` frontend (Issues 3 + 2 together, one feature).** The
   backend is done and tested; the request-builder hook (renders.js:110) is already in
   place; drafts persist any JSON. Deliver split-at-playhead as the first slice (smallest UI
   surface), then word text editing.
2. **Then undo/redo (Issue 1).** Do it second because its snapshot scope should include
   `transcriptEdits` — building history first means re-plumbing it the moment the new slice
   lands. Transcript editing also raises the stakes for undo (text edits are the most
   undo-hungry operations), so sequencing this way maximizes the value of both.

## TRANSCRIPT JSON — PER-WORD FIELD LIST

```
word_timestamps[i] = {
  "word":  str,    # verbatim Telugu token — never split/re-tokenized client-side
  "start": float,  # seconds, global (original-video) timeline, 3-decimal
  "end":   float   # seconds, global timeline, 3-decimal
}
```
Companion structures for edit addressing: `sentences: [{id, text, start, end}]` and
`segments: [{id, start, end, text}]`. No `word_tanglish` or edit fields exist yet.

---

## TEST SUITE RESULTS (run read-only)

- **Backend** — `python -m pytest tests/ -q`: **116 passed, 5 skipped** (12.2s).
  `tests/test_apply_transcript_edits.py` covers the backend *application* of
  wordEdits/mergedGroups/lineSplits and passes.
- **Frontend** — `CI=true npx craco test --watchAll=false`: **8 suites, 93 tests, all
  passed** (26s).

**Coverage gaps (why everything passes while the features are broken/absent):**
- **Undo/redo:** zero tests anywhere (nothing exists to test).
- **Split:** zero tests. No frontend test mounts a component at all (all 8 suites are pure
  logic tests: captionLines, editDocument/buildRerenderRequest, transcript remap, style
  preview, clamping, export refresh) — so a rendered button with no onClick is invisible to
  the suite. The `split` grep hits in tests are coincidental (`split-color` style name,
  `String.split`).
- **Transcript-edit export:** `editDocument.test.js` exercises `buildRerenderRequest`
  thoroughly (caption position/font/size/pill/elements/crop) but never asserts anything
  about `transcript_edits` — the exact field BUG-003 concerns. The passing backend test is
  double-edged: it proves the consumer works, masking that no producer exists. A
  cheap sentinel test ("`getEditDocument()` contains `transcriptEdits` and `startExport`'s
  payload carries it") would have caught the gap.
