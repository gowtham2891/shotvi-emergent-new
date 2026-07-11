# Shotvi — Product & Engineering Specification

**Version:** 1.0
**Status:** Draft for review
**Owner:** Product/Engineering

---

## 1. Product Overview & Goals

### 1.1 What Shotvi Is

Shotvi turns long-form video into publish-ready short clips. A user pastes a link (YouTube, Vimeo, TikTok, X) or uploads a file; Shotvi transcribes it, finds the moments worth clipping, cuts them, reframes them to vertical, adds animated captions, and hands back a timeline the user can fine-tune — trim, re-caption, re-crop, add B-roll/zooms — without leaving the browser.

### 1.2 Core Goal

**Creators should do nearly all of their short-form editing inside Shotvi and not need CapCut, Premiere, or Descript for the clipping → captioning → export workflow.** Every feature decision is filtered through that goal: if a task forces a user out to another tool, it's a gap in the product, not an acceptable scope boundary.

### 1.3 Success Metrics

| Metric | Target (6mo post-launch) |
|---|---|
| Time from paste-link to first exported clip | < 4 minutes for a 20-min source video |
| % of exports requiring zero manual edits | > 40% |
| % of sessions that touch the manual editor (not just auto-export) | tracked, not optimized — both flows are first-class |
| Clip-to-publish rate (exported clip actually posted) | > 60% |
| Weekly retention (W1) | > 35% |
| Caption WER (word error rate) on English source | < 8% |

### 1.4 Non-Goals (v1)

- Full multi-track NLE (no compositing arbitrary layers, no keyframed motion graphics beyond zoom/pan presets)
- Long-form editing (Shotvi targets clips ≤ 3 minutes)
- Native mobile apps (responsive web first; mobile app is Phase 3)
- Live streaming clipping (real-time stream-to-clip is Phase 3)

---

## 2. Target Users & Use Cases

| Persona | Description | Primary Use Case |
|---|---|---|
| **Solo creator / podcaster** | Records long-form (podcast, vlog, stream VOD), wants daily/weekly shorts | Upload full episode → get 5–10 ranked clip candidates → light edit → schedule to TikTok/Reels/Shorts |
| **Faceless/niche channel operator** | Repurposes YouTube videos (often not their own, licensed/UGC) or aggregates commentary | Paste YouTube link → auto-clip + auto-caption + B-roll → bulk export |
| **Social media manager (agency/brand)** | Manages clipping for multiple clients/brands | Multi-workspace, brand kit (fonts/colors/logo), team review/approval, bulk scheduling |
| **Course creator / coach** | Repurposes webinars and course content into hooks for ads/organic | Precise manual trim control, on-brand caption styles, CTA overlays |
| **Clipping agency / clipper-for-hire** | Clips other creators' long-form content at volume under contract | Batch processing, fast iteration, multiple aspect ratios per source |

### 2.1 Core Use Cases

1. **Fully automated repurposing** — paste link, walk away, come back to ranked clips ready to export.
2. **AI-assisted manual editing** — AI proposes clips and captions; user fine-tunes trim points, caption text/timing, crop focus, and styling before export.
3. **Batch/bulk processing** — queue multiple source videos, get clips for all of them, review in one dashboard.
4. **Brand-consistent output** — apply a saved caption style/brand kit across all clips for a channel.
5. **Direct publish** — export and immediately schedule/post to connected social accounts.

---

## 3. Full Feature List

Priority key: **P0** = blocking for that phase's launch, **P1** = important but can ship slightly after, **P2** = nice-to-have within the phase.

### 3.1 MVP (Phase 1)

| Feature | Priority | Notes |
|---|---|---|
| Paste YouTube/Vimeo link → download via yt-dlp | P0 | Already implemented (`services/video_downloader.py`) |
| Direct file upload (mp4/mov/webm, up to ~2GB) | P0 | |
| Transcription (word-level timestamps) | P0 | Already implemented (`services/transcriber.py`, stable-ts) |
| Smart moment detection / clip selection | P0 | Already implemented (`services/clip_selector.py`) — needs scoring transparency (why this clip was chosen) |
| Auto vertical reframing (16:9 → 9:16) with face/subject tracking | P0 | Already implemented (`services/vertical_cropper.py`, mediapipe) |
| Animated word-by-word captions (karaoke-style highlight) | P0 | Already implemented (`services/caption_renderer.py`) |
| In-browser timeline editor: trim, split, reorder | P0 | Partially implemented (Editor.jsx, TrimSlider.jsx) |
| Caption editing (per-word text/timing correction) | P0 | Partially implemented (`useCaptions.js`) |
| Manual crop/reframe override (drag focus point) | P0 | Partially implemented (VideoCanvas.jsx) |
| Caption style presets (3–5 built-in styles: bold, minimal, highlight-box, etc.) | P0 | |
| Export to MP4 (burned-in captions, vertical) | P0 | |
| Async job processing with progress status | P0 | Already implemented (Celery + worker.py, Processing.jsx) |
| Job dashboard (list of processed videos, clips per video) | P0 | Already implemented (Dashboard.jsx) |
| Auth (email/password + Google OAuth) | P0 | Not yet implemented |
| Usage limits / free tier metering (minutes processed) | P1 | |
| Undo/redo on editor actions | P1 | Already implemented in editorStore |
| Keyboard shortcuts for editor | P1 | Already implemented (react-hotkeys-hook) |
| Multiple aspect ratio export (9:16, 1:1, 4:5) | P1 | |
| Email notification on job completion | P1 | `api/email.py` (resend) exists — wire to job completion |
| Basic title/hook text suggestion per clip | P2 | |

### 3.2 Phase 2

| Feature | Priority | Notes |
|---|---|---|
| Direct publish to TikTok, Instagram Reels, YouTube Shorts | P0 | OAuth + platform upload APIs |
| Post scheduling / content calendar | P0 | |
| Multi-language transcription & caption translation | P0 | |
| Custom caption fonts/colors/animation (full style editor) | P0 | |
| Brand kit (logo watermark, intro/outro, color palette, font) | P0 | |
| B-roll auto-insertion (stock footage matched to transcript keywords) | P1 | Pexels/Storyblocks API |
| AI auto zoom/pan ("Ken Burns") on static talking-head footage | P1 | |
| Silence/filler-word ("um", dead air) auto-removal | P1 | |
| Speaker diarization (multi-speaker labeling, auto speaker-switch reframe) | P1 | |
| Team workspaces (multi-user, roles: owner/editor/viewer) | P1 | |
| Bulk/batch upload queue with priority | P1 | |
| Clip performance analytics (views/engagement pulled back from platforms) | P2 | |
| Background music library + auto-ducking under speech | P2 | |
| AI-generated title/description/hashtags per platform | P2 | |
| Sound effect/emoji caption embellishments | P2 | |

### 3.3 Phase 3

| Feature | Priority | Notes |
|---|---|---|
| Live stream → near-real-time clipping | P1 | Highlight detection on a rolling buffer |
| AI B-roll generation (text-to-video for cutaways) | P1 | Runway/Luma/Sora-class API |
| AI voice cleanup / re-dub / translation dubbing | P1 | ElevenLabs dubbing |
| Auto-generated talking-head avatar variants | P2 | |
| Native mobile apps (iOS/Android) for review & light edit | P1 | |
| Marketplace for caption/style templates | P2 | |
| Collaborative real-time co-editing (Figma-style cursors) | P2 | |
| AI repurposing across formats (clip → carousel/blog/newsletter) | P2 | |
| White-label / API access for agencies | P2 | |

---

## 4. User Flows

### 4.1 Primary Flow: Upload → Generate → Edit → Export/Publish

```
1. LANDING
   User lands on Home → pastes URL or drags a file onto the dropzone.

2. INTAKE
   - URL: backend validates URL, kicks off yt-dlp download job.
   - File: direct upload to object storage (presigned URL), then job enqueued.
   → User redirected to Processing screen with a job ID.

3. PROCESSING (async, polled or websocket-pushed)
   Pipeline stages shown with live progress:
   a. Download/ingest
   b. Transcription (word-level timestamps)
   c. Moment detection / clip scoring
   d. Per-clip: cut → reframe (face/subject track) → caption render preview
   → On completion, user is routed to the Clip Results / Dashboard view.

4. REVIEW CLIP CANDIDATES
   Grid of ranked clip candidates, each with:
   - Thumbnail, duration, a one-line "why this clip" rationale, virality/score badge
   - Quick actions: Edit, Discard, Regenerate caption style, Quick export
   User selects a clip to open the full editor, or multi-selects for bulk export.

5. EDIT (Editor.jsx — the core authoring surface)
   - Vertical canvas preview (VideoCanvas.jsx) with live caption overlay
   - Timeline/trim slider (TrimSlider.jsx): trim in/out, split, ripple-delete
   - Caption panel: per-word text edit, timing nudge, style picker
   - Reframe panel: drag focus box, switch tracked subject, manual keyframe crop
   - Metadata panel (MetadataPanel.jsx): title, description, hashtags, platform target
   - Undo/redo, autosave to draft state (Zustand store, persisted)

6. EXPORT
   User picks aspect ratio(s) + resolution → export job enqueued (server-side
   FFmpeg render, burned-in captions) → progress shown → download link
   and/or "Publish" CTA.

7. PUBLISH (Phase 2)
   User selects connected platform account(s) + caption/hashtags per platform
   → publish immediately or schedule → confirmation + link to live post.
```

### 4.2 Secondary Flow: Batch Processing

```
Dashboard → "New batch" → paste multiple links / upload multiple files
→ single job queue, processed in priority order → user reviews a combined
results dashboard grouped by source video.
```

### 4.3 Secondary Flow: Returning User

```
Login → Dashboard (recent jobs, draft clips, published clips) → resume any
in-progress edit (state restored from autosave) → or start new job.
```

---

## 5. Tech Stack Recommendations

The project already has a working foundation (FastAPI + Celery + Redis + Postgres backend, React 19 + Vite + Zustand + Tailwind 4 frontend, yt-dlp/stable-ts/mediapipe pipeline). Recommendations below build on that rather than proposing a rewrite, and call out where to diverge.

| Layer | Recommendation | Reasoning |
|---|---|---|
| **Frontend framework** | Keep **React 19 + Vite**; do *not* migrate to Next.js | The product is a single authenticated SPA (editor-heavy, not content/SEO-heavy). Next.js's SSR/routing wins don't apply; migrating would be pure churn. Add a thin marketing/landing site in Next.js or Astro *separately* if SEO matters later — keep it decoupled from the app. |
| **State management** | Keep **Zustand** (already adopted) | Already proven in `editorStore.js` for undo/redo + autosave; lighter than Redux for this surface area. |
| **Styling** | Keep **Tailwind CSS v4** | Already adopted; pair with a small design-tokens file (Section 11) rather than a component library, since the editor UI is bespoke. |
| **Canvas/video rendering (editor preview)** | **WebCodecs API + Canvas2D/WebGL** for scrubbing/preview; fall back to `<video>` + CSS overlays where WebCodecs isn't supported | Frame-accurate caption/crop preview without re-encoding; WebCodecs has broad enough support in 2026 (Chromium, Firefox) for a creator-tool audience |
| **Backend API** | Keep **FastAPI** | Already adopted, async-native, pairs cleanly with Celery and Pydantic validation |
| **Task queue** | Keep **Celery + Redis** | Already adopted; suitable for the multi-stage video pipeline (download → transcribe → score → cut → reframe → caption → render). Consider splitting queues by stage (CPU-bound render queue vs. I/O-bound download/API queue) for better worker scaling |
| **Database** | Keep **PostgreSQL** (already in `requirements.txt` via psycopg2) via **SQLAlchemy** (already adopted) | Relational data (users, projects, clips, jobs) with clear FK relationships; Postgres JSONB for flexible fields like transcript/caption payloads |
| **Object storage** | **Cloudflare R2** (or S3) for source videos, rendered clips, thumbnails | R2 has zero egress fees, which matters a lot for a video product serving large files repeatedly; S3-compatible API means no lock-in risk |
| **CDN** | **Cloudflare CDN** in front of R2 for clip delivery/preview streaming | Pairs naturally with R2; low latency for global creator audience |
| **Authentication** | **Clerk** or **Supabase Auth** | Both give OAuth (Google/TikTok login), session management, and webhook hooks for billing without building auth from scratch. Clerk has the more polished pre-built UI components for a fast MVP |
| **Payments/billing** | **Stripe** (Billing + metered usage) | Industry standard; metered billing fits a "minutes processed" usage model cleanly |
| **Hosting — frontend** | **Vercel** or **Cloudflare Pages** | Static SPA build, instant deploys, preview deploys per PR |
| **Hosting — API + workers** | **Fly.io** or **Railway** for API; dedicated **GPU workers** (e.g., RunPod, Modal, or AWS g5 instances) for the ML pipeline | Video/ML processing is bursty and GPU-bound (transcription, reframing); decouple stateless API hosting from GPU compute so you don't pay for idle GPUs on every API request |
| **Background job orchestration at scale** | Consider **Modal** or **Inngest** as Phase 2 alternative/complement to raw Celery | Easier autoscaling of GPU workers per pipeline stage if volume grows beyond what self-managed Celery workers handle well |
| **Monitoring/observability** | **Sentry** (errors), **Grafana + Prometheus** or **Better Stack** (infra/queue metrics), **PostHog** (product analytics) | Job pipelines fail in stage-specific ways (download fails vs. transcription fails vs. render fails) — need per-stage error visibility, not just generic 500s |
| **CI/CD** | **GitHub Actions** | Lint/test on PR, deploy frontend to Vercel, deploy API container to Fly/Railway |

---

## 6. AI Components

| Capability | Recommended Service/Model | Notes |
|---|---|---|
| **Transcription (word-level timestamps)** | **OpenAI Whisper (large-v3) via faster-whisper / stable-ts** (already adopted) or **Deepgram Nova-3** as a hosted alternative | Keep stable-ts locally for cost control at scale; Deepgram is the fallback if self-hosted GPU transcription becomes the bottleneck — much faster, pay-per-minute |
| **Moment detection / clip scoring ("what's the good part")** | LLM-based scoring: **Gemini 2.5 Flash** or **GPT-4.1-mini**-class model fed the transcript + engagement heuristics (pacing, question/hook phrases, sentiment swings, laughter/applause via audio cues) | `google-genai` is already in requirements — keep using Gemini for cost/latency; this is a transcript-in, ranked-segments-out task, doesn't need a frontier model |
| **Title/hook/hashtag generation** | Same LLM (Gemini Flash / GPT-4.1-mini) | Cheap, low-latency, structured-output (JSON mode) |
| **Vertical reframing / subject tracking** | **MediaPipe Face Detection/Pose** (already adopted) for face-track crop; consider **YOLOv8/v11** for general subject detection (slides, multiple speakers, non-face content) as a complement | MediaPipe alone struggles on slides/screen-share/B-roll-only footage — add a general object/saliency detector as fallback crop signal |
| **Captions rendering** | Custom FFmpeg/Canvas renderer (already adopted, `caption_renderer.py`) | Keep server-side burn-in via FFmpeg `drawtext`/ASS subtitles for final export; client-side Canvas/WebGL for live preview only |
| **Speaker diarization** (Phase 2) | **pyannote.audio 3.x** or **Deepgram diarization** | Needed for multi-speaker auto-reframe (switch crop focus to active speaker) |
| **Filler-word/silence removal** (Phase 2) | Derived from existing word-level transcript timestamps — no new model needed, just a silence-gap + filler-word-list heuristic pass | |
| **B-roll matching** (Phase 2) | Transcript keyword extraction (LLM) → **Pexels API** / **Storyblocks API** search | Start with stock footage matching before investing in generative B-roll |
| **AI B-roll generation** (Phase 3) | **Runway Gen-4** or **Luma Ray2** API | Higher cost, defer until B-roll-matching demand is proven |
| **Voice cleanup / dubbing** (Phase 3) | **ElevenLabs** (dubbing + voice isolation) | |
| **Translation (captions)** (Phase 2) | LLM translation (Gemini/GPT) for caption text; keep original timestamps | |

---

## 7. System Architecture

### 7.1 High-Level Diagram (described)

```
┌──────────────┐      ┌────────────────────┐      ┌──────────────────┐
│   Browser     │◄────►│   API (FastAPI)     │◄────►│   PostgreSQL      │
│  React SPA    │ HTTPS│  - Auth/session      │      │  users, projects, │
│  (Vite/       │ /WS  │  - CRUD endpoints    │      │  clips, jobs,     │
│  Zustand)     │      │  - Job enqueue       │      │  transcripts      │
└──────┬────────┘      └─────────┬───────────┘      └──────────────────┘
       │                          │
       │ presigned upload         │ enqueue job
       ▼                          ▼
┌──────────────┐      ┌────────────────────┐
│ Object Storage│      │   Redis (broker)    │
│ (Cloudflare R2)│◄────┤                     │
│ source/clips/  │     └─────────┬───────────┘
│ thumbnails     │               │
└──────┬────────┘                ▼
       │              ┌────────────────────────────────┐
       │              │   Celery Workers (GPU pool)     │
       │              │  Stage 1: download (yt-dlp)     │
       │              │  Stage 2: transcribe (Whisper)  │
       │              │  Stage 3: clip scoring (LLM)    │
       │◄─────────────┤  Stage 4: cut (FFmpeg)          │
       │  read/write  │  Stage 5: reframe (MediaPipe)   │
       │              │  Stage 6: caption render (FFmpeg)│
       │              └─────────────┬────────────────────┘
       │                            │ status updates
       │                            ▼
       │              ┌────────────────────┐
       │              │  Postgres (job state)│ ──► WebSocket/poll push to client
       │              └────────────────────┘
       ▼
┌──────────────┐
│     CDN       │  serves rendered clips/thumbnails to browser & (Phase 2)
│ (Cloudflare)  │  directly to social platform publish APIs
└──────────────┘
```

### 7.2 Data Flow (per job)

1. Client sends URL or uploads file (presigned PUT direct to R2 for files >~50MB to avoid proxying through API).
2. API creates a `Job` row (status=`queued`), enqueues a Celery chain.
3. Worker pipeline runs as a **chain of stage tasks**, each updating `Job.stage` and `Job.progress` in Postgres; client polls `/jobs/{id}` or subscribes via WebSocket for live progress.
4. Each completed clip candidate is persisted as a `Clip` row referencing its transcript segment, crop keyframes, and a rendered preview asset in R2.
5. On user edit (trim/caption/crop changes), the frontend writes draft state to Zustand (persisted locally) and periodically syncs to `PATCH /clips/{id}/draft` — no re-render happens until export is requested.
6. On export, a render job is enqueued that applies the final edit state (trim points, caption overrides, crop keyframes, style) via FFmpeg, writes the output to R2, and returns a CDN URL.
7. (Phase 2) Publish job takes the exported asset + per-platform metadata and calls the target platform's upload API, then polls for publish confirmation.

### 7.3 Why a staged pipeline (not monolithic)

Each stage has different resource needs (download = network-bound, transcription/reframing = GPU-bound, FFmpeg cut/render = CPU-bound). Splitting into discrete Celery tasks per stage allows independent retry (e.g., re-run just captioning without re-transcribing), independent scaling of worker pools, and per-stage progress reporting to the user — important for a product where a 20-minute video might take 2-3 minutes to process and users need to see *what's happening*, not a single spinner.

---

## 8. Database Schema

### 8.1 Key Models

```
User
 - id (uuid, pk)
 - email (unique)
 - auth_provider (enum: email | google | tiktok)
 - plan (enum: free | pro | team)
 - usage_minutes_this_period (int)
 - created_at

Workspace (Phase 2 — team support; v1 can have an implicit 1:1 User:Workspace)
 - id (uuid, pk)
 - owner_user_id (fk -> User)
 - name

WorkspaceMember (Phase 2)
 - workspace_id (fk)
 - user_id (fk)
 - role (enum: owner | editor | viewer)

SourceVideo
 - id (uuid, pk)
 - workspace_id (fk -> Workspace)
 - source_type (enum: url | upload)
 - source_url (nullable)
 - storage_path (R2 key)
 - duration_seconds
 - status (enum: pending | downloading | ready | failed)
 - created_at

Transcript
 - id (uuid, pk)
 - source_video_id (fk -> SourceVideo, 1:1)
 - language
 - words (jsonb: [{word, start, end, confidence}])
 - speakers (jsonb, nullable — diarization output, Phase 2)

Job
 - id (uuid, pk)
 - source_video_id (fk -> SourceVideo)
 - type (enum: pipeline | export | publish)
 - stage (enum: download | transcribe | score | cut | reframe | caption | render | done)
 - status (enum: queued | running | succeeded | failed)
 - progress (float 0-1)
 - error_message (nullable)
 - created_at, updated_at

Clip
 - id (uuid, pk)
 - source_video_id (fk -> SourceVideo)
 - transcript_segment (jsonb: start_word_idx, end_word_idx, start_time, end_time)
 - score (float — virality/quality ranking from clip_selector)
 - score_rationale (text — "why this clip" LLM explanation)
 - crop_keyframes (jsonb: [{time, x, y, w, h, tracked_subject}])
 - caption_style_id (fk -> CaptionStyle, nullable)
 - caption_overrides (jsonb — per-word text/timing edits diffed from Transcript)
 - aspect_ratio (enum: 9:16 | 1:1 | 4:5 | 16:9)
 - status (enum: candidate | draft | exported | published)
 - thumbnail_path (R2 key)
 - created_at, updated_at

CaptionStyle
 - id (uuid, pk)
 - workspace_id (fk, nullable — null = built-in preset)
 - name
 - font, font_size, color, highlight_color, position, animation_type
 - is_builtin (bool)

Export
 - id (uuid, pk)
 - clip_id (fk -> Clip)
 - resolution, aspect_ratio
 - storage_path (R2 key)
 - status (enum: queued | rendering | ready | failed)
 - created_at

SocialAccount (Phase 2)
 - id (uuid, pk)
 - workspace_id (fk)
 - platform (enum: tiktok | instagram | youtube | x)
 - oauth_tokens (encrypted)
 - account_handle

PublishJob (Phase 2)
 - id (uuid, pk)
 - export_id (fk -> Export)
 - social_account_id (fk -> SocialAccount)
 - scheduled_at (nullable)
 - status (enum: scheduled | publishing | published | failed)
 - platform_post_url (nullable)

Subscription
 - id (uuid, pk)
 - user_id (fk)
 - stripe_customer_id, stripe_subscription_id
 - plan, status, current_period_end
```

### 8.2 Key Relationships

- `SourceVideo` 1—N `Clip` (one source produces many candidate clips)
- `SourceVideo` 1—1 `Transcript`
- `Clip` N—1 `CaptionStyle`
- `Clip` 1—N `Export` (same clip can be exported at multiple aspect ratios)
- `Export` 1—N `PublishJob` (same export published to multiple platforms/accounts)
- `Job` is polymorphic over pipeline/export/publish work, always traceable back to a `SourceVideo` or `Export`

---

## 9. API Structure

Base: `/api/v1`

### 9.1 Auth
- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/oauth/google/callback`
- `POST /auth/logout`
- `GET /auth/me`

### 9.2 Source Videos / Ingest
- `POST /videos` — `{source_type: "url", url}` or presigned-upload flow for files
- `POST /videos/upload-url` — returns presigned PUT URL for direct-to-R2 upload
- `GET /videos/{id}`
- `GET /videos` — list (paginated, filterable by workspace/status)
- `DELETE /videos/{id}`

### 9.3 Jobs
- `GET /jobs/{id}` — poll status/stage/progress
- `WS /jobs/{id}/stream` — websocket push for live progress
- `POST /jobs/{id}/retry`

### 9.4 Clips
- `GET /videos/{id}/clips` — ranked candidate list
- `GET /clips/{id}`
- `PATCH /clips/{id}/draft` — autosave editor state (trim, captions, crop)
- `POST /clips/{id}/regenerate-captions`
- `POST /clips/{id}/discard`
- `POST /clips/{id}/restore`

### 9.5 Captions
- `GET /clips/{id}/transcript`
- `PATCH /clips/{id}/transcript` — word-level text/timing edits
- `GET /caption-styles` — built-in + workspace custom styles
- `POST /caption-styles`

### 9.6 Export
- `POST /clips/{id}/export` — `{aspect_ratio, resolution}` → returns Export job id
- `GET /exports/{id}`
- `GET /exports/{id}/download`

### 9.7 Publish (Phase 2)
- `GET /social-accounts`
- `POST /social-accounts/connect/{platform}` — OAuth kickoff
- `POST /exports/{id}/publish` — `{platform, account_id, caption, scheduled_at?}`
- `GET /publish-jobs/{id}`

### 9.8 Billing
- `GET /billing/usage`
- `POST /billing/checkout-session`
- `POST /billing/webhook` (Stripe)

### 9.9 Workspaces (Phase 2)
- `GET/POST /workspaces`
- `POST /workspaces/{id}/members`
- `PATCH /workspaces/{id}/members/{user_id}` — role change

---

## 10. Frontend Structure

### 10.1 Pages (extends current `frontend/src/pages/`)

| Page | Purpose | Status |
|---|---|---|
| `Home.jsx` | Landing/intake — paste URL or upload, marketing copy | Exists |
| `Processing.jsx` | Live job progress (stage indicator, ETA) | Exists |
| `Dashboard.jsx` | List of source videos + their clip candidates, filters/search | Exists |
| `Editor.jsx` | Core clip editor (canvas, timeline, captions, crop, metadata) | Exists |
| `Login.jsx` / `Signup.jsx` | Auth | New |
| `Settings.jsx` | Account, billing, brand kit, connected social accounts | New |
| `Publish.jsx` (Phase 2) | Scheduling/calendar view across platforms | New |
| `WorkspaceSettings.jsx` (Phase 2) | Team members/roles | New |

### 10.2 Components (extends `frontend/src/components/`)

| Component | Purpose | Status |
|---|---|---|
| `Navbar.jsx` | Top nav | Exists |
| `VideoCanvas.jsx` | Vertical preview canvas with caption overlay + crop box | Exists — extend for drag-to-reframe |
| `TrimSlider.jsx` | Timeline trim/split control | Exists |
| `MetadataPanel.jsx` | Title/description/hashtags per clip | Exists |
| `CaptionPanel.jsx` | Per-word caption text/timing editor + style picker | New |
| `ClipCard.jsx` | Candidate clip thumbnail card (score, rationale, quick actions) | New |
| `StylePresetPicker.jsx` | Caption style gallery | New |
| `UploadDropzone.jsx` | Drag/drop + URL paste intake widget | New (currently inline in Home) |
| `ProgressStages.jsx` | Visual pipeline stage tracker | New |
| `PublishModal.jsx` (Phase 2) | Platform selection + scheduling | New |

### 10.3 State Management

- **Zustand** (`store/editorStore.js`, already adopted) — single source of truth for active clip's edit state: trim points, caption overrides, crop keyframes, undo/redo stack, autosave-dirty flag.
- Add a second store, `projectStore.js`, for dashboard-level state (list of videos/jobs, filters) — keep separate from editor state so editor undo/redo history doesn't bloat with unrelated list-view actions.
- Server state (jobs, video lists) via **TanStack Query** (recommended addition) layered on top of `axios` (already adopted) for caching/polling/invalidation — avoids hand-rolled polling loops for job status.

### 10.4 Hooks (extends `frontend/src/hooks/`)

- `useJob.js` (exists) — job status polling
- `useCaptions.js` (exists) — caption state derivation
- `useAutosave.js` (new) — debounced draft sync to `PATCH /clips/{id}/draft`
- `useKeyboardShortcuts.js` (new, wraps react-hotkeys-hook bindings centrally)

---

## 11. UI/UX Guidelines & Design System

### 11.1 Design Principles

1. **Editor-first, not gallery-first.** The clip candidate grid is a launchpad into editing, not the product itself — minimize clicks from "see a clip" to "be editing it."
2. **Show the AI's reasoning.** Every auto-generated clip, caption, or crop decision should have a visible, dismissible rationale ("why this clip," confidence score) — builds trust and teaches the user what the AI optimizes for.
3. **Never block on processing.** Users should be able to start editing clip 1 while clips 2–10 are still rendering.
4. **Mobile-responsive review, desktop-first editing.** Dashboard/review views must work on mobile (creators check status on the go); the full timeline editor can assume desktop viewport in v1.

### 11.2 Design Tokens (Tailwind v4 config basis)

| Token | Value | Use |
|---|---|---|
| Primary | `#6E56F8` (violet) | CTAs, active states, brand |
| Surface (dark mode default) | `#0B0B10` / `#16161E` / `#1F1F29` | App background, panels, cards |
| Accent / success | `#22D3A0` | Export success, "ready" states |
| Warning | `#F5A623` | Processing, low-confidence flags |
| Danger | `#F0506E` | Errors, destructive actions |
| Font — UI | Inter | |
| Font — caption presets | Configurable per style (Montserrat, Poppins, Anton, etc.) | Caption rendering is independent of app UI font |
| Radius | `rounded-xl` (12px) default for cards/panels | |

**Theme:** dark mode as default and primary (video editing tools are conventionally dark to make footage the visual focus); light mode optional Phase 2.

### 11.3 Editor Layout

- Left: clip canvas (vertical preview, 9:16 centered) with overlay crop-box and live captions
- Right: tabbed panel — Captions / Reframe / Style / Metadata
- Bottom: timeline/trim slider spanning full width, with waveform visualization
- Top bar: clip title, undo/redo, export button, aspect ratio switcher

### 11.4 Accessibility

- All editor controls keyboard-navigable (already partially covered by react-hotkeys-hook)
- Caption color/contrast presets must meet WCAG AA for the *generated captions themselves* (this is a user-facing accessibility feature of the product, not just app chrome)
- Screen-reader labels on icon-only buttons

---

## 12. Non-Functional Requirements

### 12.1 Performance

- End-to-end pipeline (download → ranked clips ready) for a 20-minute source video: **target < 4 minutes** using GPU workers for transcription/reframing.
- Editor canvas scrubbing: **< 100ms** seek latency (achieved via pre-rendered low-res proxy preview, not full-res source).
- Export render: **target ≤ 1x realtime** per clip (a 60s clip exports in ≤ 60s) on a dedicated render worker.

### 12.2 Scalability

- Stateless API layer horizontally scalable behind a load balancer.
- GPU worker pool scales independently and elastically (queue depth-based autoscaling) — this is the most expensive and most bursty part of the system; isolate it from API/DB scaling decisions.
- Postgres: plan for read replicas once dashboard/list-query load grows; JSONB columns (transcript, captions, crop keyframes) keep schema flexible without migrations for most pipeline iteration.
- Object storage and CDN scale natively (R2/Cloudflare).

### 12.3 Security

- All source video and rendered clip storage in **private R2 buckets**; access via short-lived signed URLs only.
- OAuth tokens for connected social accounts encrypted at rest (e.g., via KMS-backed field encryption), never exposed to frontend.
- Standard OWASP coverage: parameterized queries (SQLAlchemy ORM default), CSRF protection on session-based endpoints, rate limiting on auth and job-creation endpoints (prevent abuse of expensive pipeline jobs), input validation on uploaded file types/sizes (reject non-video MIME types, cap upload size).
- Webhook signature verification on all inbound webhooks (Stripe, social platform callbacks).
- GDPR/CCPA-aware deletion: deleting a `SourceVideo` cascades to delete R2 assets, not just DB rows.

### 12.4 Reliability

- Each pipeline stage independently retryable (Celery task retry with backoff) without re-running upstream stages.
- Idempotent job creation (dedupe on identical URL + user within a short window to avoid double-billing/double-processing).
- Dead-letter handling: jobs that fail after max retries surface a clear, specific error to the user (e.g., "video is private/unavailable" vs. "transcription failed" vs. generic "something went wrong").

### 12.5 Pricing Model (proposed)

| Tier | Price | Included | Notes |
|---|---|---|---|
| **Free** | $0 | 30 min of source video processed/month, watermarked exports, 720p | Top-of-funnel; watermark is the conversion lever |
| **Creator** | $19–29/mo | 300 min/month, no watermark, 1080p, all caption styles | Primary paid tier, solo creators |
| **Pro** | $49–79/mo | 1000 min/month, 4K export, brand kit, direct publish/scheduling | Power users, small agencies |
| **Team** | $99+/mo + seats | Pooled minutes, workspaces, roles, priority render queue | Agencies |
| **Enterprise/API** (Phase 3) | Custom | API access, SLA, white-label | |

Metering basis: **minutes of source video processed**, not clips generated (aligns cost — GPU time scales with source duration, not clip count) and not export count (don't penalize iteration/re-editing).

---

## 13. Third-Party Integrations

| Category | Provider | Purpose | Phase |
|---|---|---|---|
| Video ingest | yt-dlp (library, not a hosted API) | YouTube/Vimeo/TikTok/X URL download | MVP (already in place) |
| Transcription | Whisper (self-hosted) / Deepgram | Speech-to-text | MVP / scale fallback |
| LLM | Google Gemini (`google-genai`, already in place) | Clip scoring, titles, hashtags, translation | MVP |
| Reframing | MediaPipe (self-hosted) | Face/subject tracking | MVP |
| Object storage | Cloudflare R2 | Source/clip/thumbnail storage | MVP |
| CDN | Cloudflare | Asset delivery | MVP |
| Auth | Clerk or Supabase Auth | Login/OAuth | MVP |
| Payments | Stripe | Subscriptions, metered billing | MVP |
| Transactional email | Resend (already in place) | Job-complete, billing, auth emails | MVP |
| Error monitoring | Sentry | | MVP |
| Product analytics | PostHog | Funnel/retention tracking | MVP |
| Stock B-roll | Pexels API / Storyblocks | B-roll matching | Phase 2 |
| Social publishing | TikTok Content Posting API, Instagram Graph API, YouTube Data API | Direct publish/scheduling | Phase 2 |
| Diarization | pyannote.audio / Deepgram | Multi-speaker support | Phase 2 |
| Voice/dubbing | ElevenLabs | Dubbing, voice isolation | Phase 3 |
| Generative B-roll | Runway / Luma | Text-to-video cutaways | Phase 3 |

---

## 14. Future Roadmap Suggestions

- **AI editing assistant chat** — "make this clip punchier," "trim the boring intro" as natural-language commands against the timeline, not just UI manipulation.
- **Performance feedback loop** — pull post-publish engagement data back from platforms and feed it into the clip-scoring model (per-workspace fine-tuning of "what counts as a good clip for *this* channel").
- **Template marketplace** — creators/agencies publish and sell caption style + brand kit templates.
- **Repurposing beyond video** — auto-generate a blog post, Twitter/X thread, or newsletter snippet from the same transcript, turning Shotvi into a content-repurposing hub rather than a video-only tool.
- **Browser extension** — clip directly from a YouTube/Twitch tab without leaving the page.
- **Live-stream highlight clipping** — rolling-buffer real-time highlight detection for streamers, auto-publishing clips during a live broadcast.
- **White-label/API platform** — let other tools embed Shotvi's clipping pipeline (the "Stripe for short-form video" play).
- **On-device/offline mode** (long-term, low priority) — local processing option for privacy-sensitive enterprise customers.

---

*End of specification.*
