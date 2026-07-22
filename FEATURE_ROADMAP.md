# Shotvi / ClipForge — Feature Roadmap (research-backed)

> Produced by a deep-research pass: 5 search angles → 24 sources fetched → 104 claims extracted →
> 25 verified by 3-vote adversarial fact-checking → **18 confirmed, 7 refuted**. Every load-bearing
> claim below survived verification and carries a citation. Refuted claims and honest gaps are
> listed at the end — read them; they change how much you should trust parts of this.
>
> Companion to `PRODUCT_REVIEW.md` (the six-lens code/product review). That doc says *fix these
> bugs*; this doc says *build these features, in this order, and here's the market evidence why.*

---

## The headline finding (it reframes your strategy)

**"Telugu-first" is not, by itself, a moat — and the research is blunt about this.** Multiple
Indic-focused clippers already ship Telugu, and one overlaps your *exact* feature:

- **Clipdify** — Telugu + 15 other languages (Hindi, Urdu, Bengali, Tamil, Kannada, Malayalam,
  Gujarati, Punjabi, Marathi, etc.), "code-switching ready," and it already does hook/virality
  detection and per-clip auto-reframe. [clipdify.com]
- **ButterCut AI** — markets "native support" for Hinglish, Tamil, **Telugu**, Bengali, Marathi;
  brands itself "the only tool built natively for Indian creators." [buttercut.ai]
- **Replix Captions** (captions.ssktechy.com → replixcaptions.com) — word-by-word **Telugu-script
  AND Tanglish** output burned into MP4 exports in under a minute. **A near-exact overlap with your
  core offering.** [captions.ssktechy.com]
- **Captiq** — an AI caption generator positioned specifically for Hindi + Indian languages, free
  tier. [captiq.io]

So language *breadth* is table-stakes, not differentiation.

**What IS defensible: Indic caption-rendering *correctness*.** Correct Telugu/Tamil conjunct
shaping requires W3C-specified orthographic-syllable boundary recognition that default Unicode
grapheme-cluster handling *fails* at — "default grapheme clusters fail to represent ligatures and
conjuncts in scripts like Tamil." Unicode 15.1's InCB update moved default clusters toward
orthographic syllables for Telugu/Bengali/Devanagari **but not Tamil**, so tailored segmentation is
still required. Competitors *assert* coverage in marketing; none of the sources prove they render
conjuncts correctly. **Your proven conjunct-correct karaoke burn-in is the piece rivals cannot
easily claim — that's the moat to protect and extend (to Tamil, Kannada, Malayalam where it's
hardest).** [W3C i18n Indic Layout Requirements]

**Strategic consequence:** don't market "Telugu support." Market **"captions that don't break your
script"** — and race competitors on the two things they *can't* cheaply copy: rendering correctness
+ depth on the Indian-language AI stack (Sarvam ASR/dubbing). Everything else on this list is you
catching up to table-stakes.

---

## The roadmap

Three tiers: **must-have to be competitive** (table-stakes every clipper ships), **high-value Indic
differentiators** (extend the moat), and **monetization**. Effort is rough (S/M/L).

### 🟥 TIER 1 — Table-stakes (must-have to be taken seriously)

Every benchmarked Western clipper ships these; each is a current Shotvi gap. These don't *win* —
their absence *loses*.

| Feature | Why it's table-stakes | Effort | Notes |
|---|---|---|---|
| **Multi-speaker active-speaker reframe** | Your single static MediaPipe crop is the most visible quality gap on your ICP (podcasts/interviews). Clipdify reframes per-clip; Opus Clip ships ReframeAnything. | **L** | Directly adoptable: **TalkNet-ASD** (ACM MM 2021) does per-frame active-speaker detection at **92.3 mAP**, ingests raw mp4, outputs who's speaking → drives crop-switching on top of your existing face detection. Off-the-shelf, permissive license. [github.com/TaoRuijie/TalkNet-ASD] |
| **Filler-word / silence removal** | Confirmed across **all 9** benchmarked tools — the single most universal feature. | **M** | You already have word-level ASR timestamps + energy analysis (`refine_boundary`); this is mostly logic on data you already compute. |
| **Virality / hook scoring** | Near-universal (Vizard's AI Virality Score 0–100; Opus AI curation). | **S–M** | Extend your existing Gemini two-pass selection to *emit* a 0–100 score you already implicitly compute (`hook_score`) — surface it, rank on it, show it. |
| **Auto emoji / keyword-highlight captions** | Submagic's whole aesthetic; Vizard contextual emoji overlays. Big perceived-quality lift on Reels. | **S–M** | Gemini keyword tagging over your *existing* ASS caption pipeline — you already control the burn. |
| **Auto B-roll** | Opus/Submagic/Vizard all ship transcript-matched stock B-roll. | **L** | Needs a stock library + transcript-to-clip matching. Heaviest of the five; do last in this tier. |

*Sources: reap.video State-of-AI-Clipping-2026; ssemble.com; submagic.co — corroborated across
multiple.*

### 🟦 TIER 2 — High-value Indic differentiators (extend the moat)

These layer on the Indian-language AI stack. **This is where you win, not just catch up** — Western
tools can't easily match Indian-language depth.

| Feature | Why it extends the moat | Effort | Notes |
|---|---|---|---|
| **Upgrade ASR to Sarvam Saaras V3** | Better transcription = better captions = your whole correctness story. Per Sarvam's own IndicVoices benchmark: **19.31% WER** on the top-10 Indian languages (down from ~22% in v2.5), beating GPT-4o Transcribe, Gemini 3 Pro, Deepgram Nova3, ElevenLabs Scribe v2 — with the gap *widening* on the 12 low-resource languages competitors barely cover. | **S–M** | You already use Sarvam Telugu ASR — this is an upgrade, not a new integration. Unlocks credible expansion to other Indian languages where general models are weakest. ⚠️ Vendor-self-reported benchmark. [sarvam.ai/blogs/asr] |
| **Cross-Indic auto-translation / dubbing** | A Telugu creator turns one long-form video into Tamil/Hindi/Kannada clips **in their own cloned voice**. Huge value in India's multilingual market; a feature non-Indic-native competitors structurally can't match. | **L** | **Sarvam Dub**: 11 Indian languages incl. Telugu, with voice cloning (ECAPA-TDNN embeddings) so "audiences hear the same speaker in every language." New pipeline stage: dub audio → re-align → re-caption → re-burn. Prices naturally into a premium tier. [sarvam.ai/apis/dubbing] |
| **Extend conjunct-correct shaping to more Indic scripts** | Your actual moat. Tamil especially — Unicode still doesn't handle its conjuncts by default, so correct rendering is *hard* and rivals likely get it wrong. | **M** | Reuse the shaping/font work you already did for Telugu; each new script correctly rendered is a defensible marketing claim ("captions that don't break") in a new creator market. [W3C i18n] |

### 🟩 TIER 3 — Monetization & packaging (fix the business model)

Your single flat **₹499 (~$6)** plan sits *far* below the Western entry cluster (**$15–23/mo**:
Opus $15, Submagic $19, Vizard ~$14.50–20, Klap $23 — these entry *ranges* are confirmed; ignore
the exact sub-tier numbers, several were refuted). The low INR price is a legitimate India
advantage — but a *single flat plan with no watermark and no metering* leaves both growth and
margin on the table.

- **Add a watermarked free tier.** This is the Opus Clip norm (free = watermark + 60 credits +
  3-day storage; paid removes watermark). It does double duty: top-of-funnel growth loop *and* a
  crisp paid-conversion trigger. You currently have **no watermark** — this is the single missing
  growth mechanic. [ssemble.com]
- **Meter by minutes or credits, not "projects."** Captions.ai meters credits that fund the
  expensive generative features. Do the same so heavy features (dubbing, B-roll) price into higher
  tiers and one power user can't sink your unit economics on ₹499. [cutsnap.ai]
- **Keep the low INR anchor, add a ladder.** Free (watermark) → Creator → Studio, gated by
  minutes/credits and by which Tier-1/Tier-2 features are unlocked. Retain ₹499-ish as the paid
  entry, but stop selling one flat everything-plan.

---

## Feature gap matrix (Shotvi vs the field)

| Capability | Shotvi today | Opus / Submagic / Vizard | Indic clippers (Clipdify/ButterCut/Replix) |
|---|---|---|---|
| Telugu word-by-word captions | ✅ | ❌ (or broken) | ✅ (coverage claimed) |
| **Conjunct-correct shaping** | ✅ **(moat)** | ❌ | ⚠️ unverified — likely weak |
| Tanglish / Roman toggle | ✅ | ❌ | ✅ (Replix) |
| Multi-speaker reframe | ❌ static crop | ✅ | ✅ (Clipdify) |
| Filler-word / silence removal | ❌ | ✅ | partial |
| Virality / hook score | ❌ (computed, not surfaced) | ✅ | ✅ (Clipdify) |
| Auto emoji / keyword highlight | ❌ | ✅ | partial |
| Auto B-roll | ❌ | ✅ | partial |
| Cross-Indic dubbing (voice clone) | ❌ | ❌ | ❌ |
| Watermarked free tier | ❌ | ✅ | varies |
| Usage metering | ❌ | ✅ | varies |

The two rows where you can *own* the market: **conjunct-correct shaping** and **cross-Indic dubbing**.
Everything else is catch-up.

---

## Suggested build order

1. **Virality-score surfacing + auto-emoji captions** (S–M, high perceived-value, reuses your
   pipeline) — cheapest credibility wins.
2. **Filler-word / silence removal** (M, reuses your timestamps) — the most universal missing feature.
3. **Watermarked free tier + usage metering** (M) — unlocks the growth loop and protects margin;
   do alongside 1–2.
4. **Saaras V3 ASR upgrade** (S–M) — quietly improves the whole product and your moat.
5. **Multi-speaker reframe via TalkNet-ASD** (L) — the biggest visible quality jump for your ICP.
6. **Cross-Indic dubbing** (L) — the premium, defensible differentiator; prices a Studio tier.
7. **Auto B-roll** (L) and **more Indic scripts** (M) — round out parity + extend the moat.

---

## ⚠️ Caveats & honest gaps (don't skip this)

**Refuted claims** (killed by 2+ of 3 verifiers — do *not* rely on these):
- Exact competitor sub-tier prices were unreliable: "Opus Starter $9 / 150 min", "Submagic Starter
  $14 / 20 videos", and the specific Captions.ai tier table were all refuted. **Only the $15–23/mo
  *entry cluster* and Opus's watermarked-free-tier structure survived** — treat exact numbers as
  approximate and re-check on the vendors' own pricing pages before you set yours.
- "72% of Indian creators use Hinglish captions / 52% higher Gen-Z retention" — **refuted**, don't
  cite it.
- "Telugu creators' primary demand is caption spelling accuracy" — **refuted**, unproven.

**The biggest evidence gap:** research area 2 (**Indic/Telugu creator demand**) produced **zero
surviving claims** — both candidate demand statistics were refuted. So the *market-demand* rationale
for these features rests on competitor behavior and general India-SaaS pricing psychology, **not on
verified Telugu-creator demand data.** Before committing heavy build (dubbing, B-roll), validate
demand directly: talk to 15–20 Telugu podcast/creator channels. This is the one thing the research
could *not* substitute for.

**Source quality:** Sarvam's ASR/dubbing numbers are **vendor-self-reported** on their own
IndicVoices benchmark — cite as "per Sarvam's own benchmark," not independent fact. Indic-competitor
capabilities come from **marketing pages** (coverage claims, not verified rendering quality) — which
is exactly *why* your conjunct-shaping moat is plausible, but also means nobody has measured how bad
rivals' Telugu actually looks. The strongest-sourced claims here are **TalkNet-ASD** (peer-reviewed)
and the **W3C Indic-layout** standards — build confidently on those.

**Open question worth answering next:** what's the actual conjunct-rendering quality of
Clipdify/ButterCut/Replix on real Telugu? Nobody benchmarked it. If you run that comparison and they
*are* broken, you have shareable, self-selecting proof of your moat — the single most valuable piece
of marketing you could produce.

---

## Sources (verified-claim-bearing)

- reap.video — State of Top AI Video Clipping Tools 2026 (competitor/pricing)
- ssemble.com — 11 Best AI Clipping Tools 2026 (pricing/metering, watermark norms)
- cutsnap.ai — Captions.ai pricing 2026 (credit metering)
- clipdify.com — Indic clipper, Telugu + 15 langs (primary)
- buttercut.ai — Indian-native clipper positioning
- captions.ssktechy.com / replixcaptions.com — Replix, direct Telugu+Tanglish overlap
- captiq.io — Hindi/Indic caption generator (primary)
- github.com/TaoRuijie/TalkNet-ASD — active-speaker detection, 92.3 mAP (primary, peer-reviewed)
- sarvam.ai/blogs/asr — Saaras V3 ASR benchmark (primary, vendor-reported)
- sarvam.ai/apis/dubbing — Sarvam Dub, 11 Indian languages + voice cloning (primary)
- lists.w3.org/…/public-i18n-archive — W3C Indic Layout Requirements (primary, standards)
- submagic.co, bigvu.tv, lumiclip.ai — feature corroboration (blog, directional)
- rizevault.razorpay.com, upgrowth.in, productgrowth.in, eximpe.com — India SaaS pricing psychology
