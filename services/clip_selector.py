"""
ClipForge AI — Clip Selector (v16 — Two-Call Vision Pipeline)
=============================================================
Major change from v15: Split single overloaded Gemini call into two
focused calls, like a human editor's rough cut → fine cut workflow.

WHAT CHANGED FROM v15:
  - Removed: build_vision_prompt() (single overloaded call)
  - Removed: trim_long_clip() (absorbed into Call 2)
  - New: build_rough_cut_prompt() — Call 1: find all genuine Reel
    moments using video+transcript, return only sent IDs + why.
    No scoring, no field filling, no forced clip count.
  - New: build_fine_cut_prompt() — Call 2: given Call 1 candidates,
    perfect each one using cached video + transcript. Fix hooks,
    fix payoffs, trim filler, score, rank. Reject weak candidates.
  - New: gemini_rough_cut() — executes Call 1
  - New: gemini_fine_cut() — executes Call 2 with context caching
  - New: create_cache() / delete_cache() — manages Gemini context
    cache so Call 2 reuses video tokens cheaply
  - gemini_select_clips() — orchestrates both calls
  - select_clips() — updated stage labels

UNCHANGED:
  - upload_video_to_file_api()
  - All segmentation + junk detection logic
  - segments_to_timestamps(), attach_transcripts()
  - compute_virality_score(), ENGAGEMENT_TIER_BOOST
  - Output JSON schema
  - CLI interface
  - MAX_CLIPS = 10 as Python safety cap only (never mentioned in prompts)
"""

import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai as google_genai
from google.genai import types as genai_types

load_dotenv()

# ── Models ────────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-3-flash-preview"

# ── Embedding model ──────────────────────────────────────────────────────────
EMBEDDING_MODEL       = "l3cube-pune/telugu-sentence-similarity-sbert"
EMBEDDING_MODEL_INDIC = "l3cube-pune/indic-sentence-similarity-sbert"

# ── Clip constraints ──────────────────────────────────────────────────────────
# MAX_CLIPS is a Python safety cap only — never mentioned in prompts
# Gemini decides how many clips to select based on content quality
MAX_CLIPS       = 10
MAX_CLIP_LENGTH = 90    # seconds (target, not hard cutoff)

# ── Segmentation ──────────────────────────────────────────────────────────────
TEXTILING_WINDOW       = 3
VALLEY_THRESHOLD_ALPHA = 1.5
MAX_SEGMENT_DURATION   = 180
MIN_SEGMENT_DURATION   = 10
MARKER_BOOST_WINDOW    = 3

# ── Discourse markers (boost signals) ────────────────────────────────────────
DISCOURSE_MARKERS = [
    r"point\s+number\s+\d+",
    r"point\s+\d+",
    r"\d+\s*వ\s+point",
    r"number\s+\d+",
    r"^ముందుగా\b",
    r"^చివరగా\b",
    r"^మొదటగా\b",
    r"^రెండవది\b",
    r"^మూడవది\b",
    r"^next\s+point\b",
    r"^next\s+",
    r"^so\s+ఇప్పుడు\b",
    r"^point\s+number\b",
]

# ── Junk detection ────────────────────────────────────────────────────────────
STRONG_JUNK_WORDS = {
    "subscribe", "notification", "bell",
    "sponsor", "sponsored", "discount", "coupon", "promo",
}
PHRASE_JUNK = [
    "like and subscribe", "like share", "please like",
    "like చేయండి", "comment చేయండి", "comment below",
    "follow చేయండి", "follow us", "follow me",
    "link in description", "link in bio", "pinned comment",
    "description-లో link", "free consultation",
    "see you in the next", "see you next",
    "bye bye", "that's all for today",
    "welcome back", "thank you for watching",
    "ధన్యవాదాలు", "thanks for watching",
]
INTRO_PHRASES = [
    "welcome back", "welcome to", "what's up", "hey guys", "hello everyone",
    "నమస్కారం", "hi friends", "today's video", "ఈ video లో",
    "in this video", "in today's video",
]
OUTRO_PHRASES = [
    "see you in the next", "see you next", "bye bye", "that's all",
    "thank you for watching", "thanks for watching",
    "ధన్యవాదాలు", "next video లో", "వచ్చే video",
]
WEAK_PAYOFF_PHRASES = [
    "video చూడండి", "watch video", "video లో చూడండి",
    "video starting", "ముందు చెప్పిన", "earlier discussed",
    "చెప్తాను", "point చెప్తాను", "చూద్దాం",
    "techniques we discussed", "ముందు చూసిన",
    "అర్థమైందా",
]


HOOK_STRIP_PREFIXES = [
    r"^and\s+", r"^but\s+", r"^so\s+", r"^see[,\s]+",
    r"^yes[,\s]+", r"^now[,\s]+", r"^okay[,\s]+", r"^well[,\s]+",
    r"^actually[,\s]+", r"^basically[,\s]+", r"^of course[,\s]+",
    r"^అందుకే\s+", r"^కానీ\s+", r"^కాబట్టి\s+", r"^అయితే\s+",
    r"^అలాగే\s+", r"^దాంతో\s+", r"^ఎందుకంటే\s+", r"^అంటే\s+",
    r"^ఎవరైనా\s+", r"^ఇప్పుడు\s+", r"^అక్కడ\s+", r"^ఇక్కడ\s+",
]

def strip_hook_prefix(hook_text: str) -> str:
    text = hook_text.strip()
    changed = True
    while changed:
        changed = False
        for pattern in HOOK_STRIP_PREFIXES:
            new_text = re.sub(pattern, "", text, flags=re.IGNORECASE)
            if new_text != text:
                text = new_text.strip()
                text = text[0].upper() + text[1:] if text else text
                changed = True
    return text

# ── Engagement type ranking tiers ─────────────────────────────────────────────
ENGAGEMENT_TIER_BOOST = {
    "Emotional":     0.5,
    "Controversial": 0.5,
    "Story":         0.5,
    "Relatable":     0.5,
    "Humor":         0.3,
    "Educational":   0.0,
    "Wisdom":        0.0,
    "Insight":       0.0,
    "Other":        -0.2,
}


def is_weak_payoff(text: str) -> bool:
    lower = text.lower()
    for phrase in WEAK_PAYOFF_PHRASES:
        if phrase.lower() in lower:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Utilities — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def load_transcript(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sentences = data.get("sentences", [])
    print(f"✓ Loaded transcript: {len(sentences)} sentences")
    if not sentences:
        raise RuntimeError("No sentences in transcript.")
    return data


def is_junk_text(text: str) -> bool:
    lower = text.lower()
    for kw in STRONG_JUNK_WORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", lower):
            return True
    for phrase in PHRASE_JUNK:
        if phrase in lower:
            return True
    return False


def is_intro_text(text: str) -> bool:
    return any(p in text.lower() for p in INTRO_PHRASES)


def is_outro_text(text: str) -> bool:
    return any(p in text.lower() for p in OUTRO_PHRASES)


def is_discourse_marker(text: str) -> bool:
    lower_text = text.lower().strip()
    for pattern in DISCOURSE_MARKERS:
        if re.search(pattern, lower_text, re.IGNORECASE):
            return True
    return False


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    n = len(vectors[0])
    result = [0.0] * n
    for v in vectors:
        for i, x in enumerate(v):
            result[i] += x
    return [x / len(vectors) for x in result]


def get_sentences_in_range(sentences: list[dict],
                           start: float, end: float) -> list[dict]:
    return [s for s in sentences if s["end"] > start and s["start"] < end]


def parse_json_response(text: str, source: str) -> Optional[dict]:
    if text is None:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"^```\s*",     "", cleaned)
    cleaned = re.sub(r"\s*```$",     "", cleaned)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  [Parse] ✗ {source} JSON error: {e}")
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        print(f"  [Parse] Raw ({source}):\n{text[:400]}")
        return None


def _salvage_partial_json(raw: str) -> list:
    clips = []
    depth = 0
    start = None
    for i, c in enumerate(raw):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(raw[start:i + 1])
                    if "start_sent_id" in obj:
                        clips.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None
    return clips


# ═══════════════════════════════════════════════════════════════════════════════
# Embedding model — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

_embed_model = None

def get_embed_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    try:
        from sentence_transformers import SentenceTransformer
        print(f"  [Embed] Loading {EMBEDDING_MODEL}...")
        t0 = time.time()
        try:
            _embed_model = SentenceTransformer(EMBEDDING_MODEL)
        except Exception as e:
            print(f"  [Embed] Primary model failed ({e}), trying Indic fallback...")
            _embed_model = SentenceTransformer(EMBEDDING_MODEL_INDIC)
        print(f"  [Embed] Model loaded in {time.time() - t0:.1f}s")
    except ImportError:
        print("  [Embed] ⚠ sentence-transformers not installed — skipping")
        _embed_model = None
    return _embed_model


def embed_sentences(sentences: list[dict]) -> list[list[float]]:
    model = get_embed_model()
    if model is None:
        return [[] for _ in sentences]
    texts = [s["text"] for s in sentences]
    try:
        embeddings = model.encode(texts, show_progress_bar=False,
                                  device="cuda", batch_size=64)
        return [e.tolist() for e in embeddings]
    except Exception as e:
        print(f"  [Embed] ✗ CUDA failed: {e}, trying CPU...")
        try:
            embeddings = model.encode(texts, show_progress_bar=False,
                                      device="cpu", batch_size=32)
            return [e.tolist() for e in embeddings]
        except Exception as e2:
            print(f"  [Embed] ✗ CPU also failed: {e2}")
            return [[] for _ in sentences]


# ═══════════════════════════════════════════════════════════════════════════════
# Stage 1 — Segmentation — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def find_embedding_boundaries(sentences, embeddings):
    if not embeddings or not embeddings[0]:
        return []
    n = len(sentences)
    k = TEXTILING_WINDOW
    if n < 2 * k + 2:
        return []
    similarities = []
    for i in range(k, n - k - 1):
        left  = mean_vector(embeddings[max(0, i - k):i + 1])
        right = mean_vector(embeddings[i + 1:i + k + 2])
        sim   = cosine_similarity(left, right)
        similarities.append((i, sim))
    if not similarities:
        return []
    depths = []
    for j in range(1, len(similarities) - 1):
        i, sim_i = similarities[j]
        _, sim_prev = similarities[j - 1]
        _, sim_next = similarities[j + 1]
        depth = (sim_prev - sim_i) + (sim_next - sim_i)
        depths.append((i, depth))
    if not depths:
        return []
    depth_vals = [d for _, d in depths]
    mean_d = sum(depth_vals) / len(depth_vals)
    std_d  = math.sqrt(sum((d - mean_d) ** 2 for d in depth_vals) / len(depth_vals))
    threshold = mean_d + VALLEY_THRESHOLD_ALPHA * std_d
    valleys = [(i, depth) for i, depth in depths if depth > threshold]
    for i, depth in valleys:
        s = sentences[i]
        print(f"    [TextTile] Valley at s{i} ({s['start']:.1f}s) "
              f"depth={depth:.3f}: {s['text'][:50]}")
    return valleys


def find_marker_indices(sentences):
    markers = set()
    for i, s in enumerate(sentences):
        if is_discourse_marker(s["text"]):
            markers.add(i)
            print(f"    [Marker] Found at s{i} ({s['start']:.1f}s): {s['text'][:60]}")
    return markers


def build_segments(sentences, boundaries, embeddings):
    if not sentences:
        return []
    sorted_boundaries = sorted(boundaries)
    groups = []
    current_group = []
    for i, s in enumerate(sentences):
        if i in sorted_boundaries and current_group:
            groups.append(current_group)
            current_group = [s]
        else:
            current_group.append(s)
    if current_group:
        groups.append(current_group)
    segments = []
    seg_id = 0
    for group in groups:
        start    = group[0]["start"]
        end      = group[-1]["end"]
        duration = end - start
        if duration < MIN_SEGMENT_DURATION:
            continue
        if duration > MAX_SEGMENT_DURATION:
            mid = len(group) // 2
            sub_groups = [group[:mid], group[mid:]]
        else:
            sub_groups = [group]
        for sg in sub_groups:
            s_start = sg[0]["start"]
            s_end   = sg[-1]["end"]
            s_dur   = s_end - s_start
            if s_dur < MIN_SEGMENT_DURATION:
                continue
            full_text = " ".join(s["text"].strip() for s in sg)
            segments.append({
                "seg_id":    seg_id,
                "sentences": sg,
                "start":     round(s_start, 2),
                "end":       round(s_end, 2),
                "duration":  round(s_dur, 2),
                "full_text": full_text,
                "is_junk":   False,
            })
            seg_id += 1
    return segments


def segment_transcript(sentences):
    print(f"  [Seg] Computing embeddings for {len(sentences)} sentences...")
    embeddings = embed_sentences(sentences)
    print(f"  [Seg] Pass 1 (PRIMARY): Neural TextTiling...")
    valleys = find_embedding_boundaries(sentences, embeddings)
    print(f"  [Seg] Found {len(valleys)} embedding valleys")
    print(f"  [Seg] Pass 2 (BOOST): Discourse marker scan...")
    marker_indices = find_marker_indices(sentences)
    print(f"  [Seg] Found {len(marker_indices)} markers")
    valley_set = set(i for i, _ in valleys)
    all_boundaries = set(valley_set)
    for m_idx in marker_indices:
        nearby = any(abs(m_idx - v_idx) <= MARKER_BOOST_WINDOW
                     for v_idx in valley_set)
        if not nearby:
            all_boundaries.add(m_idx)
            s = sentences[m_idx]
            print(f"    [Boost] Marker at s{m_idx} ({s['start']:.1f}s) added")
        else:
            print(f"    [Boost] Marker at s{m_idx} reinforces existing valley")
    print(f"  [Seg] Total boundaries: {len(all_boundaries)}")
    segments = build_segments(sentences, all_boundaries, embeddings)
    print(f"\n  [Seg] {len(sentences)} sentences → {len(segments)} segments:")
    for seg in segments:
        print(f"    Seg {seg['seg_id']:>2} [{seg['start']:.0f}s-{seg['end']:.0f}s] "
              f"({seg['duration']:.0f}s) {seg['full_text'][:55].strip()}...")
    return segments


def filter_junk(segments, video_duration):
    for seg in segments:
        if seg["is_junk"]:
            continue
        sents = seg["sentences"]
        total_sents = len(sents)
        junk_count = sum(1 for s in sents
                         if is_junk_text(s["text"])
                         or is_intro_text(s["text"])
                         or is_outro_text(s["text"]))
        junk_ratio = junk_count / total_sents if total_sents > 0 else 0
        if junk_ratio > 0.5:
            seg["is_junk"] = True
            print(f"    [Filter] Seg {seg['seg_id']}: {junk_count}/{total_sents} "
                  f"junk sentences ({junk_ratio:.0%}) → marking junk")
    junk_count = sum(1 for s in segments if s["is_junk"])
    print(f"  [Filter] {junk_count}/{len(segments)} segments marked as junk")
    return segments


def get_junk_sentence_ids(segments) -> set:
    """
    Collect IDs of sentences the LLM should treat as junk.

    Two-layer flagging:
      1. All sentences in segments marked is_junk (segment-level — existing).
      2. Individual sentences where is_junk_text() / is_intro_text() / is_outro_text()
         fire, EVEN IF the surrounding segment is mostly organic content.
         This catches sponsor reads, mid-roll CTAs, and intro/outro lines that
         sit inside otherwise-good segments — e.g. the Ditto insurance block
         tucked inside a diabetes-content segment.
    """
    junk_ids = set()
    for seg in segments:
        if seg["is_junk"]:
            # Layer 1: whole-segment junk
            for s in seg["sentences"]:
                junk_ids.add(s["id"])
        else:
            # Layer 2: individual sponsor / CTA / intro / outro sentences
            # inside an otherwise-organic segment.
            for s in seg["sentences"]:
                if (is_junk_text(s["text"])
                        or is_intro_text(s["text"])
                        or is_outro_text(s["text"])):
                    junk_ids.add(s["id"])
    return junk_ids


# ═══════════════════════════════════════════════════════════════════════════════
# Virality score — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def compute_virality_score(hook_score: float, coherence_score: float,
                           cultural_score: float, engagement_score: float,
                           engagement_type: str) -> float:
    base = (
        hook_score       * 0.4 +
        coherence_score  * 0.3 +
        cultural_score   * 0.2 +
        engagement_score * 0.1
    )
    boost = ENGAGEMENT_TIER_BOOST.get(engagement_type, 0.0)
    return round(min(base + boost, 10.0), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# Video Upload — unchanged from v15
# ═══════════════════════════════════════════════════════════════════════════════

def upload_video_to_file_api(video_path: str, client) -> str:
    print(f"  [Upload] Uploading {Path(video_path).name} to Gemini File API...")
    t0 = time.time()
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"  [Upload] File size: {file_size_mb:.1f} MB")
    try:
        with open(video_path, "rb") as f:
            uploaded_file = client.files.upload(
                file=f,
                config={
                    "mime_type": "video/mp4",
                    "display_name": Path(video_path).stem,
                }
            )
    except Exception as e:
        raise RuntimeError(f"File upload failed: {e}")
    print(f"  [Upload] Uploaded — name: {uploaded_file.name}, "
          f"state: {uploaded_file.state}")
    max_wait = 300
    poll_interval = 5
    waited = 0
    while uploaded_file.state.name != "ACTIVE":
        if waited >= max_wait:
            raise RuntimeError(
                f"File {uploaded_file.name} never became ACTIVE after {max_wait}s"
            )
        if uploaded_file.state.name == "FAILED":
            raise RuntimeError(f"File processing FAILED: {uploaded_file.name}")
        print(f"  [Upload] State: {uploaded_file.state.name} — "
              f"waiting {poll_interval}s...")
        time.sleep(poll_interval)
        waited += poll_interval
        uploaded_file = client.files.get(name=uploaded_file.name)
    elapsed = time.time() - t0
    print(f"  [Upload] ✓ File ACTIVE in {elapsed:.1f}s — URI: {uploaded_file.uri}")
    return uploaded_file.uri


# ═══════════════════════════════════════════════════════════════════════════════
# NEW: Context Cache — reuse video tokens across both calls
# ═══════════════════════════════════════════════════════════════════════════════

def create_cache(file_uri: str, sentences: list[dict],
                 junk_ids: set, client) -> Optional[str]:
    """
    Create a context cache containing the video + transcript.
    Returns cache name, or None if caching fails (fallback to direct call).
    Cache TTL: 5 minutes (minimum allowed) — enough for both calls.
    """
    sent_list = ""
    for s in sentences:
        marker = " ⚠JUNK" if s["id"] in junk_ids else ""
        sent_list += (f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: "
                      f"{s['text']}{marker}\n")

    try:
        cache = client.caches.create(
            model=GEMINI_MODEL,
            config=genai_types.CreateCachedContentConfig(
                contents=[
                    genai_types.Content(
                        parts=[
                            genai_types.Part.from_uri(
                                file_uri=file_uri,
                                mime_type="video/mp4",
                            ),
                            genai_types.Part(text=f"TRANSCRIPT:\n{sent_list}"),
                        ],
                        role="user",
                    )
                ],
                ttl="300s",  # 5 minutes — minimum allowed
                display_name="clipforge_video_cache",
            ),
        )
        print(f"  [Cache] ✓ Created: {cache.name} (TTL: 5min)")
        return cache.name
    except Exception as e:
        print(f"  [Cache] ⚠ Cache creation failed: {e} — will use direct calls")
        return None


def delete_cache(cache_name: str, client) -> None:
    """Delete cache after use to avoid storage charges."""
    try:
        client.caches.delete(name=cache_name)
        print(f"  [Cache] ✓ Deleted: {cache_name}")
    except Exception as e:
        print(f"  [Cache] ⚠ Delete failed: {e} (will expire automatically)")


# ═══════════════════════════════════════════════════════════════════════════════
# NEW: Call 1 — Rough Cut Prompt
# ═══════════════════════════════════════════════════════════════════════════════


def build_rough_cut_prompt(video_duration: float, n_sentences: int) -> str:
    return f"""You are a senior Telugu Reels editor watching a {video_duration:.0f}s video.

You have the video AND the full transcript with sentence IDs and timestamps.
IMPORTANT: Sentence IDs range from 0 to {n_sentences - 1}. Never use IDs outside this range.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — DETECT CONTENT TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Read the first 15 sentences of the transcript carefully.
Classify this video as EXACTLY ONE of these types:

  Motivational    — personal growth, mindset, self-help, relationships, people-pleasing,
                    confidence, discipline, boundaries, success habits
  Geopolitics     — international news, India vs US/China/Pakistan, treaties, trade deals,
                    war, diplomacy, world leaders, national pride
  Finance         — money, investing, stocks, mutual funds, real estate, salary, tax,
                    business, startups, wealth building
  Health          — fitness, nutrition, medicine, mental health, sleep, diet, disease,
                    body science, doctors, medical myths
  Story           — narrative-driven, personal experience, case study, someone's journey,
                    event retelling, documentary style
  Teaching        — structured explainer, step-by-step tutorial, concept breakdown,
                    history lesson, science explanation, how-to
  Comedy          — humor, satire, roast, reactions, entertainment-first content
  Other           — anything that doesn't fit above

Output your classification first, then proceed to Step 2.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — APPLY TYPE-SPECIFIC HOOK RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Based on your classification, use the matching hook rules below.
These rules define what makes a viewer STOP SCROLLING for this content type.

─── IF Motivational ───────────────────────────────────
STRONG hooks (viewer stops immediately):
  - Direct personal challenge: "మీరు ఇది చేస్తున్నారంటే మీరు తప్పు చేస్తున్నారు"
  - Myth-bust: "అందరూ అనుకుంటారు X మంచిది, కానీ X వల్లే Y జరుగుతుంది"
  - Consequence-first: Start at the moment of highest personal impact, not the setup
  - Middle-class relatability: job pressure, family expectations, self-worth struggles
  - Counter-intuitive: "Nice గా ఉండటమే మీ పెద్ద పొరపాటు"
  - Shocking self-label: "మీరు ఇప్పుడు ఒక trap-లో ఉన్నారు"

WEAK hooks — NEVER use these as start sentences:
  - Section openers: "Point number 1", "First reason", "Next point"
  - Transitions: "అందుకే", "కాబట్టి", "So మనం", "దాంతో", "అంటే"
  - Mid-explanation: sentences that assume viewer already heard something
  - Pure setup: "Today I want to talk about X" type intros
  - Rhetorical question without immediate payoff hint

VIRAL TRIGGERS for Motivational:
  Identity Threat, Middle-Class Relatability, Loss Aversion, Pattern Interrupt,
  Controversial Take, Myth Busting

─── IF Geopolitics ────────────────────────────────────
STRONG hooks (viewer stops immediately):
  - National pride moment: India refusing to bow, standing firm, winning diplomatically
  - Shocking reveal: "X దేశం Y చేసింది" where Y is unexpected or alarming
  - Direct quote reveal: A world leader said something shocking — lead with what they said
  - Treaty/power shift: Something that changed the world order today
  - India angle: How this affects India specifically — always more viral than pure global news
  - Counter-narrative: "వాళ్ళు అంటున్నారు X కానీ నిజం Y"
  - Urgency hook: "ఇవాళ జరిగిన ఒక విషయం మీకు తెలియాలి"
  - Specific shocking fact: Number, date, name + unexpected action

WEAK hooks — NEVER use these as start sentences:
  - Background context: "Let me explain what happened in 1972..."
  - Name introductions: "Dmitry Medvedev అని previous President in Russia" — 
    this is setup, not a hook. The TWEET is the hook, not who tweeted it.
  - "Today I want to cover", "In this video", "Before I start"
  - Transition sentences mid-analysis
  - Setup sentences that require prior context to understand

VIRAL TRIGGERS for Geopolitics:
  National Pride, Outrage/Shock, Curiosity Gap, Fear/Threat, Social Currency
  (viewer shares to show they're informed), Pattern Interrupt

─── IF Finance ────────────────────────────────────────
STRONG hooks (viewer stops immediately):
  - Money mistake reveal: "ఈ ఒక్క mistake వల్ల మీరు లక్షలు పోగొట్టుకుంటున్నారు"
  - Wealth secret: "Rich people చేసే ఒక పని మీకు తెలియదు"
  - Shocking number: Specific amount + unexpected context
  - Common myth bust: "Mutual funds safe అని అనుకుంటున్నారా? వినండి"
  - Direct consequence: "మీరు ఇప్పుడు ఇది చేయకపోతే 10 సంవత్సరాల తర్వాత పశ్చాత్తాపడతారు"
  - Relatability: Salary, EMI, savings pressure that every middle-class person feels

WEAK hooks — NEVER use these as start sentences:
  - Definitions: "Compound interest అంటే ఏంటంటే..."
  - Historical background: "1991-లో liberalization జరిగింది..."
  - "In this video I will explain"
  - Pure technical setup with no emotional hook

VIRAL TRIGGERS for Finance:
  Loss Aversion, Curiosity Gap, Social Currency, Identity Threat

─── IF Health ─────────────────────────────────────────
STRONG hooks (viewer stops immediately):
  - Myth bust: "అందరూ X healthy అంటారు కానీ X వల్ల Y జరుగుతుంది"
  - Personal threat: "మీరు రోజూ ఇది చేస్తున్నారంటే మీ body-కి ఇది జరుగుతుంది"
  - Shocking body fact: Specific, unexpected, visceral
  - Common habit danger: Something everyone does revealed as harmful
  - Doctor/expert contradiction: "Doctors చెప్పని నిజం"

WEAK hooks:
  - Medical definitions, anatomy explanations as openers
  - "Today we will learn about X condition"
  - Pure statistics without personal threat angle

VIRAL TRIGGERS for Health:
  Loss Aversion, Fear/Threat, Identity Threat, Myth Busting

─── IF Story ──────────────────────────────────────────
STRONG hooks (viewer stops immediately):
  - Start at the most dramatic moment: not the beginning of the story
  - Consequence-first: "ఆ రోజు వాడు ఒక్క decision తీసుకున్నాడు, అది వాడి జీవితాన్నే మార్చేసింది"
  - Unexpected character action: Something the person did that nobody expected
  - Emotional peak: The moment of highest tension or revelation in the story
  - "ఏం జరిగిందంటే..." when what happened is genuinely shocking

WEAK hooks:
  - "Let me tell you about X person" introductions
  - Background/childhood setup as opener
  - Chronological story starts from the beginning

VIRAL TRIGGERS for Story:
  Curiosity Gap, Emotional Impact, Pattern Interrupt, Social Currency

─── IF Teaching ───────────────────────────────────────
STRONG hooks (viewer stops immediately):
  - The most surprising fact in the entire explanation — lead with it
  - "మీకు ఇది తెలియదు కానీ..." followed by genuinely unknown fact
  - Common misunderstanding reveal: "అందరూ ఇలా అర్థం చేసుకుంటారు కానీ అసలు విషయం వేరు"
  - Direct utility: "ఈ ఒక్క విషయం తెలిస్తే మీకు X లో ఎప్పుడూ problem రాదు"
  - Counterintuitive fact that makes viewer rethink something familiar

WEAK hooks:
  - "Today I will teach you about X"
  - Definitions as openers
  - "Step 1 is..." as the very first sentence
  - Historical context before the surprising revelation

VIRAL TRIGGERS for Teaching:
  Curiosity Gap, Social Currency, Identity Threat, Pattern Interrupt

─── IF Comedy or Other ────────────────────────────────
STRONG hooks:
  - The funniest or most absurd moment — don't bury it
  - Unexpected punchline setup that makes viewer need to see payoff
  - Relatable situation stated in a surprising way

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — FIND CLIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Now scan the full transcript using the hook rules for your detected content type.

YOUR JOB:
Watch the video and read the transcript together. Find every moment that deserves
to be a standalone Instagram Reel or YouTube Short for a Telugu 18-35 urban audience.

For each moment:
1. Identify the precise HOOK sentence — where a stranger stops scrolling
2. Identify the precise PAYOFF sentence — where the tension resolves
3. Set start_sent_id to the hook, end_sent_id to the payoff

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOOK SCANNING PROCESS (mandatory for every candidate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Step 1 — Identify the interesting segment
Step 2 — Start from the MIDDLE of that segment, not the beginning
Step 3 — Scan BACKWARD to find the earliest sentence that works as a cold open
Step 4 — Validate: would a stranger with zero context feel something in 2 seconds?
          If no — move FORWARD one sentence and repeat

UNIVERSAL HOOK REJECTIONS (applies to ALL content types):
  - Any sentence starting with: "అందుకే", "కాబట్టి", "అయితే", "దాంతో", "అలాగే",
    "ఎందుకంటే", "అంటే", "So మనం", "that's why", "so", "but", "also", "next"
  - Mid-story references: sentences with "అతను", "ఆమె", "అది", "ఆ వ్యక్తి" where
    that person was NOT introduced inside this clip
  - Pure name introductions: "X అని Y in Z" — the person's ACTION is the hook, not who they are
  - Section headers: "Point number 1", "Next point", "Moving on to"
  - Continuation fragments: clearly mid-sentence, mid-thought, mid-explanation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRUCTURAL DEAD ZONES (detect visually from the video)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Telugu YouTube videos always have dead zones. Watch the
video carefully to identify them:

ZONE 1 — CHANNEL INTRO (typically first 15-90 seconds):
  Visual signals: intro animation, logo, music bed,
  host saying hi/నమస్కారం/welcome, channel name mentioned,
  "today we will cover X" setup sentences.
  Rule: NEVER start a clip inside this zone.
  Exception: If the very first sentence of the video is
  already a strong viral hook (shocking fact, myth bust,
  consequence-first statement) — KEEP IT as the start.
  A strong hook at second 0 is gold. Do not waste it.

ZONE 2 — SPONSOR SEGMENT (anywhere in video):
  Visual signals: host suddenly changes tone, mentions
  a product/app/service, discount codes, "link in
  description", screen recording of an app, unnatural
  energy shift mid-content.
  Rule: NEVER include sponsor content in any clip.
  Tool: Use the segments array to skip it exactly the
  same way middle filler is already trimmed.
  Example — clip with sponsor in the middle:
  segments: [
    {{"start_sent_id": 5, "end_sent_id": 22}},
    {{"start_sent_id": 31, "end_sent_id": 45}}
  ]
  This keeps the hook (5-22), cuts the sponsor (23-30),
  continues with the content (31-45).

ZONE 3 — CHANNEL OUTRO (typically last 30-90 seconds):
  Visual signals: subscribe animation appears, bell icon,
  host saying bye/ధన్యవాదాలు/next video లో కలుద్దాం,
  like and share requests, end screen cards appearing,
  energy drops, host wrapping up.
  Rule: NEVER end a clip inside this zone.
  If a candidate ends here — move end_sent_id BACKWARD
  until you are before the outro begins.

KEY INSIGHT — Strong hooks can appear anywhere:
  If the video starts with a viral hook at second 0,
  KEEP IT. The hook is the start. Just use the segments
  array to cut any sponsor or dead zone in the middle,
  then continue with the payoff content.

  Pattern for hook-at-start with middle dead zone:
  segments: [
    {{"start_sent_id": 0, "end_sent_id": 15}},
    {{"start_sent_id": 28, "end_sent_id": 42}}
  ]

  This preserves the strong opening hook (0-15),
  cuts the dead middle (16-27 — sponsor/intro animation),
  continues with the meat of the content (28-42).

IMPORTANT: Use the VIDEO to detect these zones, not
just the text. Intro animation and music are obvious
visually even if the transcript text seems fine.
The segments array is your primary tool — use it
aggressively to cut dead zones just like middle filler.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PAYOFF RULES (same for all content types)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The payoff must:
  - Resolve the tension the hook created
  - End with a complete thought
  - NOT end on: "చెప్తాను", "చూద్దాం", CTAs, subscribe requests, mid-thought fragments
  - Be the strongest possible ending — if natural end is weak, walk back one sentence

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIP QUALITY RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Target 30-90 seconds per clip
- Each clip must stand completely alone — zero prior context needed
- Return only moments that genuinely deserve to be posted
- If only 2 exist, return 2. If 8 exist, return 8. Never pad with weak moments.
- Skip: ⚠JUNK sentences, intros, outros, CTAs, subscribe requests

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELF-CHECK BEFORE OUTPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For every clip ask:
1. Does the hook match the STRONG hook patterns for my detected content type?
2. Is the hook a UNIVERSAL REJECTION sentence? If yes — move forward.
3. Would a stranger with zero context feel something in 2 seconds? If no — reject.
4. Does the payoff resolve what the hook promised? If no — find a better payoff.
5. Is the clip 30-90 seconds? If under 30s — extend the window.
6. Does it need zero prior context? If no — reject or find an earlier hook.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY valid JSON. No markdown, no explanation:
{{
  "content_type": "<detected type>",
  "candidates": [
    {{
      "start_sent_id": 3,
      "end_sent_id": 18,
      "why": "<one sentence: complete story arc — setup, tension, resolution>",
      "visual_energy": "<one sentence: what you saw/heard at the exact hook moment in the video>",
      "hook_type": "<which strong hook pattern from the type-specific rules above>"
    }}
  ]
}}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# NEW: Call 2 — Fine Cut Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def build_fine_cut_prompt(candidates: list[dict], sentences: list[dict],
                          sent_by_id: dict, video_id: str = "",
                          first_sentences: list[dict] = None) -> str:

    clip_id_prefix = video_id if video_id else "clip"

    candidates_text = ""
    for i, cand in enumerate(candidates, 1):
        s_id = int(cand.get("start_sent_id", 0))
        e_id = int(cand.get("end_sent_id", 0))
        cand_sents = [sent_by_id[j] for j in range(s_id, e_id + 1)
                      if j in sent_by_id]
        sent_text = ""
        for s in cand_sents:
            sent_text += f"    {s['id']} [{s['start']:.1f}s]: {s['text']}\n"
        candidates_text += f"""
CANDIDATE {i}: sentences {s_id}-{e_id}
Why identified: {cand.get('why', '')}
Visual energy at hook: {cand.get('visual_energy', '')}
Sentences:
{sent_text}"""

    return f"""You are a senior Telugu Reels editor. You have already watched the video and identified candidate clip boundaries with precise hooks and payoffs. Your job now is purely analytical — no boundary decisions, no hook hunting.

━━━ YOUR JOB ━━━
For each candidate:
1. Accept the boundaries as given (start_sent_id and end_sent_id are already correct)
2. Check for middle filler and trim if needed
3. Decide: is this clip good enough to post? If not — reject it
4. Score all 4 dimensions honestly
5. Rank across all clips

You are NOT re-selecting hooks. You are NOT changing start or end boundaries unless trimming middle filler.

━━━ STEP 1 — REJECT OR ACCEPT ━━━
Reject the entire clip if:
- No emotional arc — purely informational list with no tension
- Two candidates cover the same topic — keep only the stronger one
- Clip is under 15 seconds
- Sponsor/CTA content anywhere in the clip
- Hook score would be below 6 — a weak hook cannot be saved by good content
- Hook sentence is a transition, section header, mid-explanation, or mid-story reference — even if Call 1 missed it:
  - Section openers: "X-లో main-గా Y రకాలు ఉంటాయి", "X విషయానికి వస్తే..."
  - Mid-explanation: sentences starting with "So మనం...", "దాంతో...", "అంటే...", "See ప్రతి..." that assume prior context
  - Pure educational list with no cold-open value — if a complete stranger wouldn't stop scrolling in 2 seconds, reject
- Channel intro detected (visually — host greeting,
  intro animation, music, channel name mention):
  If clip START falls inside the intro zone, trim it
  using segments array to skip to real content.
  Exception: if sentence 0 is a genuine viral hook,
  keep it — the strong opening is the point.
- Sponsor segment detected anywhere in the clip:
  Use segments array to cut it out surgically.
  Do not reject the whole clip — just remove the
  sponsor section and keep the content around it.
- Channel outro detected (subscribe animation, bell,
  bye bye, end screen cards, energy drop at end):
  If clip END falls in the outro zone, move end_sent_id
  backward until you are before the outro.
  Never end a clip on a subscribe request or CTA.
- Strong hook at video start:
  If the very first sentence is already viral-worthy,
  do NOT reject it for being "too early in the video."
  Keep it. Use segments array to cut any dead zone
  that follows, then resume with the content.
  A hook at second 0 is an asset, not a problem.



━━━ STEP 2 — INTELLIGENT TRIMMING ━━━
Review every candidate for middle filler — repetition, tangents, sponsor reads, energy drops.
Drop filler ONLY IF the sentence before and after the cut still connect naturally.
Use segments array for non-contiguous clips.
Target 30-75 seconds. Strong content up to 90s is acceptable.
Never trim if it breaks coherence.

SURGICAL SINGLE-SENTENCE REMOVAL:
Sometimes only ONE sentence in a clip is bad — a CTA,
a video reference, or a sponsor line buried in otherwise
good content.

In these cases, use a 2-segment array to remove JUST
that one sentence, keeping everything else intact:

segments: [
  {{"start_sent_id": X, "end_sent_id": Y}},
  {{"start_sent_id": Y+2, "end_sent_id": Z}}
]
Where Y+1 is the single bad sentence being removed.

CRITICAL: After removing a sentence, verify the join:
Read the last sentence of Part 1 and the first sentence
of Part 2 back to back out loud. Ask: does this feel
natural? Does the viewer need to know what was removed?

If Part 2's first sentence references something from
Part 1's context (not from the removed sentence),
the join is NATURAL — keep it.

If Part 2's first sentence references something ONLY
in the removed sentence, the join is BROKEN — either:
  a) Move Part 2 start forward to find a better entry
  b) Or move Part 1 end backward to keep more context

The goal: a viewer watching the stitched clip should
never feel something is missing.

━━━ STEP 3 — SCORE HONESTLY ━━━
- hook_score (1-10): How hard does the opening stop the scroll? Score the sentence as-is.
- coherence_score (1-10): How complete is the story arc — setup → tension → resolution?
- cultural_score (1-10): How strongly does it resonate with Telugu 18-35 urban audience?
- engagement_score (1-10): How likely is share/save vs just watch?

Score honestly — not generously. A 7 means good. A 9 means exceptional.

━━━ STEP 4 — RANK ━━━
confidence_rank 1 = the clip you'd post first if you could only post one.

RANKING PRIORITY:
- Hook accessibility first — can a complete stranger understand it in 2 seconds?
- Emotional impact second — shock, relatability, curiosity
- Story arc completeness third
- Content depth last

━━━ WHAT MAKES TELUGU CONTENT GO VIRAL (for scoring reference) ━━━
- Myth-busting ("అందరూ అనుకుంటారు X, కానీ అసలు నిజం Y")
- Consequence-first hooks ("ఈ ఒక్క mistake వల్ల కోట్లు పోతాయి")
- Middle-class struggle relatability
- Shocking fact with emotional reframe
- Story arc with clear hero + conflict + resolution
- Speaker visibly energised — leaning in, raised voice, dramatic pause

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON. No markdown, no explanation.

{{
  "clips": [
    {{
      "clip_id": "{clip_id_prefix}_c1",
      "segments": [
        {{"start_sent_id": 10, "end_sent_id": 18}}
      ],
      "confidence_rank": 1,
      "confidence_note": "<trigger name>: <max 15 words why this works for Telugu audience>",
      "hook_text": "<exact text of start_sent_id sentence>",
      "payoff_text": "<exact text of end_sent_id sentence>",
      "why": "<complete story arc in max 12 words>",
      "visual_note": "<what was seen/heard at hook moment from visual_energy field>",
      "engagement_type": "<Emotional|Story|Controversial|Educational|Relatable|Humor|Wisdom|Insight>",
      "hook_score": 8,
      "coherence_score": 9,
      "cultural_score": 8,
      "engagement_score": 7,
      "psychological_trigger": "<e.g. Curiosity Gap, Myth Busting, Middle-Class Relatability, Controversial Take>",
      "trimmed": false,
      "trim_reason": "",
      "notes": ""
    }}
  ]
}}

━━━ SELF-CHECK BEFORE OUTPUT ━━━
1. Did you change any start_sent_id or end_sent_id without trimming justification? If yes — revert.
2. Is hook_text the exact text of the start_sent_id sentence? If no — fix it.
3. Is payoff_text the exact text of the end_sent_id sentence? If no — fix it.
4. Are confidence_ranks unique integers starting from 1? If no — fix it.
5. Did you reject duplicates — two clips on the same topic? If no — drop the weaker one.

━━━ CANDIDATES ━━━
{candidates_text}

Return ONLY valid JSON.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Timestamps helper — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def segments_to_timestamps(clip_segments: list[dict],
                            sent_by_id: dict) -> tuple[float, float, float, bool]:
    if not clip_segments:
        return 0.0, 0.0, 0.0, False
    all_starts = []
    all_ends   = []
    total_duration = 0.0
    for seg in clip_segments:
        s_id = seg.get("start_sent_id")
        e_id = seg.get("end_sent_id")
        if s_id is None or e_id is None:
            return 0.0, 0.0, 0.0, False
        try:
            s_id = int(s_id)
            e_id = int(e_id)
        except (ValueError, TypeError):
            return 0.0, 0.0, 0.0, False
        start_sent = sent_by_id.get(s_id)
        end_sent   = sent_by_id.get(e_id)
        if start_sent is None or end_sent is None:
            return 0.0, 0.0, 0.0, False
        seg_start = start_sent["start"]
        seg_end   = end_sent["end"]
        if seg_end <= seg_start:
            return 0.0, 0.0, 0.0, False
        all_starts.append(seg_start)
        all_ends.append(seg_end)
        total_duration += seg_end - seg_start
    clip_start = min(all_starts)
    clip_end   = max(all_ends)
    return (round(clip_start, 2), round(clip_end, 2),
            round(total_duration, 2), True)


# ═══════════════════════════════════════════════════════════════════════════════
# NEW: Call 1 — Rough Cut Execution
# ═══════════════════════════════════════════════════════════════════════════════

def gemini_rough_cut(file_uri: str, sentences: list[dict],
                     junk_ids: set, video_duration: float,
                     cache_name: Optional[str], client) -> list[dict]:
    """
    Call 1: Find all genuine Reel moments.
    Uses cached content if available, otherwise direct call.
    Returns list of {start_sent_id, end_sent_id, why, visual_energy}.
    """
    prompt = build_rough_cut_prompt(video_duration, len(sentences))
    print(f"  [Call 1] Rough cut — finding candidate moments...")

    try:
        if cache_name:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    cached_content=cache_name,
                    thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                    max_output_tokens=16384
                ),
            )
        else:
            # Fallback: direct call with video + transcript inline
            sent_list = ""
            for s in sentences:
                marker = " ⚠JUNK" if s["id"] in junk_ids else ""
                sent_list += (f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: "
                              f"{s['text']}{marker}\n")
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    genai_types.Part.from_uri(
                        file_uri=file_uri,
                        mime_type="video/mp4",
                    ),
                    f"TRANSCRIPT:\n{sent_list}\n\n{prompt}",
                ],
                config=genai_types.GenerateContentConfig(
                    thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )

        raw = response.text
        print(f"  [Call 1] Response: {len(raw)} chars")
        print(f"  [Call 1] RAW:\n{raw[:2000]}")

    except Exception as e:
        raise RuntimeError(f"Rough cut API call failed: {e}")

    result = parse_json_response(raw, "rough-cut")

    if result and "candidates" in result:
        candidates = result["candidates"]
        # log the detected content type if present
        content_type = result.get("content_type", "unknown")
        print(f"  [Call 1] Detected content type: {content_type}")
    elif result and isinstance(result, list):
        candidates = result
    else:
        candidates = _salvage_partial_json(raw)

    if not candidates:
        raise RuntimeError("Rough cut returned no candidates")

    print(f"  [Call 1] ✓ Found {len(candidates)} candidate moments")
    for i, c in enumerate(candidates, 1):
        print(f"    Candidate {i}: s{c.get('start_sent_id')}-s{c.get('end_sent_id')} "
            f"[{c.get('hook_type', '')}] — {c.get('why', '')[:60]}")

    return candidates


# ═══════════════════════════════════════════════════════════════════════════════
# NEW: Call 2 — Fine Cut Execution
# ═══════════════════════════════════════════════════════════════════════════════

def gemini_fine_cut(candidates: list[dict], sentences: list[dict],
                    sent_by_id: dict, junk_ids: set,
                    file_uri: str, cache_name: Optional[str],
                    video_id: str, client) -> list[dict]:
    """
    Call 2: Perfect each candidate — fix hooks, payoffs, trim, score, rank.
    Uses cached content if available.
    Returns list of finalised clip dicts.
    """
    # Validate candidates have valid sentence IDs
    n_sentences = len(sentences)
    valid_candidates = []
    for c in candidates:
        try:
            s_id = int(c.get("start_sent_id", -1))
            e_id = int(c.get("end_sent_id", -1))
        except (ValueError, TypeError):
            continue
        # Clamp to valid range instead of skipping
        s_id = max(0, min(s_id, n_sentences - 1))
        e_id = max(0, min(e_id, n_sentences - 1))
        if e_id <= s_id:
            print(f"  [Call 2] ⚠ Invalid candidate s{s_id}-s{e_id} after clamping — skipping")
            continue
        c["start_sent_id"] = s_id
        c["end_sent_id"]   = e_id
        valid_candidates.append(c)

    if not valid_candidates:
        raise RuntimeError("No valid candidates for fine cut")

    prompt = build_fine_cut_prompt(valid_candidates, sentences,
                               sent_by_id, video_id,
                               first_sentences=sentences[:15])
    print(f"  [Call 2] Fine cut — perfecting {len(valid_candidates)} candidates "
          f"({len(prompt)} prompt chars)...")

    try:
        if cache_name:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    cached_content=cache_name,
                    thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                    max_output_tokens=65536,
                ),
            )
        else:
            # Fallback: rebuild full context inline
            sent_list = ""
            for s in sentences:
                marker = " ⚠JUNK" if s["id"] in junk_ids else ""
                sent_list += (f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: "
                              f"{s['text']}{marker}\n")
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    genai_types.Part.from_uri(
                        file_uri=file_uri,
                        mime_type="video/mp4",
                    ),
                    f"TRANSCRIPT:\n{sent_list}\n\n{prompt}",
                ],
                config=genai_types.GenerateContentConfig(
                    thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                    max_output_tokens=32768,
                    response_mime_type="application/json",
                ),
            )

        raw = response.text
        print(f"  [Call 1] Response: {len(raw)} chars")
        print(f"  [Call 1] Raw response:\n{raw}")

    except Exception as e:
        raise RuntimeError(f"Fine cut API call failed: {e}")

    result = parse_json_response(raw, "fine-cut")

    if result and "clips" in result:
        gemini_clips = result["clips"]
    elif result and isinstance(result, list):
        gemini_clips = result
    else:
        gemini_clips = _salvage_partial_json(raw)

    if not gemini_clips:
        raise RuntimeError("Fine cut returned no clips")

    print(f"  [Call 2] ✓ Fine cut returned {len(gemini_clips)} clips")

    # ── Post-process fine cut output ─────────────────────────────────
    final_clips = []

    for gc in gemini_clips:
        # Handle both segments array and flat start/end
        clip_segments = gc.get("segments")
        if not clip_segments:
            s_id = gc.get("start_sent_id")
            e_id = gc.get("end_sent_id")
            if s_id is not None and e_id is not None:
                clip_segments = [{"start_sent_id": int(s_id),
                                   "end_sent_id":   int(e_id)}]
            else:
                print(f"  [Clip] ⚠ No segments or start/end — skipping")
                continue

        # Map to timestamps
        clip_start, clip_end, content_duration, is_valid = segments_to_timestamps(
            clip_segments, sent_by_id
        )

        if not is_valid:
            print(f"  [Clip] ⚠ Invalid timestamps — skipping")
            continue

        if content_duration < 5:
            print(f"  [Clip] ⚠ Too short ({content_duration:.1f}s) — skipping")
            continue

        # Hook and payoff
        hook_sent_id   = int(clip_segments[0].get("start_sent_id", 0))
        payoff_sent_id = int(clip_segments[-1].get("end_sent_id", 0))
        hook_sent      = sent_by_id.get(hook_sent_id)
        payoff_sent    = sent_by_id.get(payoff_sent_id)

        hook_text   = gc.get("hook_text")   or (hook_sent["text"]   if hook_sent   else "")
        hook_text   = strip_hook_prefix(hook_text)
        payoff_text = gc.get("payoff_text") or (payoff_sent["text"] if payoff_sent else "")

        # Skip junk hooks
        if hook_sent_id in junk_ids:
            print(f"  [Clip] ⚠ Hook s{hook_sent_id} is junk — skipping")
            continue



        hook_score       = float(gc.get("hook_score",       5.0))
        coherence_score  = float(gc.get("coherence_score",  5.0))
        cultural_score   = float(gc.get("cultural_score",   5.0))
        engagement_score = float(gc.get("engagement_score", 5.0))
        engagement_type  = gc.get("engagement_type", "Insight")

        virality_score = compute_virality_score(
            hook_score, coherence_score, cultural_score,
            engagement_score, engagement_type
        )

        clip = {
            "clip_id":               gc.get("clip_id",
                                            f"{video_id or 'clip'}_c{len(final_clips)+1}"),
            "start":                 clip_start,
            "end":                   clip_end,
            "duration":              content_duration,
            "segments":              clip_segments,
            "confidence_rank":       int(gc.get("confidence_rank", 99)),
            "confidence_note":       gc.get("confidence_note", ""),
            "hook_text":             hook_text,
            "payoff_text":           payoff_text,
            "why":                   gc.get("why", ""),
            "visual_note":           gc.get("visual_note", ""),
            "engagement_type":       engagement_type,
            "hook_score":            hook_score,
            "coherence_score":       coherence_score,
            "cultural_score":        cultural_score,
            "engagement_score":      engagement_score,
            "psychological_trigger": gc.get("psychological_trigger", ""),
            "trimmed":               gc.get("trimmed", False),
            "trim_reason":           gc.get("trim_reason", ""),
            "notes":                 gc.get("notes", ""),
            "virality_score":        virality_score,
            "para_id":               hook_sent_id,
            "anchor_text":           payoff_text,
            "anchor_score":          round(virality_score, 2),
        }
        if clip["confidence_rank"] < 1:
            print(f"  [Clip] ⚠ Rejected by Gemini (rank={clip['confidence_rank']}) — skipping")
            continue

        print(f"  [Clip] rank={clip['confidence_rank']} "
              f"[{clip_start:.1f}s→{clip_end:.1f}s] content={content_duration:.1f}s "
              f"segs={len(clip_segments)} virality={virality_score} "
              f"hook='{hook_text[:50]}'")

        final_clips.append(clip)

    # Sort by confidence_rank
    final_clips.sort(key=lambda c: c["confidence_rank"])

    # Overlap filter
    used_sent_ids: set[int] = set()
    ranked_clips = []
    for clip in final_clips:
        clip_sent_ids = set()
        for seg in clip["segments"]:
            s_id = int(seg["start_sent_id"])
            e_id = int(seg["end_sent_id"])
            clip_sent_ids.update(range(s_id, e_id + 1))
        overlap = clip_sent_ids & used_sent_ids
        if overlap:
            print(f"  [Overlap] Dropping rank={clip['confidence_rank']} "
                  f"— {len(overlap)} overlapping sentences")
            continue
        used_sent_ids |= clip_sent_ids
        ranked_clips.append(clip)

    # Python safety cap — never mentioned in prompts
    ranked_clips = ranked_clips[:MAX_CLIPS]
    return ranked_clips


# ═══════════════════════════════════════════════════════════════════════════════
# Long-clip trim — third call, fires only on clips > TRIM_TRIGGER_SEC
# ═══════════════════════════════════════════════════════════════════════════════

# Hard ceiling: clips longer than this get trimmed by a 3rd Gemini call.
# Anything under stays untouched.
TRIM_TRIGGER_SEC = 90
# Target after trimming. Model is asked to land at-or-under this.
TRIM_TARGET_SEC  = 75


def build_trim_prompt(clip: dict, segment_sentences: list[dict]) -> str:
    """
    Build the prompt for the trim call. We give the model the over-length
    clip's existing hook/payoff and the full sentence list it currently spans,
    then ask it to drop the weakest filler so the result lands ≤ TRIM_TARGET_SEC.
    """
    sent_list = ""
    for s in segment_sentences:
        sent_list += (f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s] "
                      f"({s['end'] - s['start']:.1f}s): {s['text']}\n")

    current_duration = clip.get("duration", clip["end"] - clip["start"])

    return f"""You are a senior video editor doing a precise trim on a clip that
is too long for a Reel / Short. Your only job: drop the weakest filler so the
final clip lands at or under {TRIM_TARGET_SEC} seconds, while keeping the
hook and the payoff intact.

CURRENT CLIP (too long — {current_duration:.1f}s):
  Title:  {clip.get('title', clip.get('confidence_note', 'untitled'))}
  Hook:   {clip.get('hook_text', '(unknown)')}
  Payoff: {clip.get('payoff_text', '(unknown)')}

SENTENCES IN THE CLIP (with timestamps and per-sentence duration):
{sent_list}

RULES — read carefully:
  1. You MUST keep the hook sentence and the payoff sentence — they are
     load-bearing. Do not drop either.
  2. You MAY drop one or more contiguous middle sentences if they are
     tangents, repetitions, or weak filler.
  3. You MAY split the clip into two contiguous sub-segments by dropping a
     middle chunk — this is preferred over a hard truncate.
  4. The final clip's total duration MUST be ≤ {TRIM_TARGET_SEC} seconds.
     This is non-negotiable. If you cannot get under that without losing
     hook or payoff, return the smallest tight version you can.
  5. Do NOT add new sentences. Only drop / split existing ones.
  6. Return the result as JSON with this exact shape:

{{
  "segments": [
    {{"start_sent_id": <int>, "end_sent_id": <int>}}
  ],
  "trim_reason": "<one short sentence explaining what you dropped and why>"
}}

If the segments list has 1 entry the clip is contiguous. If it has 2 entries
the clip is split (drops the gap between them). Never return more than 2.
Return ONLY the JSON object, no preamble.
"""


def gemini_trim_long_clip(clip: dict, sentences: list[dict], sent_by_id: dict,
                          cache_name: Optional[str], client) -> dict:
    """
    Trim one over-length clip via a focused 3rd Gemini call.

    Returns the clip with updated segments / start / end / duration / trim_reason.
    On failure, returns the original clip unchanged (no exception bubbles up —
    a failed trim should not break the whole pipeline).
    """
    # Gather the sentences this clip currently spans (across all its segments)
    segment_sentences: list[dict] = []
    for seg in clip.get("segments", []):
        s_id = int(seg["start_sent_id"])
        e_id = int(seg["end_sent_id"])
        for sid in range(s_id, e_id + 1):
            if sid in sent_by_id:
                segment_sentences.append(sent_by_id[sid])

    if not segment_sentences:
        print(f"  [Trim] ⚠ Clip has no resolvable sentences — keeping as-is")
        return clip

    prompt = build_trim_prompt(clip, segment_sentences)

    try:
        if cache_name:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    cached_content=cache_name,
                    thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                ),
            )
        else:
            # No cache available — just send the prompt as text. We don't need
            # the video again here since we're picking from existing sentences.
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                ),
            )
        raw = response.text
    except Exception as e:
        print(f"  [Trim] ⚠ API call failed ({e}) — keeping clip as-is")
        return clip

    result = parse_json_response(raw, "trim")
    if not result or "segments" not in result:
        print(f"  [Trim] ⚠ Could not parse trim response — keeping clip as-is")
        return clip

    new_segments = result.get("segments", [])
    if not new_segments or not isinstance(new_segments, list):
        print(f"  [Trim] ⚠ No segments in trim response — keeping clip as-is")
        return clip

    # Resolve new segments back to time boundaries
    try:
        resolved = []
        for seg in new_segments[:2]:  # cap at 2 segments per the prompt rules
            s_id = int(seg["start_sent_id"])
            e_id = int(seg["end_sent_id"])
            if s_id not in sent_by_id or e_id not in sent_by_id:
                continue
            if e_id < s_id:
                continue
            resolved.append({"start_sent_id": s_id, "end_sent_id": e_id})
    except (KeyError, ValueError, TypeError) as e:
        print(f"  [Trim] ⚠ Malformed segment IDs ({e}) — keeping clip as-is")
        return clip

    if not resolved:
        print(f"  [Trim] ⚠ No valid segments after resolution — keeping clip as-is")
        return clip

    # Compute new start / end / duration. For split clips the "duration" is
    # the *sum* of segment durations (what the viewer actually sees), not the
    # span from first start to last end.
    new_start = sent_by_id[resolved[0]["start_sent_id"]]["start"]
    new_end   = sent_by_id[resolved[-1]["end_sent_id"]]["end"]
    new_duration = sum(
        sent_by_id[s["end_sent_id"]]["end"] - sent_by_id[s["start_sent_id"]]["start"]
        for s in resolved
    )

    # Sanity: if trim didn't actually shrink, or shrank past hook/payoff loss,
    # keep original. We've already lost the trim call cost; don't also ship
    # a worse clip.
    if new_duration >= clip.get("duration", clip["end"] - clip["start"]):
        print(f"  [Trim] ⚠ Trim did not reduce duration "
              f"({new_duration:.1f}s ≥ original) — keeping clip as-is")
        return clip

    old_duration = clip.get("duration", clip["end"] - clip["start"])
    print(f"  [Trim] ✓ {old_duration:.1f}s → {new_duration:.1f}s "
          f"({len(resolved)} segment{'s' if len(resolved) > 1 else ''})")

    # Apply the trim
    clip["segments"]    = resolved
    clip["start"]       = new_start
    clip["end"]         = new_end
    clip["duration"]    = new_duration
    clip["trimmed"]     = True
    clip["trim_reason"] = result.get("trim_reason", "Trimmed by post-process pass to fit Reel length")
    return clip


def trim_long_clips(clips: list[dict], sentences: list[dict],
                    sent_by_id: dict, cache_name: Optional[str],
                    client) -> list[dict]:
    """
    Walk all clips. Fire gemini_trim_long_clip on any that exceed TRIM_TRIGGER_SEC.
    Returns the (possibly modified) clip list. Never raises.
    """
    long_clips = [c for c in clips if c.get("duration", 0) > TRIM_TRIGGER_SEC]
    if not long_clips:
        print(f"  [Trim] No clips exceed {TRIM_TRIGGER_SEC}s — nothing to trim")
        return clips

    print(f"  [Trim] {len(long_clips)} clip(s) exceed {TRIM_TRIGGER_SEC}s — trimming")
    for i, clip in enumerate(long_clips, 1):
        print(f"  [Trim] {i}/{len(long_clips)}: "
              f"{clip.get('duration', 0):.1f}s clip — '{clip.get('hook_text', '')[:60]}...'")
        gemini_trim_long_clip(clip, sentences, sent_by_id, cache_name, client)
        # Brief delay to be polite to the API
        time.sleep(2)

    return clips


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator — two-call pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def gemini_select_clips(sentences: list[dict], junk_ids: set,
                        video_duration: float, file_uri: str,
                        video_id: str, client) -> list:
    """
    Orchestrates the two-call pipeline:
    Call 1 (rough cut) → Call 2 (fine cut)
    Uses context caching to reuse video tokens across both calls.
    """
    sent_by_id = {s["id"]: s for s in sentences}

    # Try to create context cache
    print(f"  [Cache] Creating context cache (video + transcript)...")
    cache_name = create_cache(file_uri, sentences, junk_ids, client)

    try:
        # ── Call 1: Rough cut ────────────────────────────────────────
        candidates = gemini_rough_cut(
            file_uri, sentences, junk_ids,
            video_duration, cache_name, client
        )

        # Small delay between calls to avoid rate limiting
        time.sleep(3)

        # ── Call 2: Fine cut ─────────────────────────────────────────
        clips = gemini_fine_cut(
            candidates, sentences, sent_by_id, junk_ids,
            file_uri, cache_name, video_id, client
        )

        # ── Call 3 (conditional): Trim over-length clips ─────────────
        # Reuses the same cache — only fires for clips > TRIM_TRIGGER_SEC.
        if clips:
            time.sleep(2)
            print(f"\n  [Stage 3.5] Checking for over-length clips...")
            clips = trim_long_clips(clips, sentences, sent_by_id, cache_name, client)

    finally:
        # Always clean up cache
        if cache_name:
            delete_cache(cache_name, client)

    return clips


# ═══════════════════════════════════════════════════════════════════════════════
# Attach transcripts — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def attach_transcripts(clips, all_sentences, word_timestamps=None):
    sent_by_id = {s["id"]: s for s in all_sentences}
    for clip in clips:
        transcript    = []
        clip_segments = clip.get("segments", [])
        if clip_segments:
            for seg_idx, seg in enumerate(clip_segments):
                s_id = int(seg["start_sent_id"])
                e_id = int(seg["end_sent_id"])
                seg_sents = [sent_by_id[i] for i in range(s_id, e_id + 1)
                             if i in sent_by_id]
                for s in seg_sents:
                    transcript.append({
                        "start": round(s["start"], 2),
                        "end":   round(s["end"],   2),
                        "text":  s["text"],
                    })
                if seg_idx < len(clip_segments) - 1:
                    transcript.append({"start": -1, "end": -1, "text": "[CUT]"})
        else:
            clip_sents = get_sentences_in_range(
                all_sentences, clip["start"], clip["end"]
            )
            for s in clip_sents:
                transcript.append({
                    "start": round(s["start"], 2),
                    "end":   round(s["end"],   2),
                    "text":  s["text"],
                })
        clip["transcript"]      = transcript
        clip["transcript_text"] = " ".join(
            s["text"] for s in transcript if s["text"] != "[CUT]"
        )
    return clips


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def select_clips(transcript_path: str) -> dict:
    """
    Full pipeline:
    1. Load transcript
    2. Junk detection
    3. Upload video to Gemini File API
    4. Create context cache
    5. Call 1: Rough cut (find all genuine Reel moments)
    6. Call 2: Fine cut (perfect each candidate)
    7. Attach transcripts
    8. Save output JSON
    """
    pipeline_start = time.time()

    video_id   = Path(transcript_path).stem.replace("_audio_transcript", "")
    video_path = transcript_path.replace("_audio_transcript.json", ".mp4")

    if not os.path.exists(video_path):
        raise RuntimeError(f"Video file not found: {video_path}")

    data            = load_transcript(transcript_path)
    sentences       = data.get("sentences", [])
    word_timestamps = data.get("word_timestamps", [])
    video_duration  = sentences[-1]["end"] if sentences else 0.0

    print(f"✓ Video ID       : {video_id}")
    print(f"✓ Video file     : {Path(video_path).name}")
    print(f"✓ Video duration : {video_duration:.1f}s ({video_duration/60:.1f} min)")
    print(f"✓ Sentences      : {len(sentences)}")

    # Stage 1: Junk detection
    print(f"\n📦 Stage 1: Segmentation (junk detection)...")
    segments = segment_transcript(sentences)
    if not segments:
        raise RuntimeError("No segments found")

    print(f"\n🗑  Filtering junk...")
    segments = filter_junk(segments, video_duration)
    junk_ids = get_junk_sentence_ids(segments)
    print(f"  ✓ {len(junk_ids)} junk sentence IDs")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in .env")
    client = google_genai.Client(api_key=api_key)

    uri_cache_path = transcript_path.replace("_audio_transcript.json", "_file_uri.txt")
    if os.path.exists(uri_cache_path):
        with open(uri_cache_path, "r") as f:
            file_uri = f.read().strip()
        print(f"\n📤 Stage 2: Reusing cached file URI: {file_uri}")
    else:
        print(f"\n📤 Stage 2: Uploading video...")
        file_uri = upload_video_to_file_api(video_path, client)
        with open(uri_cache_path, "w") as f:
            f.write(file_uri)
        print(f"  [Upload] ✓ URI cached for future runs")

    # Stage 3 + 4: Two-call clip selection
    print(f"\n🧠 Stage 3: Two-call vision selection ({GEMINI_MODEL})...")
    clips = gemini_select_clips(sentences, junk_ids, video_duration,
                                file_uri, video_id, client)

    if not clips:
        raise RuntimeError("Pipeline returned no clips")

    clips = attach_transcripts(clips, sentences, word_timestamps)

    elapsed = time.time() - pipeline_start
    print(f"\n{'='*65}")
    print(f"SELECTED CLIPS  ({elapsed:.1f}s total)")
    print(f"{'='*65}")

    for i, clip in enumerate(clips, 1):
        seg_summary = " + ".join(
            f"s{s['start_sent_id']}-s{s['end_sent_id']}"
            for s in clip.get("segments", [])
        )
        print(f"\n🎬 Clip {i} [rank={clip['confidence_rank']}]: {clip.get('why', '')}")
        print(f"   Segments    : {seg_summary}")
        print(f"   Time        : {clip['start']:.1f}s → {clip['end']:.1f}s "
              f"(content={clip['duration']:.1f}s)")
        print(f"   Virality    : {clip.get('virality_score', '?')}/10  "
              f"[{clip.get('engagement_type', '?')}]")
        print(f"   Hook        : {clip.get('hook_text', '')[:80]}")
        print(f"   Payoff      : {clip.get('payoff_text', '')[:80]}")
        print(f"   Visual      : {clip.get('visual_note', '')}")
        if clip.get("trimmed"):
            print(f"   Trimmed     : {clip.get('trim_reason', '')}")

    output = {
        "video_id":        video_id,
        "video_duration":  video_duration,
        "total_sentences": len(sentences),
        "total_segments":  len(segments),
        "clips":           clips,
        "metadata": {
            "pipeline":         "ClipForge-v17-ThreeCallVision",
            "approach":         ("junk-detection (incl. sentence-level CTA flagging) → "
                                 "video-upload → context-cache → "
                                 "rough-cut (Call1) → fine-cut (Call2) → "
                                 "trim-long-clips (Call3, conditional) → segments-array"),
            "language":         "Telugu/Codemix",
            "gemini_model":     GEMINI_MODEL,
            "thinking_level":   "HIGH",
            "call_1":           "rough cut — find all genuine Reel moments",
            "call_2":           "fine cut — perfect hooks, payoffs, trim, score, rank",
            "call_3":           f"trim-long-clips — fires only on clips > {TRIM_TRIGGER_SEC}s",
            "trim_trigger_sec": TRIM_TRIGGER_SEC,
            "trim_target_sec":  TRIM_TARGET_SEC,
            "caching":          "context cache reuses video tokens across all calls",
            "clip_count_rule":  "quality decides count, no min/max in prompts",
            "file_uri":         file_uri,
        }
    }

    output_path = transcript_path.replace("_audio_transcript.json",
                                          "_audio_clips.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Saved: {output_path}")

    return output


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python services/clip_selector.py <transcript_json>")
        print("Example: python services/clip_selector.py "
              "storage/uploads/F94zxTfgGOs_audio_transcript.json")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"✗ File not found: {path}")
        sys.exit(1)

    try:
        result = select_clips(path)
        print(f"\n🎉 Done! {len(result['clips'])} clips ready for cutting.")
    except Exception as e:
        print(f"\n✗ Pipeline failed: {e}")
        raise