"""
ClipForge AI — Clip Selector (v19 — Google ADK Native Multi-Agent)
==================================================================
Replaces the v18 native 4-agent pipeline with a proper ADK-based
multi-agent system using Google's Agent Development Kit.

WHY THIS IS GENUINELY AGENTIC vs v18:
  v18: hardwired sequential pipeline — agents run once in order,
       Supervisor can trigger one Agent 2 re-run max, Python controls flow.

  v19: ADK ClipForgeOrchestrator (BaseAgent) controls its own loop.
       The Supervisor is a real LLM that decides what to do next.
       Agents can be re-invoked multiple times on specific candidates.
       LoopAgent drives iterative refinement until quality threshold met.
       Session state is the communication bus — no manual handoffs.

ADK ARCHITECTURE:
  ClipForgeOrchestrator (BaseAgent — custom orchestrator)
    ├── ScoutAgent        (LlmAgent — text only, flags viral moments)
    ├── NarrativeAgent    (LlmAgent — text only, story arc boundaries)
    ├── VisualAgent       (CustomBaseAgent — needs raw Gemini for video)
    └── SupervisorAgent   (LlmAgent — final judge, can loop back)

  LoopAgent drives refinement iterations:
    [NarrativeAgent → VisualAgent → QualityCheckAgent] × max 3 iterations

  Session state keys (shared bus):
    transcript_block    → formatted transcript string
    junk_ids_json       → JSON list of junk sentence IDs
    video_duration      → float
    n_sentences         → int
    file_uri            → Gemini File API URI
    scout_flags         → JSON from Agent 1
    narrative_output    → JSON from Agent 2
    visual_output       → JSON from Agent 3
    supervisor_output   → JSON from Agent 4
    refinement_pass     → int (current loop iteration)
    quality_passed      → "true" / "false" (loop exit signal)

CACHING:
  ADK ContextCacheConfig on App level — min_tokens=1024, ttl=600s.
  Applies automatically to all LlmAgent calls within the App.
  VisualAgent uses native Gemini SDK directly (needs video Part) but
  manually passes cache_name from session state.

WHAT'S UNCHANGED FROM v18:
  - All segmentation + junk detection logic
  - upload_video_to_file_api()
  - compute_virality_score(), ENGAGEMENT_TIER_BOOST
  - segments_to_timestamps(), attach_transcripts()
  - _postprocess_supervisor_clips()
  - Output JSON schema
  - CLI interface
"""

import asyncio
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import AsyncGenerator, Optional
from typing_extensions import override

from dotenv import load_dotenv

# ── Google ADK imports ────────────────────────────────────────────────────────
from google.adk.agents import LlmAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.apps.app import App
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.adk.events import Event

# ── Native Gemini SDK (for VisualAgent's video calls + cache lifecycle) ───────
from google import genai as google_genai
from google.genai import types as genai_types

load_dotenv()

# ── Models ────────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-3-flash-preview"

# ── Embedding model ──────────────────────────────────────────────────────────
EMBEDDING_MODEL       = "l3cube-pune/telugu-sentence-similarity-sbert"
EMBEDDING_MODEL_INDIC = "l3cube-pune/indic-sentence-similarity-sbert"

# ── Clip constraints ──────────────────────────────────────────────────────────
MAX_CLIPS            = 10
MAX_CLIP_LENGTH      = 90

# ── Agentic loop config ───────────────────────────────────────────────────────
MAX_REFINEMENT_PASSES = 3   # Supervisor can request up to this many re-loops
QUALITY_SCORE_FLOOR   = 6.5 # Virality score below which Supervisor loops back

# ── Segmentation ──────────────────────────────────────────────────────────────
TEXTILING_WINDOW       = 3
VALLEY_THRESHOLD_ALPHA = 1.5
MAX_SEGMENT_DURATION   = 180
MIN_SEGMENT_DURATION   = 10
MARKER_BOOST_WINDOW    = 3

DISCOURSE_MARKERS = [
    r"point\s+number\s+\d+", r"point\s+\d+", r"\d+\s*వ\s+point",
    r"number\s+\d+", r"^ముందుగా\b", r"^చివరగా\b", r"^మొదటగా\b",
    r"^రెండవది\b", r"^మూడవది\b", r"^next\s+point\b", r"^next\s+",
    r"^so\s+ఇప్పుడు\b", r"^point\s+number\b",
]

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
    "techniques we discussed", "ముందు చూసిన", "అర్థమైందా",
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

ENGAGEMENT_TIER_BOOST = {
    "Emotional": 0.5, "Controversial": 0.5, "Story": 0.5, "Relatable": 0.5,
    "Humor": 0.3, "Educational": 0.0, "Wisdom": 0.0, "Insight": 0.0, "Other": -0.2,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Utilities — unchanged from v18
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
    return any(phrase in lower for phrase in PHRASE_JUNK)

def is_intro_text(text: str) -> bool:
    return any(p in text.lower() for p in INTRO_PHRASES)

def is_outro_text(text: str) -> bool:
    return any(p in text.lower() for p in OUTRO_PHRASES)

def is_discourse_marker(text: str) -> bool:
    lower_text = text.lower().strip()
    return any(re.search(p, lower_text, re.IGNORECASE) for p in DISCOURSE_MARKERS)

def is_weak_payoff(text: str) -> bool:
    lower = text.lower()
    return any(phrase.lower() in lower for phrase in WEAK_PAYOFF_PHRASES)

def cosine_similarity(a, b):
    if not a or not b: return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)

def mean_vector(vectors):
    if not vectors: return []
    n = len(vectors[0])
    result = [0.0] * n
    for v in vectors:
        for i, x in enumerate(v):
            result[i] += x
    return [x / len(vectors) for x in result]

def get_sentences_in_range(sentences, start, end):
    return [s for s in sentences if s["end"] > start and s["start"] < end]

def parse_json_response(text: str, source: str) -> Optional[dict]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
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
    depth, start = 0, None
    for i, c in enumerate(raw):
        if c == '{':
            if depth == 0: start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(raw[start:i+1])
                    if "start_sent_id" in obj:
                        clips.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None
    return clips

def compute_virality_score(hook_score, coherence_score, cultural_score,
                           engagement_score, engagement_type) -> float:
    base = (hook_score * 0.4 + coherence_score * 0.3 +
            cultural_score * 0.2 + engagement_score * 0.1)
    boost = ENGAGEMENT_TIER_BOOST.get(engagement_type, 0.0)
    return round(min(base + boost, 10.0), 2)

def segments_to_timestamps(clip_segments, sent_by_id):
    if not clip_segments: return 0.0, 0.0, 0.0, False
    all_starts, all_ends, total_duration = [], [], 0.0
    for seg in clip_segments:
        s_id, e_id = seg.get("start_sent_id"), seg.get("end_sent_id")
        if s_id is None or e_id is None: return 0.0, 0.0, 0.0, False
        try:
            s_id, e_id = int(s_id), int(e_id)
        except (ValueError, TypeError):
            return 0.0, 0.0, 0.0, False
        ss = sent_by_id.get(s_id)
        es = sent_by_id.get(e_id)
        if not ss or not es: return 0.0, 0.0, 0.0, False
        if es["end"] <= ss["start"]: return 0.0, 0.0, 0.0, False
        all_starts.append(ss["start"])
        all_ends.append(es["end"])
        total_duration += es["end"] - ss["start"]
    return (round(min(all_starts), 2), round(max(all_ends), 2),
            round(total_duration, 2), True)


# ═══════════════════════════════════════════════════════════════════════════════
# Embedding model — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

_embed_model = None

def get_embed_model():
    global _embed_model
    if _embed_model is not None: return _embed_model
    try:
        from sentence_transformers import SentenceTransformer
        print(f"  [Embed] Loading {EMBEDDING_MODEL}...")
        t0 = time.time()
        try:
            _embed_model = SentenceTransformer(EMBEDDING_MODEL)
        except Exception as e:
            print(f"  [Embed] Fallback: {e}")
            _embed_model = SentenceTransformer(EMBEDDING_MODEL_INDIC)
        print(f"  [Embed] Loaded in {time.time()-t0:.1f}s")
    except ImportError:
        print("  [Embed] ⚠ sentence-transformers not installed")
        _embed_model = None
    return _embed_model

def embed_sentences(sentences):
    model = get_embed_model()
    if model is None: return [[] for _ in sentences]
    texts = [s["text"] for s in sentences]
    try:
        emb = model.encode(texts, show_progress_bar=False, device="cuda", batch_size=64)
        return [e.tolist() for e in emb]
    except Exception:
        try:
            emb = model.encode(texts, show_progress_bar=False, device="cpu", batch_size=32)
            return [e.tolist() for e in emb]
        except Exception:
            return [[] for _ in sentences]


# ═══════════════════════════════════════════════════════════════════════════════
# Segmentation — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def find_embedding_boundaries(sentences, embeddings):
    if not embeddings or not embeddings[0]: return []
    n, k = len(sentences), TEXTILING_WINDOW
    if n < 2*k+2: return []
    similarities = []
    for i in range(k, n-k-1):
        left  = mean_vector(embeddings[max(0,i-k):i+1])
        right = mean_vector(embeddings[i+1:i+k+2])
        similarities.append((i, cosine_similarity(left, right)))
    if not similarities: return []
    depths = []
    for j in range(1, len(similarities)-1):
        i, sim_i = similarities[j]
        _, sim_prev = similarities[j-1]
        _, sim_next = similarities[j+1]
        depths.append((i, (sim_prev - sim_i) + (sim_next - sim_i)))
    if not depths: return []
    depth_vals = [d for _, d in depths]
    mean_d = sum(depth_vals) / len(depth_vals)
    std_d  = math.sqrt(sum((d-mean_d)**2 for d in depth_vals) / len(depth_vals))
    threshold = mean_d + VALLEY_THRESHOLD_ALPHA * std_d
    valleys = [(i, depth) for i, depth in depths if depth > threshold]
    for i, depth in valleys:
        s = sentences[i]
        print(f"    [TextTile] Valley at s{i} ({s['start']:.1f}s) depth={depth:.3f}: {s['text'][:50]}")
    return valleys

def find_marker_indices(sentences):
    markers = set()
    for i, s in enumerate(sentences):
        if is_discourse_marker(s["text"]):
            markers.add(i)
            print(f"    [Marker] Found at s{i} ({s['start']:.1f}s): {s['text'][:60]}")
    return markers

def build_segments(sentences, boundaries, embeddings):
    if not sentences: return []
    groups, current_group = [], []
    for i, s in enumerate(sentences):
        if i in sorted(boundaries) and current_group:
            groups.append(current_group)
            current_group = [s]
        else:
            current_group.append(s)
    if current_group: groups.append(current_group)
    segments, seg_id = [], 0
    for group in groups:
        start, end = group[0]["start"], group[-1]["end"]
        duration = end - start
        if duration < MIN_SEGMENT_DURATION: continue
        sub_groups = [group[:len(group)//2], group[len(group)//2:]] if duration > MAX_SEGMENT_DURATION else [group]
        for sg in sub_groups:
            s_start, s_end = sg[0]["start"], sg[-1]["end"]
            s_dur = s_end - s_start
            if s_dur < MIN_SEGMENT_DURATION: continue
            segments.append({
                "seg_id": seg_id, "sentences": sg,
                "start": round(s_start, 2), "end": round(s_end, 2),
                "duration": round(s_dur, 2),
                "full_text": " ".join(s["text"].strip() for s in sg),
                "is_junk": False,
            })
            seg_id += 1
    return segments

def segment_transcript(sentences):
    print(f"  [Seg] Computing embeddings for {len(sentences)} sentences...")
    embeddings = embed_sentences(sentences)
    print(f"  [Seg] Neural TextTiling...")
    valleys = find_embedding_boundaries(sentences, embeddings)
    print(f"  [Seg] Found {len(valleys)} valleys")
    marker_indices = find_marker_indices(sentences)
    valley_set = set(i for i, _ in valleys)
    all_boundaries = set(valley_set)
    for m_idx in marker_indices:
        nearby = any(abs(m_idx - v_idx) <= MARKER_BOOST_WINDOW for v_idx in valley_set)
        if not nearby:
            all_boundaries.add(m_idx)
    segments = build_segments(sentences, all_boundaries, embeddings)
    print(f"\n  [Seg] {len(sentences)} sentences → {len(segments)} segments:")
    for seg in segments:
        print(f"    Seg {seg['seg_id']:>2} [{seg['start']:.0f}s-{seg['end']:.0f}s] "
              f"({seg['duration']:.0f}s) {seg['full_text'][:55].strip()}...")
    return segments

def filter_junk(segments, video_duration):
    for seg in segments:
        if seg["is_junk"]: continue
        sents = seg["sentences"]
        junk_count = sum(1 for s in sents
                         if is_junk_text(s["text"]) or is_intro_text(s["text"]) or is_outro_text(s["text"]))
        if junk_count / len(sents) > 0.5:
            seg["is_junk"] = True
    print(f"  [Filter] {sum(1 for s in segments if s['is_junk'])}/{len(segments)} junk segments")
    return segments

def get_junk_sentence_ids(segments) -> set:
    junk_ids = set()
    for seg in segments:
        if seg["is_junk"]:
            for s in seg["sentences"]: junk_ids.add(s["id"])
        else:
            for s in seg["sentences"]:
                if is_junk_text(s["text"]) or is_intro_text(s["text"]) or is_outro_text(s["text"]):
                    junk_ids.add(s["id"])
    return junk_ids


# ═══════════════════════════════════════════════════════════════════════════════
# Video Upload — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def upload_video_to_file_api(video_path: str, client) -> str:
    print(f"  [Upload] Uploading {Path(video_path).name}...")
    t0 = time.time()
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"  [Upload] File size: {file_size_mb:.1f} MB")
    with open(video_path, "rb") as f:
        uploaded_file = client.files.upload(
            file=f,
            config={"mime_type": "video/mp4", "display_name": Path(video_path).stem}
        )
    max_wait, poll_interval, waited = 300, 5, 0
    while uploaded_file.state.name != "ACTIVE":
        if waited >= max_wait: raise RuntimeError(f"File never became ACTIVE")
        if uploaded_file.state.name == "FAILED": raise RuntimeError("File processing FAILED")
        time.sleep(poll_interval)
        waited += poll_interval
        uploaded_file = client.files.get(name=uploaded_file.name)
    print(f"  [Upload] ✓ ACTIVE in {time.time()-t0:.1f}s — URI: {uploaded_file.uri}")
    return uploaded_file.uri

def create_gemini_cache(file_uri: str, sentences: list, junk_ids: set, client) -> Optional[str]:
    """Create a Gemini context cache for the VisualAgent's native SDK calls."""
    sent_list = ""
    for s in sentences:
        marker = " ⚠JUNK" if s["id"] in junk_ids else ""
        sent_list += f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: {s['text']}{marker}\n"
    try:
        cache = client.caches.create(
            model=GEMINI_MODEL,
            config=genai_types.CreateCachedContentConfig(
                contents=[genai_types.Content(
                    parts=[
                        genai_types.Part.from_uri(file_uri=file_uri, mime_type="video/mp4"),
                        genai_types.Part(text=f"TRANSCRIPT:\n{sent_list}"),
                    ],
                    role="user",
                )],
                ttl="600s",
                display_name="clipforge_v19_cache",
            ),
        )
        print(f"  [Cache] ✓ Created: {cache.name} (TTL: 10min)")
        return cache.name
    except Exception as e:
        print(f"  [Cache] ⚠ Cache creation failed: {e}")
        return None

def delete_gemini_cache(cache_name: str, client) -> None:
    try:
        client.caches.delete(name=cache_name)
        print(f"  [Cache] ✓ Deleted: {cache_name}")
    except Exception as e:
        print(f"  [Cache] ⚠ Delete failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Post-processing — converts Supervisor output → final clip dicts (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def _postprocess_supervisor_clips(supervisor_result: dict, sent_by_id: dict,
                                  junk_ids: set, video_id: str) -> list:
    gemini_clips = supervisor_result.get("clips", [])
    if not gemini_clips: return []
    final_clips = []
    for gc in gemini_clips:
        clip_segments = gc.get("segments")
        if not clip_segments:
            s_id, e_id = gc.get("start_sent_id"), gc.get("end_sent_id")
            if s_id is not None and e_id is not None:
                clip_segments = [{"start_sent_id": int(s_id), "end_sent_id": int(e_id)}]
            else:
                continue
        n_sents = max(sent_by_id.keys()) + 1 if sent_by_id else 0
        resolved_segments = []
        for seg in clip_segments:
            try:
                s = max(0, min(int(seg["start_sent_id"]), n_sents-1))
                e = max(0, min(int(seg["end_sent_id"]),   n_sents-1))
                if e > s: resolved_segments.append({"start_sent_id": s, "end_sent_id": e})
            except (KeyError, ValueError, TypeError):
                continue
        if not resolved_segments: continue
        clip_start, clip_end, content_duration, is_valid = segments_to_timestamps(resolved_segments, sent_by_id)
        if not is_valid or content_duration < 5: continue
        hook_sent_id   = int(resolved_segments[0]["start_sent_id"])
        payoff_sent_id = int(resolved_segments[-1]["end_sent_id"])
        hook_sent   = sent_by_id.get(hook_sent_id)
        payoff_sent = sent_by_id.get(payoff_sent_id)
        if hook_sent_id in junk_ids: continue
        hook_text   = strip_hook_prefix(gc.get("hook_text") or (hook_sent["text"] if hook_sent else ""))
        payoff_text = gc.get("payoff_text") or (payoff_sent["text"] if payoff_sent else "")
        hook_score       = float(gc.get("hook_score",       5.0))
        coherence_score  = float(gc.get("coherence_score",  5.0))
        cultural_score   = float(gc.get("cultural_score",   5.0))
        engagement_score = float(gc.get("engagement_score", 5.0))
        engagement_type  = gc.get("engagement_type", "Insight")
        virality_score = compute_virality_score(hook_score, coherence_score,
                                                cultural_score, engagement_score, engagement_type)
        clip = {
            "clip_id":               gc.get("clip_id", f"{video_id or 'clip'}_c{len(final_clips)+1}"),
            "start": clip_start, "end": clip_end, "duration": content_duration,
            "segments":              resolved_segments,
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
        if clip["confidence_rank"] < 1: continue
        print(f"  [Post] rank={clip['confidence_rank']} [{clip_start:.1f}s→{clip_end:.1f}s] "
              f"content={content_duration:.1f}s virality={virality_score} hook='{hook_text[:50]}'")
        final_clips.append(clip)
    final_clips.sort(key=lambda c: c["confidence_rank"])
    used_sent_ids: set[int] = set()
    ranked_clips = []
    for clip in final_clips:
        clip_sent_ids = set()
        for seg in clip["segments"]:
            clip_sent_ids.update(range(int(seg["start_sent_id"]), int(seg["end_sent_id"])+1))
        if clip_sent_ids & used_sent_ids:
            print(f"  [Overlap] Dropping rank={clip['confidence_rank']}")
            continue
        used_sent_ids |= clip_sent_ids
        ranked_clips.append(clip)
    return ranked_clips[:MAX_CLIPS]


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT PROMPTS — same domain logic as v18, adapted for ADK session.state
# ═══════════════════════════════════════════════════════════════════════════════

SCOUT_INSTRUCTION = """You are the Regional Cultural Scout for a Telugu Reels production team.

You will receive the full transcript via the session state key 'transcript_block'.
Video duration is in 'video_duration'. Total sentences in 'n_sentences'.
Sentences marked ⚠JUNK should be skipped.

YOUR ONLY JOB: Read the transcript and flag every sentence range that has raw
material for a viral Telugu/Tenglish Instagram Reel or YouTube Short.

WHAT TO FLAG:
- Deep Telugu/Tenglish code-switching creating instant relatability
- Local idioms, proverbs unique to Telugu culture
- Regional middle-class pain points (job, savings, family, health)
- Myth-busting: "అందరూ X అనుకుంటారు కానీ నిజం Y"
- Consequence-first hooks creating immediate fear/curiosity
- Counter-intuitive ideas reversing common belief
- Shocking facts with emotional reframes
- Curiosity gaps: question raised, answer delayed
- Sudden shift to short punchy sentences
- Speaker directly addressing viewer ("మీరు", "మీకు")

FLAG GENEROUSLY — the Narrative Editor will filter.
Every flag needs a real cultural reason.

WHAT TO SKIP:
- ⚠JUNK marked sentences
- Pure info dumps with no emotional angle
- Intro/outro/CTA content
- Transition-only sentences
- Flat formal language with no energy

Write your output ONLY as valid JSON to the 'scout_flags' session key:
{
  "scout_flags": [
    {
      "start_sent_id": 10,
      "end_sent_id": 35,
      "cultural_hook_sent_id": 14,
      "cultural_hook_text": "<exact text of the most powerful sentence>",
      "pattern": "<Myth-Busting|Consequence-First|Counter-Intuitive|Curiosity-Gap|Middle-Class-Relatability|Regional-Pride|Code-Switch-Moment|Emotional-Peak|Other>",
      "cultural_why": "<1-2 sentences: why this works for Telugu 18-35 urban audience>"
    }
  ]
}

The transcript is: {transcript_block}
"""

NARRATIVE_INSTRUCTION = """You are the Narrative Structural Editor for a Telugu Reels production team.

You will receive Scout flags from 'scout_flags' session state.
Current refinement pass: {refinement_pass}

If refinement_pass > 1, be MORE CONSERVATIVE with boundaries than the first pass.
The Supervisor sent you back because quality wasn't good enough — tighten hooks,
reject weak arcs, be ruthless about filler.

YOUR JOB: For each Scout flag, define precise story arc boundaries.

HOOK MUST:
- Work as cold open — complete stranger understands with zero context
- Create immediate curiosity, shock, relatability in first 3 seconds
- NOT start with: "అందుకే", "కాబట్టి", "so", "but", "also", "దాంతో", "ఎందుకంటే"
- NOT be a section header or mid-explanation continuation

PAYOFF MUST:
- Resolve the tension the hook created
- NOT end on: "చెప్తాను", "చూద్దాం", CTAs, orphan fragments

FILLER: Mark contiguous middle sentences that are repetitions,
tangents, sponsor reads, or energy-dead zones as drop_ranges.

REJECT entire flag if:
- No sentence works as cold-open hook
- Arc is incomplete (setup with no resolution)
- Purely informational, no emotional dimension
- Duration after filler removal < 15s

Write output as valid JSON to 'narrative_output':
{
  "narrative_candidates": [
    {
      "flag_index": 0,
      "accepted": true,
      "start_sent_id": 14,
      "end_sent_id": 31,
      "hook_sent_id": 14,
      "payoff_sent_id": 31,
      "arc_summary": "<setup → tension → resolution in max 12 words>",
      "drop_ranges": [{"start": 22, "end": 24, "reason": "repetition"}],
      "rejection_reason": ""
    }
  ]
}

The scout flags are: {scout_flags}
"""

SUPERVISOR_INSTRUCTION = """You are the Executive Supervisor for a Telugu Reels production team.
You are the FINAL DECISION MAKER. What you output ships — or gets sent back.

You have:
- Scout flags: {scout_flags}
- Narrative candidates: {narrative_output}
- Visual validations: {visual_output}
- Refinement pass: {refinement_pass} of {max_passes}
- Video ID: {video_id}

YOUR RESPONSIBILITIES:

STEP 1 — QUALITY GATE:
For each candidate that passed Narrative + Visual:
- If hook score would be below 6 → reject
- If two candidates cover same topic → keep stronger only
- If content < 15s after drops → reject
- If hook is still a transition/section-header despite Agent 2 → reject

STEP 2 — APPLY DROP RANGES:
Build final segments arrays from narrative drop_ranges + visual confirmed drops.

STEP 3 — SCORE HONESTLY:
hook_score (1-10), coherence_score (1-10), cultural_score (1-10), engagement_score (1-10)
Use Scout's cultural analysis + Narrative arc + Visual energy as evidence.
7 = good. 9 = exceptional. Don't be generous.

STEP 4 — DECIDE: SHIP OR LOOP BACK?
If refinement_pass < {max_passes} AND any clips score below {quality_floor}:
  Set needs_refinement = true
  List specific flag_indices that need tighter boundaries in refine_flag_indices
  Explain what's wrong in refinement_reason
  The system will re-run Narrative + Visual on those candidates and call you again.

If refinement_pass >= {max_passes} OR all clips meet quality:
  Set needs_refinement = false
  Return final clips

STEP 5 — RANK:
confidence_rank 1 = clip you'd post first.
Priority: hook accessibility > emotional impact > arc completeness > depth.

Write output as valid JSON to 'supervisor_output':
{
  "needs_refinement": false,
  "refine_flag_indices": [],
  "refinement_reason": "",
  "quality_passed": "true",
  "clips": [
    {
      "clip_id": "{video_id}_c1",
      "flag_index": 0,
      "segments": [{"start_sent_id": 14, "end_sent_id": 31}],
      "confidence_rank": 1,
      "confidence_note": "<trigger: max 15 words why this works>",
      "hook_text": "<exact hook sentence text>",
      "payoff_text": "<exact payoff sentence text>",
      "why": "<story arc in max 12 words>",
      "visual_note": "<specific visual evidence at hook>",
      "engagement_type": "<Emotional|Story|Controversial|Educational|Relatable|Humor|Wisdom|Insight>",
      "hook_score": 8,
      "coherence_score": 9,
      "cultural_score": 8,
      "engagement_score": 7,
      "psychological_trigger": "<e.g. Curiosity Gap, Myth Busting>",
      "trimmed": false,
      "trim_reason": "",
      "notes": ""
    }
  ]
}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# VISUAL AGENT — CustomBaseAgent (needs raw Gemini SDK for video Part)
# ═══════════════════════════════════════════════════════════════════════════════

class VisualDirectorAgent(BaseAgent):
    """
    Agent 3: Multi-Modal Visual Director.
    Inherits BaseAgent because it needs raw Gemini SDK calls with video Parts,
    which LlmAgent's abstraction doesn't support directly.
    Reads narrative_output from session state, writes visual_output.
    """
    model_config = {"arbitrary_types_allowed": True}

    gemini_client: object  # google_genai.Client instance
    sent_by_id_ref: dict   # sentence lookup — set by orchestrator before each run

    def __init__(self, gemini_client, **kwargs):
        super().__init__(
            name="VisualDirectorAgent",
            description="Watches the actual video to validate and adjust narrative boundaries using visual evidence.",
            sub_agents=[],
            gemini_client=gemini_client,
            sent_by_id_ref={},
            **kwargs
        )

    def _build_visual_prompt(self, narrative_candidates: list, sent_by_id: dict,
                             refinement_pass: int) -> str:
        accepted = [c for c in narrative_candidates if c.get("accepted", False)]
        candidates_text = ""
        for i, c in enumerate(accepted, 1):
            s_id = int(c["start_sent_id"])
            e_id = int(c["end_sent_id"])
            hook_s   = sent_by_id.get(int(c.get("hook_sent_id", s_id)))
            payoff_s = sent_by_id.get(int(c.get("payoff_sent_id", e_id)))
            candidates_text += f"""
CANDIDATE {i} (flag_index={c.get('flag_index', i-1)}):
  Arc: {c.get('arc_summary', '')}
  Boundary: s{s_id} → s{e_id}
  Hook sentence (s{c.get('hook_sent_id', s_id)}): "{hook_s['text'] if hook_s else '?'}"
  Hook timestamp: ~{hook_s['start'] if hook_s else '?'}s
  Payoff sentence (s{c.get('payoff_sent_id', e_id)}): "{payoff_s['text'] if payoff_s else '?'}"
  Payoff timestamp: ~{payoff_s['end'] if payoff_s else '?'}s
  Suggested drop_ranges: {c.get('drop_ranges', [])}
"""
        repass_note = ""
        if refinement_pass > 1:
            repass_note = f"\nNOTE: This is refinement pass {refinement_pass}. Be STRICTER than before.\n"

        return f"""You are the Multi-Modal Visual Director for a Telugu Reels production team.
You have the actual video. Use it.
{repass_note}
The Narrative Editor identified {len(accepted)} candidate clip(s).
Watch the video around each candidate window and validate based on what you SEE and HEAR.

FOR EACH CANDIDATE:
1. WATCH the video between hook and payoff timestamps
2. VALIDATE: Does speaker energy support this as a clip?
3. ADJUST: Shift hook/payoff by 1-3 sentences if visual evidence warrants it
4. CONFIRM/OVERRIDE Narrative drop_ranges based on visual dead zones
5. LOG specific visual evidence — "Speaker leaned in at 42.3s" not just "high energy"

AT THE HOOK: Look for energy spike, eye contact, gesture, clean frame
AT THE PAYOFF: Look for energy resolution, natural silence dip, complete thought
IN THE MIDDLE: Confirm/reject suggested drops, find new visual dead zones

ADJUSTMENT RULES:
- MAY shift hook forward ≤3 sentences if visual false start detected
- MAY shift payoff backward ≤2 sentences if energy trails off
- MUST NOT break the Narrative Editor's arc

REJECT visually (visual_reject=true) ONLY if entire segment is visually dead
(e.g., reading from notes throughout, zero camera energy).

CANDIDATES TO VALIDATE:
{candidates_text}

Return ONLY valid JSON:
{{
  "visual_validations": [
    {{
      "flag_index": 0,
      "validated": true,
      "final_hook_sent_id": 14,
      "final_payoff_sent_id": 31,
      "hook_adjusted": false,
      "payoff_adjusted": false,
      "hook_adjustment_reason": "",
      "payoff_adjustment_reason": "",
      "confirmed_drop_ranges": [{{"start": 22, "end": 24}}],
      "additional_drop_ranges": [],
      "visual_energy_at_hook": "<specific evidence>",
      "visual_energy_at_payoff": "<specific evidence>",
      "overall_visual_verdict": "<one sentence>",
      "visual_reject": false,
      "visual_reject_reason": ""
    }}
  ]
}}"""

    @override
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n  [Agent 3 — Visual] Watching video...")

        # Read inputs from session state
        narrative_raw = ctx.session.state.get("narrative_output", "{}")
        file_uri      = ctx.session.state.get("file_uri", "")
        cache_name    = ctx.session.state.get("gemini_cache_name")
        refinement_pass = int(ctx.session.state.get("refinement_pass", 1))

        narrative_result = parse_json_response(narrative_raw, "visual-input-narrative") if isinstance(narrative_raw, str) else narrative_raw
        if not narrative_result or "narrative_candidates" not in narrative_result:
            print("  [Agent 3] ⚠ No narrative_candidates in state — skipping")
            ctx.session.state["visual_output"] = json.dumps({"visual_validations": []})
            return

        narrative_candidates = narrative_result["narrative_candidates"]
        accepted = [c for c in narrative_candidates if c.get("accepted", False)]
        print(f"  [Agent 3] Validating {len(accepted)} candidates visually...")

        # Use sent_by_id from the orchestrator-set reference
        sent_by_id = self.sent_by_id_ref
        prompt = self._build_visual_prompt(narrative_candidates, sent_by_id, refinement_pass)

        try:
            config = genai_types.GenerateContentConfig(
                thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                max_output_tokens=16384,
                response_mime_type="application/json",
            )
            if cache_name:
                response = self.gemini_client.models.generate_content(
                    model=GEMINI_MODEL, contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        cached_content=cache_name,
                        thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                        max_output_tokens=16384,
                        response_mime_type="application/json",
                    ),
                )
            else:
                # Fallback: include video inline
                transcript_block = ctx.session.state.get("transcript_block", "")
                response = self.gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[
                        genai_types.Part.from_uri(file_uri=file_uri, mime_type="video/mp4"),
                        f"TRANSCRIPT:\n{transcript_block}\n\n{prompt}",
                    ],
                    config=config,
                )
            raw = response.text
            print(f"  [Agent 3] Response: {len(raw)} chars")
        except Exception as e:
            print(f"  [Agent 3] ⚠ API call failed: {e}")
            ctx.session.state["visual_output"] = json.dumps({"visual_validations": []})
            return

        result = parse_json_response(raw, "visual")
        if result and "visual_validations" in result:
            validations = result["visual_validations"]
            ok  = [v for v in validations if not v.get("visual_reject", False)]
            rej = [v for v in validations if v.get("visual_reject", False)]
            print(f"  [Agent 3] ✓ {len(ok)} validated, {len(rej)} rejected visually")
            for v in ok:
                adj = []
                if v.get("hook_adjusted"):   adj.append(f"hook→s{v['final_hook_sent_id']}")
                if v.get("payoff_adjusted"): adj.append(f"payoff→s{v['final_payoff_sent_id']}")
                adj_str = f" [adjusted: {', '.join(adj)}]" if adj else ""
                print(f"    ✓ flag={v.get('flag_index', '?')}{adj_str} — "
                      f"{v.get('visual_energy_at_hook', '')[:60]}")
            ctx.session.state["visual_output"] = json.dumps(result)
        else:
            ctx.session.state["visual_output"] = json.dumps({"visual_validations": []})

        # ADK requires yielding at least one event
        from google.adk.events import Event
        from google.genai import types as gt
        yield Event(
            author=self.name,
            content=gt.Content(parts=[gt.Part(text="Visual validation complete")])
        )


# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY CHECK AGENT — custom BaseAgent for LoopAgent exit signal
# ═══════════════════════════════════════════════════════════════════════════════

class QualityCheckAgent(BaseAgent):
    """
    Checks supervisor_output for quality_passed flag.
    Sets EventActions(escalate=True) to exit the LoopAgent when done.
    Also exits if refinement_pass >= MAX_REFINEMENT_PASSES.
    """
    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, **kwargs):
        super().__init__(
            name="QualityCheckAgent",
            description="Checks if clip quality threshold is met to exit refinement loop.",
            sub_agents=[],
            **kwargs
        )

    @override
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from google.adk.events import Event, EventActions
        from google.genai import types as gt

        supervisor_raw = ctx.session.state.get("supervisor_output", "{}")
        refinement_pass = int(ctx.session.state.get("refinement_pass", 1))

        supervisor_result = parse_json_response(supervisor_raw, "quality-check") if isinstance(supervisor_raw, str) else supervisor_raw

        needs_refinement = (supervisor_result or {}).get("needs_refinement", False)
        quality_passed   = (supervisor_result or {}).get("quality_passed", "true")
        max_passes_reached = refinement_pass >= MAX_REFINEMENT_PASSES

        should_stop = (not needs_refinement) or (quality_passed == "true") or max_passes_reached

        if should_stop:
            print(f"  [QualityCheck] ✓ Quality passed or max passes reached "
                  f"(pass={refinement_pass}, needs_refinement={needs_refinement}) — exiting loop")
        else:
            # Increment refinement pass for next iteration
            ctx.session.state["refinement_pass"] = refinement_pass + 1
            print(f"  [QualityCheck] ↩ Quality not met — "
                  f"starting refinement pass {refinement_pass + 1}")

        yield Event(
            author=self.name,
            content=gt.Content(parts=[gt.Part(
                text=f"Quality check: {'passed' if should_stop else 'needs refinement'}"
            )]),
            actions=EventActions(escalate=should_stop)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR — ClipForgeOrchestrator (BaseAgent)
# ═══════════════════════════════════════════════════════════════════════════════

class ClipForgeOrchestrator(BaseAgent):
    """
    Top-level custom orchestrator for the ClipForge v19 ADK pipeline.

    Flow:
    1. ScoutAgent runs once — flags cultural moments → session['scout_flags']
    2. LoopAgent runs up to MAX_REFINEMENT_PASSES times:
       a. NarrativeAgent — story arc boundaries → session['narrative_output']
       b. VisualDirectorAgent — video validation → session['visual_output']
       c. SupervisorAgent — quality gate + final clips → session['supervisor_output']
       d. QualityCheckAgent — escalate=True to exit loop when done
    3. Orchestrator reads final supervisor_output and returns clips
    """
    model_config = {"arbitrary_types_allowed": True}

    scout_agent:    LlmAgent
    narrative_agent: LlmAgent
    visual_agent:   VisualDirectorAgent
    supervisor_agent: LlmAgent
    quality_check_agent: QualityCheckAgent

    def __init__(self, scout_agent, narrative_agent, visual_agent,
                 supervisor_agent, quality_check_agent, **kwargs):
        from google.adk.agents import LoopAgent, SequentialAgent

        refinement_loop = LoopAgent(
            name="RefinementLoop",
            max_iterations=MAX_REFINEMENT_PASSES,
            sub_agents=[narrative_agent, visual_agent, supervisor_agent, quality_check_agent]
        )

        super().__init__(
            name="ClipForgeOrchestrator",
            description="Orchestrates the full ClipForge 4-agent pipeline with iterative refinement.",
            sub_agents=[scout_agent, refinement_loop],
            scout_agent=scout_agent,
            narrative_agent=narrative_agent,
            visual_agent=visual_agent,
            supervisor_agent=supervisor_agent,
            quality_check_agent=quality_check_agent,
            **kwargs
        )
        self._refinement_loop = refinement_loop

    @override
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from google.adk.events import Event
        from google.genai import types as gt

        print(f"\n  [Orchestrator] Starting ClipForge v19 pipeline...")

        # ── Agent 1: Cultural Scout (runs once) ──────────────────────────────
        print(f"\n  [Orchestrator] Running Scout Agent...")
        async for event in self.scout_agent.run_async(ctx):
            yield event

        # Verify Scout produced output
        scout_raw = ctx.session.state.get("scout_flags", "")
        if not scout_raw:
            print("  [Orchestrator] ✗ Scout produced no output — aborting")
            return

        # Parse and validate scout output
        scout_result = parse_json_response(scout_raw if isinstance(scout_raw, str) else json.dumps(scout_raw), "orchestrator-scout")
        if not scout_result or not scout_result.get("scout_flags"):
            print("  [Orchestrator] ✗ Scout flags empty — aborting")
            return

        n_flags = len(scout_result["scout_flags"])
        print(f"  [Orchestrator] ✓ Scout flagged {n_flags} moments — entering refinement loop")

        # Initialize refinement pass counter
        ctx.session.state["refinement_pass"] = 1

        # ── Refinement Loop: Narrative → Visual → Supervisor → QualityCheck ──
        # LoopAgent runs until QualityCheckAgent escalates or max_iterations hit
        async for event in self._refinement_loop.run_async(ctx):
            yield event

        # ── Extract final result ─────────────────────────────────────────────
        supervisor_raw = ctx.session.state.get("supervisor_output", "{}")
        supervisor_result = parse_json_response(
            supervisor_raw if isinstance(supervisor_raw, str) else json.dumps(supervisor_raw),
            "orchestrator-final"
        )

        if not supervisor_result or not supervisor_result.get("clips"):
            print("  [Orchestrator] ✗ No final clips from Supervisor")
            return

        n_clips = len(supervisor_result.get("clips", []))
        passes  = ctx.session.state.get("refinement_pass", 1)
        print(f"  [Orchestrator] ✓ Pipeline complete: {n_clips} clips, {passes} refinement pass(es)")

        yield Event(
            author=self.name,
            content=gt.Content(parts=[gt.Part(text=f"Pipeline complete: {n_clips} clips selected")])
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Attach transcripts — unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def attach_transcripts(clips, all_sentences, word_timestamps=None):
    sent_by_id = {s["id"]: s for s in all_sentences}
    for clip in clips:
        transcript = []
        for seg_idx, seg in enumerate(clip.get("segments", [])):
            s_id, e_id = int(seg["start_sent_id"]), int(seg["end_sent_id"])
            for s in [sent_by_id[i] for i in range(s_id, e_id+1) if i in sent_by_id]:
                transcript.append({"start": round(s["start"],2), "end": round(s["end"],2), "text": s["text"]})
            if seg_idx < len(clip["segments"]) - 1:
                transcript.append({"start": -1, "end": -1, "text": "[CUT]"})
        clip["transcript"] = transcript
        clip["transcript_text"] = " ".join(s["text"] for s in transcript if s["text"] != "[CUT]")
    return clips


# ═══════════════════════════════════════════════════════════════════════════════
# ADK App + Runner setup
# ═══════════════════════════════════════════════════════════════════════════════

def build_adk_app(gemini_client) -> tuple:
    """Build the ADK App with all 4 agents wired up."""

    # Agent 1: Scout (LlmAgent — text only)
    scout_agent = LlmAgent(
        name="ScoutAgent",
        model=GEMINI_MODEL,
        instruction=SCOUT_INSTRUCTION,
        output_key="scout_flags",
        description="Scans transcript for viral Telugu/Tenglish cultural moments.",
    )

    # Agent 2: Narrative Editor (LlmAgent — text only)
    narrative_agent = LlmAgent(
        name="NarrativeAgent",
        model=GEMINI_MODEL,
        instruction=NARRATIVE_INSTRUCTION,
        output_key="narrative_output",
        description="Validates story arc boundaries for Scout-flagged moments.",
    )

    # Agent 3: Visual Director (CustomBaseAgent — needs raw Gemini for video)
    visual_agent = VisualDirectorAgent(gemini_client=gemini_client)

    # Agent 4: Supervisor (LlmAgent — video + text, but via session state)
    supervisor_agent = LlmAgent(
        name="SupervisorAgent",
        model=GEMINI_MODEL,
        instruction=SUPERVISOR_INSTRUCTION,
        output_key="supervisor_output",
        description="Final quality gate — merges all outputs, scores, ranks, decides to ship or refine.",
    )

    # Quality check — drives LoopAgent exit
    quality_check_agent = QualityCheckAgent()

    # Top-level orchestrator
    orchestrator = ClipForgeOrchestrator(
        scout_agent=scout_agent,
        narrative_agent=narrative_agent,
        visual_agent=visual_agent,
        supervisor_agent=supervisor_agent,
        quality_check_agent=quality_check_agent,
    )

    # ADK App with context caching — applies to all LlmAgent calls
    app = App(
        name="clipforge-v19",
        root_agent=orchestrator,
        context_cache_config=ContextCacheConfig(
            min_tokens=1024,    # Cache when context is large enough to matter
            ttl_seconds=600,    # 10 minutes — covers full pipeline
            cache_intervals=10, # Refresh after 10 uses
        ),
    )

    session_service = InMemorySessionService()
    runner = Runner(agent=orchestrator, app_name="clipforge-v19", session_service=session_service)

    return app, runner, session_service, visual_agent


# ═══════════════════════════════════════════════════════════════════════════════
# Main pipeline entry point
# ═══════════════════════════════════════════════════════════════════════════════

async def run_adk_pipeline(sentences: list, junk_ids: set, video_duration: float,
                           file_uri: str, video_id: str,
                           gemini_client) -> list:
    """
    Runs the full ADK 4-agent pipeline asynchronously.
    Returns final processed clips.
    """
    sent_by_id = {s["id"]: s for s in sentences}

    # Build transcript block for session state
    transcript_block = ""
    for s in sentences:
        marker = " ⚠JUNK" if s["id"] in junk_ids else ""
        transcript_block += f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: {s['text']}{marker}\n"

    # Create Gemini cache for VisualAgent's native SDK calls
    print(f"  [Cache] Creating Gemini context cache for VisualAgent...")
    cache_name = create_gemini_cache(file_uri, sentences, junk_ids, gemini_client)

    # Build ADK app and runner
    app, runner, session_service, visual_agent = build_adk_app(gemini_client)

    # Give VisualAgent access to sent_by_id for prompt building
    visual_agent.sent_by_id_ref = sent_by_id

    # Session state — the shared communication bus across all agents
    initial_state = {
        "transcript_block": transcript_block,
        "junk_ids_json":    json.dumps(list(junk_ids)),
        "video_duration":   str(video_duration),
        "n_sentences":      str(len(sentences)),
        "file_uri":         file_uri,
        "video_id":         video_id,
        "gemini_cache_name": cache_name or "",
        "max_passes":       str(MAX_REFINEMENT_PASSES),
        "quality_floor":    str(QUALITY_SCORE_FLOOR),
        "refinement_pass":  "1",
        # Agent outputs (populated during run)
        "scout_flags":      "",
        "narrative_output": "",
        "visual_output":    "",
        "supervisor_output": "",
    }

    user_id    = "clipforge_user"
    session_id = f"session_{video_id}_{int(time.time())}"

    session = await session_service.create_session(
        app_name="clipforge-v19",
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )

    from google.genai import types as gt
    trigger_message = gt.Content(
        role="user",
        parts=[gt.Part(text=f"Select the best clips from video: {video_id}")]
    )

    try:
        print(f"\n  [ADK] Running pipeline (max {MAX_REFINEMENT_PASSES} refinement passes)...")
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=trigger_message
        ):
            if hasattr(event, "author") and event.author:
                content_preview = ""
                if hasattr(event, "content") and event.content and event.content.parts:
                    text = event.content.parts[0].text or ""
                    content_preview = f": {text[:80]}" if text else ""
                print(f"  [ADK Event] {event.author}{content_preview}")

        # Read final result from session
        final_session = await session_service.get_session(
            app_name="clipforge-v19",
            user_id=user_id,
            session_id=session_id
        )
        supervisor_raw = final_session.state.get("supervisor_output", "{}")

    finally:
        if cache_name:
            delete_gemini_cache(cache_name, gemini_client)

    supervisor_result = parse_json_response(
        supervisor_raw if isinstance(supervisor_raw, str) else json.dumps(supervisor_raw),
        "final"
    )
    if not supervisor_result:
        raise RuntimeError("ADK pipeline returned no parseable supervisor output")

    clips = _postprocess_supervisor_clips(supervisor_result, sent_by_id, junk_ids, video_id)
    return clips


def select_clips(transcript_path: str) -> dict:
    """Full pipeline entry point — same interface as v18."""
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

    # Stage 1: Segmentation + junk detection
    print(f"\n📦 Stage 1: Segmentation + junk detection...")
    segments = segment_transcript(sentences)
    if not segments:
        raise RuntimeError("No segments found")
    segments = filter_junk(segments, video_duration)
    junk_ids = get_junk_sentence_ids(segments)
    print(f"  ✓ {len(junk_ids)} junk sentence IDs")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in .env")
    gemini_client = google_genai.Client(api_key=api_key)

    uri_cache_path = transcript_path.replace("_audio_transcript.json", "_file_uri.txt")
    if os.path.exists(uri_cache_path):
        with open(uri_cache_path) as f:
            file_uri = f.read().strip()
        print(f"\n📤 Stage 2: Reusing cached file URI: {file_uri}")
    else:
        print(f"\n📤 Stage 2: Uploading video...")
        file_uri = upload_video_to_file_api(video_path, gemini_client)
        with open(uri_cache_path, "w") as f:
            f.write(file_uri)

    # Stage 3: ADK 4-agent pipeline
    print(f"\n🧠 Stage 3: ADK 4-Agent Pipeline ({GEMINI_MODEL})...")
    print(f"   Scout → [Narrative → Visual → Supervisor → QualityCheck] × {MAX_REFINEMENT_PASSES} max")
    clips = asyncio.run(run_adk_pipeline(
        sentences, junk_ids, video_duration,
        file_uri, video_id, gemini_client
    ))

    if not clips:
        raise RuntimeError("Pipeline returned no clips")

    clips = attach_transcripts(clips, sentences, word_timestamps)

    elapsed = time.time() - pipeline_start
    print(f"\n{'='*65}")
    print(f"SELECTED CLIPS  ({elapsed:.1f}s total)")
    print(f"{'='*65}")

    for i, clip in enumerate(clips, 1):
        seg_summary = " + ".join(
            f"s{s['start_sent_id']}-s{s['end_sent_id']}" for s in clip.get("segments", [])
        )
        print(f"\n🎬 Clip {i} [rank={clip['confidence_rank']}]: {clip.get('why', '')}")
        print(f"   Segments : {seg_summary}")
        print(f"   Time     : {clip['start']:.1f}s → {clip['end']:.1f}s "
              f"(content={clip['duration']:.1f}s)")
        print(f"   Virality : {clip.get('virality_score', '?')}/10  [{clip.get('engagement_type', '?')}]")
        print(f"   Hook     : {clip.get('hook_text', '')[:80]}")
        print(f"   Payoff   : {clip.get('payoff_text', '')[:80]}")
        print(f"   Visual   : {clip.get('visual_note', '')}")

    output = {
        "video_id": video_id, "video_duration": video_duration,
        "total_sentences": len(sentences), "total_segments": len(segments),
        "clips": clips,
        "metadata": {
            "pipeline":       "ClipForge-v19-ADK-NativeMultiAgent",
            "approach":       (
                "junk-detection → video-upload → gemini-cache → "
                "ADK(Scout → LoopAgent[Narrative→Visual→Supervisor→QualityCheck]) → "
                f"iterative refinement up to {MAX_REFINEMENT_PASSES} passes"
            ),
            "language":       "Telugu/Codemix",
            "gemini_model":   GEMINI_MODEL,
            "thinking_level": "HIGH",
            "adk_version":    "google-adk",
            "agent_1":        "ScoutAgent — LlmAgent, text-only, flags viral moments",
            "agent_2":        "NarrativeAgent — LlmAgent, text-only, arc boundaries",
            "agent_3":        "VisualDirectorAgent — CustomBaseAgent, video+text",
            "agent_4":        "SupervisorAgent — LlmAgent, final quality gate",
            "loop_driver":    "ADK LoopAgent + QualityCheckAgent escalation",
            "caching":        "ADK ContextCacheConfig (LlmAgents) + manual Gemini cache (VisualAgent)",
            "quality_floor":  QUALITY_SCORE_FLOOR,
            "max_passes":     MAX_REFINEMENT_PASSES,
            "file_uri":       file_uri,
        }
    }

    output_path = transcript_path.replace("_audio_transcript.json", "_audio_clips_v19.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Saved: {output_path}")
    return output


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python services/clip_selector_v19_adk.py <transcript_json>")
        print("Example: python services/clip_selector_v19_adk.py "
              "storage/uploads/F94zxTfgGOs_audio_transcript.json")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"✗ File not found: {path}")
        sys.exit(1)

    try:
        result = select_clips(path)
        print(f"\n🎉 Done! {len(result['clips'])} clips ready.")
    except Exception as e:
        print(f"\n✗ Pipeline failed: {e}")
        raise