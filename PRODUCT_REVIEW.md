# Shotvi / ClipForge — Full Product Review

> Six in-role reviews (backend, ML pipeline, editor, UX, security, product), each reading the
> actual code in `shotvi-emergent-new/` — not the existing review docs. Grades and severities
> reflect a **public-launch bar**, not internal-alpha. Every finding cites `file:line`.
>
> Codebase reviewed: ~2.6k API LOC · ~7k services LOC · ~14.8k frontend LOC.

---

## Verdict (one line)

**The engine is ahead of the product.** You have a genuinely differentiated technical moat
(correct Telugu caption shaping + word-level ASR + a WYSIWYG editor most auto-clippers can't
match), wrapped in an MVP that is **not yet safe or complete enough to launch publicly**. The
gaps are concentrated and fixable — none are architectural rewrites.

---

## Scorecard

| Lens | Grade | One line |
|---|---|---|
| 🖥️ Editor / Frontend | **A−** | Unusually disciplined document model + autosave hardening. One WYSIWYG zoom bug. |
| 🎬 Pipeline / ML | **B−** | Telugu ASR + captions beat the incumbents; video craft lags; caption desync on every clip. |
| 🔧 Backend / Infra | **B− / C+** | Auth & webhooks well built; data layer, job durability, uploads, observability are prototype-grade. |
| 🎨 UX / Visual Design | **B / C+** | Looks 9/10, behaves 6/10 — dead nav, no mobile, focus rings disabled, fabricated stats. |
| 🔐 Security | **Not launch-safe** | Core auth holds, but SSRF + ownership bypass + injection + zero rate-limiting block launch. |
| 📈 Product / Growth | **Wedge real, biz stub** | Paywall gates nothing, 24h TTL kills retention, no watermark = no growth loop. |

---

## The launch-blocker board

Consolidated across all six reviewers and de-duplicated. These must be true before you let the
public in. Ordered by "how badly it hurts if a stranger finds it first."

### 🔴 1. Anyone can download anyone else's clips — `/outputs` is unauthenticated & filenames are the public YouTube id
Output/thumbnail files are named `{youtube_id}_clip1_…_captioned.mp4` and served with no auth.
The YouTube id is public, so clips, edits and virality scores are trivially enumerable. You
cannot market "your private clips" while this is true.
**Fix:** signed expiring URLs or an authed streaming endpoint enforcing `_require_video_access`;
put an unguessable token in filenames.
`api/main.py:65,86`

### 🔴 2. Ownership bypass — `POST /jobs/recover/{video_id}` mints a job for any processed video with no owner check
User B calls recover on User A's video id and receives A's clips, hook text, virality scores and
AI metadata — then passes the by-video guard on `/transcript` and clip download too. This single
legacy endpoint defeats the otherwise-careful per-owner scoping.
**Fix:** remove from the prod surface, or require the caller already owns a job over `video_id`.
`api/main.py:265-332`

### 🔴 3. SSRF via the YouTube "allowlist" — it's a substring match, not a host match
`"youtube.com" in netloc` passes `http://youtube.com@169.254.169.254/watch?v=…` and
`youtube.com.evil.com`. The raw URL is then handed to yt-dlp, which fetches cloud-metadata /
internal hosts from inside your trust boundary.
**Fix:** exact-match `parsed.hostname` against a set; rebuild a canonical
`https://www.youtube.com/watch?v={id}` before fetch; segment worker egress.
`services/youtube_utils.py:28`, `services/video_downloader.py:66`

### 🔴 4. Karaoke captions are out of sync on *every* clip
The cutter snaps each clip to an energy-refined start (up to 0.5s off `clip.start`), but captions
are timed against the unrefined `clip.start`. The correcting sidecar (`_vertical_segments.json`)
is never written, so `remap_time` is a no-op. Multi-segment clips drift additively. The one thing
a karaoke product can't get wrong — invisible in dev, visible on every clip a user posts.
**Fix:** persist the refined boundaries the cutter actually used and rebase all word timing on
them (or emit the sidecar the code already knows how to consume).
`video_cutter.py:372-392`, `caption_renderer.py:802,335-351`

### 🟠 5. No rate limiting or quota anywhere — one account can run up an unbounded Gemini / ASR bill
Every `/jobs` and `/metadata` call spends real money (yt-dlp egress, Sarvam/Deepgram, Gemini —
and clip selection uploads the whole video to Gemini **twice**). The only throttle is a
per-*video* lock, useless against distinct URLs. Billing gates zero features, so free = paid.
This is an existential unit-economics hole.
**Fix:** per-user Redis token bucket + hard daily job quota + concurrent-pipeline cap, tied to
the plan you already record. Cap `transcript_text` length.
`api/main.py:103,187,652`, `api/billing.py`

### 🟠 6. Unbounded video upload read straight into RAM
`content = await file.read()` with no size cap, no type sniff (the *overlay-image* route does
both correctly — the primary path does neither). A multi-GB body or a few concurrent uploads OOMs
the process.
**Fix:** stream to disk in bounded chunks, enforce a max size + duration, ffprobe-validate the
container before enqueueing.
`api/main.py:199-201`

### 🟠 7. FFmpeg filtergraph injection via unvalidated `crop_box`
`crop_box` is a free-form dict interpolated straight into `-vf "crop=in_w*{w}…"`. A value like
`"1,movie=/etc/passwd,…"` splices a `movie=` source that reads a server file into the user's own
output. `bg_color` was hardened against exactly this; its siblings (`crop_box`, `style`,
`format`, `background`) were not.
**Fix:** Pydantic-validate `crop_box` as four `confloat(ge=0,le=1)`; validate style/format/
background against their known enums; sanitize filename components.
`api/models.py:108`, `api/worker.py:527-529,331-334`

### 🟠 8. Worker crash permanently orphans jobs — no Celery reliability config
No `task_acks_late`, no `reject_on_worker_lost`, no retries, no time limit. An OOM-kill mid-encode
(the common case) acks the task early and loses it; the job freezes in `status="transcribing"`
until its 24h TTL and the user polls forever. The pipeline is already checkpoint-idempotent, so
late-ack redelivery is safe.
**Fix:** `acks_late` + `reject_on_worker_lost` + soft/hard time limits + a stale-job reaper that
stamps `failed`.
`api/worker.py:26-30,247`

### 🟠 9. 24h Redis TTL silently deletes a paying user's project list
Every job expires after 24h and TTL is never refreshed. A creator's clips vanish the next day
even though the files persist on disk — the drafts that reference them outlive their job (7-day
TTL). For a "my projects" product this is data loss and a retention killer.
**Fix:** don't TTL terminal jobs; move job/clip metadata to durable Postgres (the Supabase phase
the comments anticipate). This also kills the O(N) Redis scans.
`api/database.py:40`

### 🟡 10. The front door feels broken — dead nav, an inert demo button & a pricing/checkout mismatch
App-shell "Billing / Settings / Help" all route to `/dashboard`; "Clip Library" points at a mock
id; the landing "Watch 60-sec demo" CTA has no handler; the marketing page sells 3 tiers but
checkout only knows 1. Global `*:focus-visible{outline:none}` blinds keyboard users (WCAG fail).
Individually minor, collectively "this is a prototype."
**Fix:** hide routes that don't exist yet, wire or remove the demo CTA, reconcile pricing with the
one real plan, restore focus rings.
`shotvi/AppShell.jsx`, `pages/Landing.jsx`, `index.css`

---

## 🔐 Security Engineer

**Verdict — not safe to launch as-is.** The core is genuinely well built: JWT verification (no
`alg:none`, audience pinned, JWKS rotation, fail-closed), Razorpay webhook HMAC over the raw body
with constant-time compare + replay ledger, path-traversal containment on `/clips/download`, and
PIL magic-byte sniffing on overlay uploads. Every subprocess call is list-form — no shell
injection. The problems are all at the edges: URL validation, resource limits, one un-scoped
legacy endpoint.

Beyond the four security blockers above, the medium-severity cluster should ship in the same pass:

- **Path traversal in rerender output filenames** — `style/format/background` only strip `:` and
  `#`, not `/` or `\`, then compose ffmpeg output paths → an authed user can write `.mp4` files
  outside `OUTPUT_DIR`. `api/worker.py:331-390`
- **`video_id` path param → filesystem with no shape check** — enforce `^[A-Za-z0-9_-]{8,16}$`
  before touching disk. `api/main.py:265,482,575`
- **CORS wildcard with credentials** — `allow_origins=["*"]` + `allow_credentials=True`. Limited
  impact today (bearer token, not cookies) but wrong and a launch red flag. `api/main.py:47-53`
- **Verbose ffmpeg stderr surfaced to clients** (leaks server paths); **`PATCH /jobs/{id}`
  accepts arbitrary dict / unvalidated email**; **JWT `exp` not explicitly required** (add
  `options={"require":["exp","sub","aud"]}` for defense in depth).

**Secrets audit — good news.** `.env` is **not** committed (gitignored, absent from full history),
and `.env.example` holds only placeholders. No rotation needed for git exposure. **But** the
on-disk `.env` holds real production keys (Gemini, Sarvam, Resend, Deepgram) in plaintext, plus
*test-mode* Razorpay keys. Move to an injected secret store for deploy; swap Razorpay to live keys
+ regenerate the webhook secret at launch; treat the four API keys as sensitive if the machine was
ever shared. `DEV_MODE=false` is correctly set, so prod uses real JWKS verification.

---

## 🎬 Media / ML Pipeline Engineer

**Verdict — the Telugu core beats the incumbents; the video craft trails them.** Word-timestamping
(Sarvam Saaras + MMS CTC forced alignment) and caption shaping (locked `ass=`, bundled OFL fonts,
cap-height calibration, escaped ASS text, single `\an5\pos` path) are the best-engineered part of
the whole product and genuinely ahead of Opus/Klap on Telugu. The two-pass rough/fine-cut selector
with genre-aware hook rules is sophisticated. The video-editing half is the weak side.

**Strengths**
- Correct Telugu conjunct shaping treated as a tested invariant — the moat
- ASS injection escaping done right (`_escape_ass_text`)
- Romanized CTC alignment — right call for Tenglish code-mix
- LLM context-caching, partial-JSON salvage, junk/intro/outro pre-filtering
- Multi-segment "cut the sponsor out of the middle" threaded end-to-end

**Beyond the sync blocker (all P1)**
- **"Subject tracking" is a single static crop** — averages all faces into one x; 2 speakers →
  cuts both off; movement drifts out of frame. Biggest gap vs Opus/Klap auto-reframe.
- **Diarization is fetched then discarded** — you pay for it and drop the exact signal that would
  fix multi-face reframe.
- **Four sequential full re-encodes** (cut→crop→overlay→caption), all CPU libx264, no NVENC —
  generational quality loss + cost.
- **LLM selection is a single point of failure** — any exception fails the whole job; no backoff,
  no heuristic fallback despite having embeddings + scoring.
- **`BorderStyle=4` for the caption pill is undefined in libass** (should be 3); preview/unstable
  Gemini model pinned in prod.

**Highest-lift quality wins:** fix sync → real auto-reframe (per-frame detect + EMA/Kalman
smoothing + active-speaker via the diarization you already fetch + blurred-bg fallback) → collapse
the re-encode chain into one `filter_complex` + NVENC → filler-word / dead-air removal (you already
have word timestamps + energy analysis) → auto on-screen hook titles from the `hook_score` you
compute but only rank on.

---

## 🔧 Senior Backend Engineer

**Verdict — a security-conscious MVP that is not yet ready for scale.** The things that were
deliberately hardened (JWT auth, 404-not-403 ownership, webhook replay/ordering guards,
path-traversal on downloads, checkpoint-based pipeline resumption) show real maturity. The
foundations (Redis data layer, job durability, resource management, observability) are
prototype-level and will fall over under real concurrency.

**Strengths**
- Genuinely well-thought-out auth & ownership; owner stamped server-side, never through Celery
- Billing webhook correctness (constant-time HMAC, event ledger, created_at high-water mark)
- Checkpoint pipeline reuses expensive external stages from disk
- Deliberate input hardening where it counts (hex-color validator, PIL byte-sniff)

**Beyond the durability & upload blockers**
- **P1 · Full Redis keyspace scans on hot paths** — `video_owned_by` runs `scan_iter("job:*")` on
  every transcript/download request → O(total jobs across all users). Add per-owner + per-video
  secondary indexes.
- **P1 · Leaked intermediate render files** — `_prepared`/`_canvas` MP4s never deleted; disk grows
  unbounded. Delete in `finally` + add output GC.
- **P1 · Unauthenticated thumbnail route has no path containment** (unlike download).
- **P2 · Observability is `print()` everywhere** — no structured logs, request IDs, or a real
  health check that pings Redis/broker.
- **P2 · Non-atomic multi-write sequences**, no Redis client timeouts/retry, localhost URLs
  hardcoded in `email.py`.

**Infra to add for scale:** split Celery into dedicated queues (heavy pipeline vs rerender), move
job metadata to Postgres + object storage with signed URLs, a crash/orphan reaper on Celery beat,
structured logging + Sentry + cost counters, and per-user rate limits tied to the billing plan.

---

## 🖥️ Senior Frontend / Editor Engineer

**Verdict — A− architecture, B polish. Well above typical "React video tool" quality.** A single
Zustand store with one document model (elements / exportSettings / transcriptEdits) that is the
*same shape* for drafts, undo snapshots and the export payload, so history-restore and
draft-reload physically cannot diverge. The autosave/draft race-hardening is the most robust part
of the entire product.

**Strengths**
- Document-model unification — undo, drafts & export can't drift
- Autosave stale-write guards close every window probed (arming gate, stale-run token, sync
  capture before async PATCH)
- Correct undo coalescing (whole gesture = one frame); single keyboard listener + pure keymap
- Honest disabled states — animations/rotation/mov-webm visibly disabled, not silently lying
  about the burn

**Issues**
- **P1 · Zoom double-scales element font size** — `getBoundingClientRect()` reads the
  post-`scale(zoom)` height, so captions render off-size at any zoom ≠ 1 (default fit is ~0.85).
  Directly breaks the WYSIWYG promise. Thread unscaled `STAGE_DIMS.h` instead.
- **P1 · Caption pill padding/radius in absolute px** — text scales as a fraction of canvas, pill
  padding doesn't → pill hugs text differently in the burn.
- **P2 · Dead `CaptionRenderer.jsx`** reads store fields that no longer exist (would crash if
  mounted) — delete it.
- **P2 · Fake waveform** (120 bars from `Math.sin`) misleads scrubbing; **seek clamps to trim** so
  you can't preview excluded regions.

**Feature wins the model is ready for:** multi-select + group transform (move `selectedElementId`
→ a Set), explicit align/distribute buttons, real waveform + word ticks on the timeline, duplicate
/ copy-paste / z-order hotkeys, and full layout templates (extend the existing "My Style").

---

## 🎨 Senior Product Designer (UX/UI)

**Verdict — high visual craft, mid-stage completeness. It looks like a 9/10 product and behaves
like a 6/10.** A confident dark identity, coherent purple→magenta accent, real type hierarchy, and
standout bilingual creator-native copy. The gap between how good it looks and how much actually
works is exactly what an evaluating user reads as "unfinished" — and almost all of it is cheap to
fix.

**Strengths**
- Distinct, consistent visual identity — nothing looks like a stock template
- Real state handling in the core flow (4-step progress, failure+retry, picks up in-flight job on
  mount)
- Well-considered first-run onboarding (FirstRunHero + one-time "first clips ready" cue, correctly
  gated)
- Telugu ⇄ Tanglish toggle presented as the flagship it is; Export honest about pipeline limits

**Beyond the "front door" blocker**
- **No mobile story at all** — editor is a fixed 3-col grid, shell a fixed sidebar. Unusable
  <800px, for a product whose *output is mobile video*.
- **Fabricated trust signals** — "12,000+ creators", "94 avg virality", a named testimonial, all
  invented.
- **A wall of decorative controls** — search, notification bell w/ unread dot, all filters/sorts,
  social-share buttons: invite a click, do nothing.
- **Dead legal/footer/anchor links**, an inaccessible hand-rolled language dropdown (you already
  have Radix `ui/select`), thin long-job transparency (no elapsed/estimate/cancel/email-me).
- **Low-contrast muted grays** near/below the AA line; two parallel design systems (tokens
  defined, then bypassed with arbitrary hex everywhere).

**Highest-leverage real feature hiding behind fake buttons:** the Export metadata generator
already produces title/description/hashtags — pair it with a working "copy caption + hashtags for
posting" action. Also: hover-to-play clip previews, an editor coach-mark tour, and "email me when
it's done" (the backend already has `email.py`).

---

## 📈 Senior PM / Growth

**Verdict — a strong engine wrapped in an unfinished business.** The moat is real and specific:
correct Telugu caption shaping + byte-identical WYSIWYG + a Tanglish dual-script toggle — things
the English-first tools genuinely get wrong. But monetization is a stub (one ₹499 plan that gates
nothing, no watermark, no metering, no upload cap), retention is actively undermined by the 24h
TTL, and the growth loop (a watermark on free exports) simply doesn't exist.

**The moat**
- Telugu caption *correctness* as a tested invariant — the thing to lead marketing with
- WYSIWYG editor with byte-identical preview↔export + editable word-level transcript
- Genre-aware, culturally-tuned clip selection
- Razorpay + UPI fits the market; Stripe-based competitors can't easily take UPI

**Must-haves to be competitive**
- **Persistent library** (kill the TTL) — table stakes
- **Enforce the paywall** — watermark on free + usage metering by source-minutes (protects margin
  *and* creates the growth loop)
- **Real free-tier limits** the landing page already promises but the backend doesn't enforce
- **Multi-speaker reframe** — your ICP is podcasts; single-face crop is the most visible quality gap
- Remove or wire the dead social-share CTAs

**Pricing** — meter the expensive thing (*source video minutes*), not "projects". A flat ₹499
unlimited plan is a margin trap the moment a power user appears — you're paying for whole-video
Gemini tokens twice per job. Reinstate a 3-tier ladder that matches enforcement (Free w/ hard
watermark → Creator → Studio), and consider UPI one-time credit packs (a ₹99 "10-clip pack" may
out-convert a subscription in this market).

**Hard truth** — Telugu-only long-form→Shorts is a real but modest market (low tens of thousands of
monetizable creators), fine for a lean UPI-billed business but not venture-scale on its own. The
plan has to be "own Indic caption correctness end-to-end — Telugu → Hindi/Tamil/Kannada/Bengali."
Your Tanglish engine + language toggle + Indic SBERT fallback show you already know this. The risk
is polishing Telugu captions for another six months while monetization, retention and distribution
stay broken. **Close that gap next.**

---

## What I'd do next — in order

One sequence that unblocks launch, protects the business, and spends effort where it compounds.
Roughly two focused sprints to a defensible public beta.

1. **Close the security cluster + secure the media** — SSRF host-match, kill/scope
   `/jobs/recover`, bound + validate uploads, validate `crop_box`/style/format, and put signed
   URLs on `/outputs`. Ship the Pydantic validation cluster in the same pass.
   *(Blocks a public launch outright · ~1 sprint)*

2. **Fix the caption-sync defect** — rebase word timing on the refined cut boundaries. Invisible
   to you in dev but visible on every clip a user posts — the difference between "looks broken" and
   "looks professional," on your flagship feature.
   *(Product-quality blocker · small, surgical)*

3. **Durability + retention foundation** — move job/clip metadata off TTL'd Redis into Postgres
   (also kills the O(N) scans), add Celery `acks_late` + an orphan reaper, and wire the dashboard
   to the real persistent library.
   *(Data-loss + scale · ~1 sprint)*

4. **Turn billing into a business + light the growth loop** — watermark on free exports, meter by
   source-minutes, enforce real tiers, reconcile the landing page. Instrument cost-per-job on real
   1–2hr podcasts *before* spending on acquisition.
   *(Margin + distribution · ~1 sprint)*

5. **Ship real auto-reframe (multi-speaker)** — per-frame detect + smoothing + active-speaker via
   the diarization you already fetch + blurred-bg fallback. Your ICP is interviews/podcasts; this
   is the most visible remaining quality gap vs Opus/Captions.
   *(Competitive parity · larger)*

6. **UX honesty pass + WYSIWYG zoom fix** — restore focus rings, hide/remove dead controls, a
   responsive shell + mobile clips view, replace fabricated stats with real sample output, fix the
   editor zoom double-scale. Cheap, high trust-per-hour.
   *(Trust & polish · ongoing)*
