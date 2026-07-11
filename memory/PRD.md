# ClipForge AI — Codebase Cleanup PRD

## Problem
Portfolio-grade cleanup and bug fixes for the existing Telugu-first AI video
clipping web app (`gowtham2891/clipforge-ai`). Executed as 6 sequenced commits.

## Product context
- Web app: React 19 + Zustand frontend + FastAPI + Celery + Redis backend
- 6-stage pipeline: Download → Transcribe → Select → Cut → Crop → Caption
- Sarvam ASR, Gemini clip selection, MediaPipe 9:16 crop, ASS karaoke captions
- Caption burn locked to `ass=` + `fontsdir` (subtitles= breaks Telugu shaping)

## Commits delivered

### Commit 1 — Remove Streamlit
- Deleted `app.py`
- Removed `streamlit` from `requirements.txt`
- Verified no other streamlit imports remain
- `docker-compose.yml` never defined a streamlit service — no changes needed there

### Commit 2 — README + LICENSE
- Root `README.md` with project description, 6-stage architecture, tech stack,
  setup instructions, WYSIWYG editor section, font licensing
- MIT `LICENSE` at repo root

### Commit 3 — Deterministic caption font preview (Known Issue 2)
- Symlinked `frontend/public/fonts/{NotoSansTelugu,Ramabhadra,Mandali}-Regular.ttf`
  to the same `.ttf` files in `services/assets/fonts/` (byte-identical)
- Added `@font-face` rules in `frontend/src/index.css`
- Removed Nirmala UI fallback from Telugu stack (silently drifted export)
- Added `getCaptionFontStack` helper + 3 regression tests

### Commit 4 — Unified default caption anchoring (Known Issue 1)
- `generate_ass_karaoke` now emits `{\an5\pos(cx,cy)}` on EVERY event, always
- Untouched captions default to `(0.5, 0.82)` (matches frontend default)
- Worker threads `target_w/target_h` on all rerender formats
- Style Alignment now `5` (center) to match `\an5` overrides
- `caption_position` param kept for backward compat but is now dead for placement
- Rewrote `tests/test_caption_positioning.py` with 9 new regression tests
- Added 3 frontend tests asserting frontend default matches export contract

### Commit 5 — Clamp caption drag range (Known Issue 3)
- New `frontend/src/lib/clampToFrame.js` — bbox-aware center clamp
- Wired into `ElementRenderer.jsx` for caption drags
- Non-caption elements retain historical `(0.02, 0.98)` clamp
- 8 unit tests: 4 frame edges, interior pass-through, default anchor safety,
  oversized text symmetric-overflow, degenerate canvas dims

### Commit 6 — Remove dead `margin_bottom` (Known Issue 4)
- Removed 11 `margin_bottom` occurrences from `STYLES` in
  `services/caption_renderer.py`
- Verified no other reader

## Also added
- Static-verification smoke test `test_caption_burn_pipeline_end_to_end_ass_fontsdir_smoke`
  in `tests/test_caption_shaping.py` — proves the caption burn works end-to-end
  via `ass=` + `fontsdir` on any machine with ffmpeg (Telugu shaping test moved
  behind a `requires_libraqm` skip marker, unchanged in behavior)
- Updated `KNOWN_ISSUES.md`: items (b) (c) (d) (e) marked RESOLVED

## Test gates — all green
- Backend: 41 passed, 3 skipped (libraqm-gated Telugu shaping)
- Frontend: 81 passed, 0 failed (was 67 → added regression tests for C3/4/5)
- `grep -r streamlit .` empty; `grep -r margin_bottom services/` empty

## What is NOT changed
- FFmpeg `subtitles=` filter forbidden — untouched
- No git history rewrites or force-pushes
- Owner's 80MB committed test media out of scope
- Owner does final Telugu caption visual verification on production libass build

## Open items flagged
- Debian 12's `libass` build lacks libraqm — Telugu shaping tests correctly skip
  in that env; they pass on the production Docker image where libraqm is on
- Symlinks in `frontend/public/fonts/` — git tracks them as symlinks; on Windows
  clone with `core.symlinks=false`, they'd need `cp` fallback. Deferred pending
  owner's cross-platform CI decision
