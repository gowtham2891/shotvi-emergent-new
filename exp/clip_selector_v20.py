"""
ClipForge AI — Clip Selector (v20 — Real Multi-Agent System)
============================================================
True multi-agent system where each agent:
  - Has a single focused goal
  - Owns its own tools
  - Loops until IT is satisfied (not until pipeline says stop)
  - Makes decisions grounded in tool results, not self-reflection

AGENT ARCHITECTURE:
  Agent 1 — Cultural Scout
    Goal: find every candidate window with viral potential
    Tools: psychological_trigger_test, cold_open_test
    Loop: scans transcript, tests each window, retries weak hooks
    Exits when: full transcript scanned, confident in all flags

  Agent 2 — Narrative Editor
    Goal: find exact hook+payoff with valid arc
    Tools: payoff_strength_test, emotional_arc_test, viewer_dropoff_test
    Loop: finds payoff, tests arc, adjusts if weak, retries
    Exits when: every candidate has confirmed hook+payoff or is rejected

  Agent 3 — Visual Director
    Goal: confirm video energy matches text analysis
    No tools — native Gemini vision (single focused call per candidate)
    Exits when: all candidates visually validated or rejected

  Agent 4 — Supervisor
    Goal: final quality gate, score, rank, ship
    Tools: none — uses evidence from agents 1-3
    Loop: if quality below floor → sends back to Agent 2 (max 2x)
    Exits when: all clips meet quality floor or max loops reached

WHAT MAKES THIS REAL AGENTS vs v18:
  v18: Python decides what happens next
  v20: Each agent decides its own next action based on tool results

PATCHES APPLIED:
  P1 — response.text or "" (None guard in _agent_call)
  P2 — run_narrative max_tokens=32768
  P3 — run_pipeline carries forward pass-1 good candidates on refinement
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

# ── Our modules ───────────────────────────────────────────────────────────────
from clip_tools import (
    cold_open_test,
    payoff_strength_test,
    psychological_trigger_test,
    emotional_arc_test,
    viewer_dropoff_test,
    run_all_tools,
)
from token_tracker import TokenTracker

load_dotenv()

# ── Models ────────────────────────────────────────────────────────────────────
AGENT_MODEL = "gemini-3-flash-preview"
TOOL_MODEL  = "gemini-3.1-flash-lite"

# ── Embedding model ───────────────────────────────────────────────────────────
EMBEDDING_MODEL       = "l3cube-pune/telugu-sentence-similarity-sbert"
EMBEDDING_MODEL_INDIC = "l3cube-pune/indic-sentence-similarity-sbert"

# ── Clip constraints ──────────────────────────────────────────────────────────
MAX_CLIPS              = 10
MAX_CLIP_LENGTH        = 90

# ── Agent loop config ─────────────────────────────────────────────────────────
MAX_HOOK_SCAN_ATTEMPTS = 3   # Scout scans ±3 around seed to find valid hook
MAX_PAYOFF_ATTEMPTS    = 3   # Narrative walks back max 3 times to find valid payoff
MAX_REFINEMENT_LOOPS   = 2   # Supervisor can send back max 2 times
TRIGGER_STRENGTH_FLOOR = 6   # Scout rejects windows with trigger < 6
QUALITY_SCORE_FLOOR    = 6.5 # Supervisor rejects clips below this

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
    "bye bye", "that's all for today", "welcome back",
    "thank you for watching", "ధన్యవాదాలు", "thanks for watching",
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
    "Emotional": 0.5, "Controversial": 0.5, "Story": 0.5,
    "Relatable": 0.5, "Humor": 0.3, "Educational": 0.0,
    "Wisdom": 0.0, "Insight": 0.0, "Other": -0.2,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Utilities
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
    return any(p in lower for p in PHRASE_JUNK)

def is_intro_text(text: str) -> bool:
    return any(p in text.lower() for p in INTRO_PHRASES)

def is_outro_text(text: str) -> bool:
    return any(p in text.lower() for p in OUTRO_PHRASES)

def is_discourse_marker(text: str) -> bool:
    lower = text.lower().strip()
    return any(re.search(p, lower, re.IGNORECASE) for p in DISCOURSE_MARKERS)

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
    if not text:
        print(f"  [Parse] ✗ {source}: empty response")
        return None
    cleaned = re.sub(r"^```json\s*", "", text.strip())
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  [Parse] ✗ {source}: {e}")
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

def compute_virality_score(hook_score, coherence_score, cultural_score,
                           engagement_score, engagement_type) -> float:
    base = (hook_score * 0.4 + coherence_score * 0.3 +
            cultural_score * 0.2 + engagement_score * 0.1)
    boost = ENGAGEMENT_TIER_BOOST.get(engagement_type, 0.0)
    return round(min(base + boost, 10.0), 2)

def segments_to_timestamps(clip_segments, sent_by_id):
    if not clip_segments: return 0.0, 0.0, 0.0, False
    all_starts, all_ends, total = [], [], 0.0
    for seg in clip_segments:
        try:
            s_id, e_id = int(seg["start_sent_id"]), int(seg["end_sent_id"])
        except (KeyError, ValueError, TypeError):
            return 0.0, 0.0, 0.0, False
        ss, es = sent_by_id.get(s_id), sent_by_id.get(e_id)
        if not ss or not es or es["end"] <= ss["start"]:
            return 0.0, 0.0, 0.0, False
        all_starts.append(ss["start"])
        all_ends.append(es["end"])
        total += es["end"] - ss["start"]
    return round(min(all_starts), 2), round(max(all_ends), 2), round(total, 2), True


# ═══════════════════════════════════════════════════════════════════════════════
# Embedding model
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
# Segmentation
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
        _, sp = similarities[j-1]
        _, sn = similarities[j+1]
        depths.append((i, (sp - sim_i) + (sn - sim_i)))
    if not depths: return []
    dv = [d for _, d in depths]
    mean_d = sum(dv) / len(dv)
    std_d  = math.sqrt(sum((d-mean_d)**2 for d in dv) / len(dv))
    threshold = mean_d + VALLEY_THRESHOLD_ALPHA * std_d
    valleys = [(i, d) for i, d in depths if d > threshold]
    for i, d in valleys:
        s = sentences[i]
        print(f"    [TextTile] Valley s{i} ({s['start']:.1f}s) d={d:.3f}: {s['text'][:50]}")
    return valleys

def find_marker_indices(sentences):
    markers = set()
    for i, s in enumerate(sentences):
        if is_discourse_marker(s["text"]):
            markers.add(i)
    return markers

def build_segments(sentences, boundaries, embeddings):
    if not sentences: return []
    groups, current = [], []
    for i, s in enumerate(sentences):
        if i in sorted(boundaries) and current:
            groups.append(current)
            current = [s]
        else:
            current.append(s)
    if current: groups.append(current)
    segs, seg_id = [], 0
    for group in groups:
        s_start, s_end = group[0]["start"], group[-1]["end"]
        dur = s_end - s_start
        if dur < MIN_SEGMENT_DURATION: continue
        sub = [group[:len(group)//2], group[len(group)//2:]] if dur > MAX_SEGMENT_DURATION else [group]
        for sg in sub:
            ss, se = sg[0]["start"], sg[-1]["end"]
            sd = se - ss
            if sd < MIN_SEGMENT_DURATION: continue
            segs.append({
                "seg_id": seg_id, "sentences": sg,
                "start": round(ss,2), "end": round(se,2), "duration": round(sd,2),
                "full_text": " ".join(s["text"].strip() for s in sg), "is_junk": False,
            })
            seg_id += 1
    return segs

def segment_transcript(sentences):
    print(f"  [Seg] Computing embeddings for {len(sentences)} sentences...")
    embeddings = embed_sentences(sentences)
    valleys = find_embedding_boundaries(sentences, embeddings)
    marker_indices = find_marker_indices(sentences)
    valley_set = set(i for i, _ in valleys)
    all_boundaries = set(valley_set)
    for m in marker_indices:
        if not any(abs(m - v) <= MARKER_BOOST_WINDOW for v in valley_set):
            all_boundaries.add(m)
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
        jc = sum(1 for s in sents
                 if is_junk_text(s["text"]) or is_intro_text(s["text"]) or is_outro_text(s["text"]))
        if jc / len(sents) > 0.5:
            seg["is_junk"] = True
    print(f"  [Filter] {sum(1 for s in segments if s['is_junk'])}/{len(segments)} junk")
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
# Video Upload + Cache
# ═══════════════════════════════════════════════════════════════════════════════

def upload_video_to_file_api(video_path: str, client) -> str:
    print(f"  [Upload] Uploading {Path(video_path).name}...")
    t0 = time.time()
    with open(video_path, "rb") as f:
        uploaded = client.files.upload(
            file=f,
            config={"mime_type": "video/mp4", "display_name": Path(video_path).stem}
        )
    max_wait, poll, waited = 300, 5, 0
    while uploaded.state.name != "ACTIVE":
        if waited >= max_wait: raise RuntimeError("File never became ACTIVE")
        if uploaded.state.name == "FAILED": raise RuntimeError("File FAILED")
        time.sleep(poll); waited += poll
        uploaded = client.files.get(name=uploaded.name)
    print(f"  [Upload] ✓ ACTIVE in {time.time()-t0:.1f}s — URI: {uploaded.uri}")
    return uploaded.uri

def create_cache(file_uri: str, sentences: list, junk_ids: set, client) -> Optional[str]:
    sent_list = ""
    for s in sentences:
        marker = " ⚠JUNK" if s["id"] in junk_ids else ""
        sent_list += f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: {s['text']}{marker}\n"
    try:
        cache = client.caches.create(
            model=AGENT_MODEL,
            config=genai_types.CreateCachedContentConfig(
                contents=[genai_types.Content(
                    parts=[
                        genai_types.Part.from_uri(file_uri=file_uri, mime_type="video/mp4"),
                        genai_types.Part(text=f"TRANSCRIPT:\n{sent_list}"),
                    ],
                    role="user",
                )],
                ttl="600s",
                display_name="clipforge_v20_cache",
            ),
        )
        print(f"  [Cache] ✓ Created: {cache.name}")
        return cache.name
    except Exception as e:
        print(f"  [Cache] ⚠ Failed: {e}")
        return None

def delete_cache(cache_name: str, client) -> None:
    try:
        client.caches.delete(name=cache_name)
        print(f"  [Cache] ✓ Deleted: {cache_name}")
    except Exception as e:
        print(f"  [Cache] ⚠ Delete failed: {e}")

def _agent_call(prompt: str, cache_name: Optional[str],
                file_uri: str, sentences: list, junk_ids: set,
                client, tracker, agent_name: str,
                max_tokens: int = 16384) -> str:
    """Unified agent call — uses cache if available, falls back to inline."""
    sent_list = ""
    for s in sentences:
        marker = " ⚠JUNK" if s["id"] in junk_ids else ""
        sent_list += f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: {s['text']}{marker}\n"

    if cache_name:
        response = client.models.generate_content(
            model=AGENT_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                cached_content=cache_name,
                thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            ),
        )
    else:
        response = client.models.generate_content(
            model=AGENT_MODEL,
            contents=[
                genai_types.Part.from_uri(file_uri=file_uri, mime_type="video/mp4"),
                f"TRANSCRIPT:\n{sent_list}\n\n{prompt}",
            ],
            config=genai_types.GenerateContentConfig(
                thinking_config=genai_types.ThinkingConfig(thinking_level="HIGH"),
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            ),
        )

    if tracker:
        tracker.record(response, agent_name=agent_name,
                       call_type="cached" if cache_name else "video")

    # PATCH 1: guard against None response.text
    return response.text or ""


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT 1 — CULTURAL SCOUT
# ═══════════════════════════════════════════════════════════════════════════════

SCOUT_PROMPT = """You are the Cultural Scout for a Telugu Reels production team.

Your ONLY job: scan the transcript and return a list of candidate windows 
that might contain viral moments for a Telugu 18-35 urban audience.

Be GENEROUS — flag everything that looks interesting.
The Narrative Editor will filter. You are the first pass.

For each candidate window:
- Return approximate start_sent_id and end_sent_id
- Return the single sentence ID you think is the strongest moment
- Return why you flagged it in one sentence

Look for:
- Myth-busting moments
- Shocking facts or statistics  
- Middle class relatable struggles
- Consequence-first statements
- Counter-intuitive ideas
- Strong code-switching moments (Telugu+English)
- Speaker energy peaks
- Anything that makes you think "a Telugu viewer would react to this"

WINDOW SIZE RULES:
- Each window must span at least 8-12 sentences
- A hook sentence alone is NOT a window
- Include enough context for a complete arc: hook → build → payoff
- Minimum window size: 8 sentences. If you can't find 8 sentences, skip it.

SKIP: ⚠JUNK sentences, intro/outro, pure transitions, flat explanations

Return ONLY valid JSON:
{
  "candidate_windows": [
    {
      "start_sent_id": 40,
      "end_sent_id": 58,
      "strongest_sent_id": 46,
      "why": "one sentence reason"
    }
  ]
}"""


def run_scout(sentences: list, sent_by_id: dict, junk_ids: set,
              video_duration: float, file_uri: str,
              cache_name: Optional[str], client, tracker) -> list:
    print(f"\n{'━'*60}")
    print(f"  AGENT 1 — Cultural Scout")
    print(f"{'━'*60}")

    print(f"  [Scout] Scanning transcript for candidate windows...")
    raw = _agent_call(SCOUT_PROMPT, cache_name, file_uri,
                      sentences, junk_ids, client, tracker, "Scout")

    result = parse_json_response(raw, "scout")
    if not result or "candidate_windows" not in result:
        raise RuntimeError("Scout returned no candidate windows")

    raw_windows = result["candidate_windows"]
    print(f"  [Scout] LLM identified {len(raw_windows)} rough windows")

    confirmed_candidates = []

    for i, window in enumerate(raw_windows, 1):
        start_id = int(window.get("start_sent_id", 0))
        end_id   = int(window.get("end_sent_id", 0))
        seed_id  = int(window.get("strongest_sent_id", start_id))

        print(f"\n  [Scout] Window {i}/{len(raw_windows)}: "
              f"s{start_id}-s{end_id} (seed=s{seed_id})")

        if seed_id in junk_ids:
            print(f"  [Scout] ✗ Seed sentence is junk — skipping window")
            continue

        trigger_result = psychological_trigger_test(
            start_id, end_id, sentences, sent_by_id,
            junk_ids, client, tracker
        )

        if trigger_result.get("trigger_strength", 0) < TRIGGER_STRENGTH_FLOOR:
            print(f"  [Scout] ✗ Trigger too weak "
                  f"({trigger_result.get('trigger_strength')}) — skipping window")
            continue

        print(f"  [Scout] ✓ Trigger: {trigger_result.get('primary_trigger')} "
              f"strength={trigger_result.get('trigger_strength')}")

        hook_id = None
        hook_result = None

        scan_ids = [seed_id]
        for offset in range(1, MAX_HOOK_SCAN_ATTEMPTS + 1):
            nxt = seed_id + offset
            if nxt <= end_id and nxt not in scan_ids:
                scan_ids.append(nxt)
            prv = seed_id - offset
            if prv >= start_id and prv not in scan_ids:
                scan_ids.append(prv)

        for scan_id in scan_ids:
            if scan_id in junk_ids:
                continue

            cold = cold_open_test(
                scan_id, sentences, sent_by_id,
                junk_ids, client, tracker
            )

            if cold.get("stops_scrolling") and cold.get("confidence", 0) >= 6:
                hook_id = scan_id
                hook_result = cold
                print(f"  [Scout] ✓ Hook confirmed: s{hook_id} "
                      f"feeling={cold.get('feeling')} "
                      f"confidence={cold.get('confidence')}")
                break
            else:
                print(f"  [Scout] ✗ s{scan_id} not a valid hook "
                      f"(stops={cold.get('stops_scrolling')}, "
                      f"confidence={cold.get('confidence')}) — trying next")

        if hook_id is None:
            print(f"  [Scout] ✗ No valid hook found after "
                  f"{len(scan_ids)} attempts — rejecting window")
            continue

        confirmed_candidates.append({
            "start_sent_id":    start_id,
            "end_sent_id":      end_id,
            "hook_id":          hook_id,
            "why":              window.get("why", ""),
            "primary_trigger":  trigger_result.get("primary_trigger", "Unknown"),
            "trigger_strength": trigger_result.get("trigger_strength", 0),
            "trigger_evidence": trigger_result.get("evidence", ""),
            "cold_open":        hook_result,
        })

        print(f"  [Scout] ✓ Window confirmed: "
              f"s{start_id}-s{end_id} hook=s{hook_id} "
              f"trigger={trigger_result.get('primary_trigger')}")

    print(f"\n  [Scout] Done: {len(confirmed_candidates)}/{len(raw_windows)} "
          f"windows confirmed")
    return confirmed_candidates


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT 2 — NARRATIVE EDITOR
# ═══════════════════════════════════════════════════════════════════════════════

def _build_narrative_prompt(scout_candidates: list, sent_by_id: dict,
                             refinement_pass: int = 1,
                             refine_ids: list = None) -> str:
    candidates_to_process = scout_candidates
    if refine_ids is not None:
        candidates_to_process = [c for c in scout_candidates
                                  if c.get("hook_id") in refine_ids]

    mode = ""
    if refinement_pass > 1:
        mode = f"""━━━ REFINEMENT PASS {refinement_pass} ━━━
The Supervisor sent these candidates back because quality was below threshold.
Be STRICTER this pass — tighter boundaries, reject anything marginal.

"""

    candidates_text = ""
    for i, c in enumerate(candidates_to_process, 1):
        hook_s = sent_by_id.get(c["hook_id"])
        candidates_text += f"""
CANDIDATE {i}:
  Window: s{c['start_sent_id']} → s{c['end_sent_id']}
  Confirmed hook: s{c['hook_id']} — "{hook_s['text'] if hook_s else '?'}"
  Trigger: {c.get('primary_trigger')} (strength={c.get('trigger_strength')})
  Why flagged: {c.get('why', '')}
"""

    return f"""{mode}You are the Narrative Editor for a Telugu Reels production team.

The Cultural Scout has confirmed {len(candidates_to_process)} candidate(s)
with strong psychological hooks. Your job: find the exact PAYOFF sentence
and identify any middle FILLER to drop.

You are NOT re-evaluating hooks — they are already confirmed.
You are ONLY finding payoffs and filler.

PAYOFF rules:
- Must resolve the tension the hook created
- Must be a complete thought
- Must NOT end on: "చెప్తాను", "చూద్దాం", CTAs, mid-thought fragments
- If natural end is weak → walk back to previous strong sentence

FILLER to mark as drop_ranges:
- Repetition of same idea in different words
- Tangents that don't serve the arc
- Sponsor/CTA sentences inside the clip
- Energy-dead explanations that add no new information

REJECT entire candidate only if:
- No sentence in the window resolves the hook's tension
- Content is purely informational, no emotional resolution possible

CANDIDATES:
{candidates_text}

Return ONLY valid JSON:
{{
  "narrative_results": [
    {{
      "hook_id": 46,
      "accepted": true,
      "payoff_sent_id": 53,
      "drop_ranges": [
        {{"start": 49, "end": 50, "reason": "repetition of earlier point"}}
      ],
      "rejection_reason": ""
    }}
  ]
}}"""


def run_narrative(scout_candidates: list, sentences: list,
                  sent_by_id: dict, junk_ids: set,
                  file_uri: str, cache_name: Optional[str],
                  client, tracker,
                  refinement_pass: int = 1,
                  refine_hook_ids: list = None) -> list:
    mode = "refinement" if refinement_pass > 1 else "first pass"
    print(f"\n{'━'*60}")
    print(f"  AGENT 2 — Narrative Editor ({mode})")
    print(f"{'━'*60}")

    candidates_to_process = scout_candidates
    if refine_hook_ids:
        candidates_to_process = [c for c in scout_candidates
                                  if c["hook_id"] in refine_hook_ids]

    prompt = _build_narrative_prompt(
        candidates_to_process, sent_by_id, refinement_pass, refine_hook_ids
    )

    # PATCH 2: max_tokens=32768 for narrative (many candidates can exceed 16384)
    raw = _agent_call(prompt, cache_name, file_uri,
                      sentences, junk_ids, client, tracker, "Narrative",
                      max_tokens=32768)

    result = parse_json_response(raw, "narrative")

    if result is None:
        try:
            cleaned = raw.strip()
            cleaned = re.sub(r"^```json\s*", "", cleaned)
            cleaned = re.sub(r"^```\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                print(f"  [Narrative] Parsed as array — wrapping")
                result = {"narrative_results": parsed}
        except Exception:
            pass

    if not result or "narrative_results" not in result:
        print(f"  [Narrative] ⚠ Could not parse — raw preview:")
        print(f"  {raw[:300]}")
        raise RuntimeError("Narrative returned no results")

    narrative_results = {r["hook_id"]: r
                         for r in result["narrative_results"]}

    validated_candidates = []

    for candidate in candidates_to_process:
        hook_id  = candidate["hook_id"]
        start_id = candidate["start_sent_id"]
        end_id   = candidate["end_sent_id"]

        narr = narrative_results.get(hook_id)
        if not narr or not narr.get("accepted", False):
            reason = (narr or {}).get("rejection_reason", "rejected by narrative")
            print(f"\n  [Narrative] s{hook_id}: ✗ Rejected — {reason}")
            continue

        payoff_id   = int(narr.get("payoff_sent_id", end_id))
        drop_ranges = narr.get("drop_ranges", [])

        # Reject single-sentence clips immediately
        if payoff_id <= hook_id:
            print(f"\n  [Narrative] s{hook_id}: ✗ Rejected — payoff=hook (single sentence clip)")
            continue

        # Enforce minimum span of 4 sentences
        if payoff_id - hook_id < 4:
            payoff_id = min(hook_id + 4, end_id)
            print(f"  [Narrative] ⚠ Span too short — extending payoff to s{payoff_id}")

        print(f"\n  [Narrative] Testing s{hook_id}→s{payoff_id}...")

        payoff_confirmed = False
        current_payoff   = payoff_id

        for attempt in range(MAX_PAYOFF_ATTEMPTS):
            payoff_result = payoff_strength_test(
                hook_id, current_payoff, sentences,
                sent_by_id, junk_ids, client, tracker
            )

            if payoff_result.get("satisfied"):
                payoff_id        = current_payoff
                payoff_confirmed = True
                print(f"  [Narrative] ✓ Payoff confirmed: s{payoff_id}")
                break
            else:
                if current_payoff > hook_id + 1:
                    current_payoff -= 1
                    print(f"  [Narrative] ✗ Payoff weak — trying s{current_payoff}")
                else:
                    print(f"  [Narrative] ✗ No valid payoff found — rejecting")
                    break

        if not payoff_confirmed:
            continue

        arc_result = emotional_arc_test(
            hook_id, payoff_id, sentences,
            sent_by_id, junk_ids, client, tracker
        )

        if not arc_result.get("arc_valid"):
            weak_points = arc_result.get("weak_points", [])
            if weak_points:
                new_drops = [{"start": wp["sentence_id"],
                              "end": wp["sentence_id"],
                              "reason": wp["issue"]}
                             for wp in weak_points]
                drop_ranges = drop_ranges + new_drops
                print(f"  [Narrative] ⚠ Arc weak — added {len(new_drops)} drop ranges")
            else:
                print(f"  [Narrative] ✗ Arc invalid, no fixable weak points — rejecting")
                continue

        dropoff_result = viewer_dropoff_test(
            hook_id, payoff_id, sentences,
            sent_by_id, junk_ids, client, tracker
        )

        if not dropoff_result.get("would_watch_till_end"):
            dropoff_at = dropoff_result.get("dropoff_sentence_id")
            if dropoff_at and dropoff_at > hook_id:
                adj_payoff = payoff_strength_test(
                    hook_id, dropoff_at - 1, sentences,
                    sent_by_id, junk_ids, client, tracker
                )
                if adj_payoff.get("satisfied"):
                    payoff_id = dropoff_at - 1
                    print(f"  [Narrative] ✓ Adjusted payoff to s{payoff_id} "
                          f"(before dropoff)")
                else:
                    print(f"  [Narrative] ✗ Viewer drops off and no good earlier "
                          f"payoff — rejecting")
                    continue
            else:
                print(f"  [Narrative] ✗ Viewer drops off immediately — rejecting")
                continue

        validated_candidates.append({
            **candidate,
            "payoff_id":      payoff_id,
            "drop_ranges":    drop_ranges,
            "arc_result":     arc_result,
            "dropoff_result": dropoff_result,
        })
        print(f"  [Narrative] ✓ Validated: "
              f"hook=s{hook_id} payoff=s{payoff_id} "
              f"drops={len(drop_ranges)}")

    print(f"\n  [Narrative] Done: {len(validated_candidates)}/"
          f"{len(candidates_to_process)} candidates validated")
    return validated_candidates


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT 3 — VISUAL DIRECTOR
# ═══════════════════════════════════════════════════════════════════════════════

def _build_visual_prompt(narrative_candidates: list, sent_by_id: dict) -> str:
    candidates_text = ""
    for i, c in enumerate(narrative_candidates, 1):
        hook_s   = sent_by_id.get(c["hook_id"])
        payoff_s = sent_by_id.get(c["payoff_id"])
        candidates_text += f"""
CANDIDATE {i}:
  Hook: s{c['hook_id']} at ~{hook_s['start'] if hook_s else '?'}s
        "{hook_s['text'] if hook_s else '?'}"
  Payoff: s{c['payoff_id']} at ~{payoff_s['end'] if payoff_s else '?'}s
          "{payoff_s['text'] if payoff_s else '?'}"
  Trigger: {c.get('primary_trigger')} (strength={c.get('trigger_strength')})
  Drop ranges: {c.get('drop_ranges', [])}
"""

    return f"""You are the Visual Director for a Telugu Reels production team.
You have the actual video. Watch it carefully.

The Scout and Narrative Editor have identified {len(narrative_candidates)} 
candidate(s) with confirmed psychological hooks and payoffs.

Your job: watch the video at each candidate's timestamps and answer:
1. Does the speaker's energy actually MATCH the psychological trigger?
2. Is there a clear visual energy spike at the hook timestamp?
3. Does the energy resolve naturally at the payoff timestamp?
4. Are the suggested drop_ranges visually dead too?
5. Any NEW visual dead zones the text analysis missed?

You MAY shift hook ±2 sentences based on visual evidence.
You MAY shift payoff ±2 sentences based on visual evidence.
You MUST cite SPECIFIC visual evidence — not just "high energy."
"Speaker leaned forward and raised voice at 49.1s" is evidence.
"High energy" is not evidence.

REJECT visually (visual_reject=true) ONLY if entire segment is dead —
speaker reading from notes throughout, zero camera engagement.

CANDIDATES:
{candidates_text}

Return ONLY valid JSON:
{{
  "visual_validations": [
    {{
      "hook_id": 46,
      "validated": true,
      "final_hook_id": 46,
      "final_payoff_id": 53,
      "hook_adjusted": false,
      "payoff_adjusted": false,
      "hook_adjustment_reason": "",
      "payoff_adjustment_reason": "",
      "confirmed_drops": [49, 50],
      "additional_drops": [],
      "visual_energy_at_hook": "<specific evidence>",
      "visual_energy_at_payoff": "<specific evidence>",
      "visual_reject": false,
      "visual_reject_reason": ""
    }}
  ]
}}"""


def run_visual(narrative_candidates: list, sentences: list,
               sent_by_id: dict, junk_ids: set,
               file_uri: str, cache_name: Optional[str],
               client, tracker) -> list:
    print(f"\n{'━'*60}")
    print(f"  AGENT 3 — Visual Director")
    print(f"{'━'*60}")
    print(f"  [Visual] Watching video for {len(narrative_candidates)} candidates...")

    prompt = _build_visual_prompt(narrative_candidates, sent_by_id)
    raw = _agent_call(prompt, cache_name, file_uri,
                      sentences, junk_ids, client, tracker,
                      "Visual", max_tokens=16384)

    result = parse_json_response(raw, "visual")
    if not result or "visual_validations" not in result:
        print("  [Visual] ⚠ Could not parse visual validations — passing all through")
        return [{
            **c,
            "final_hook_id":   c["hook_id"],
            "final_payoff_id": c["payoff_id"],
            "visual_energy":   "visual validation unavailable",
            "visual_reject":   False,
        } for c in narrative_candidates]

    validations = {v["hook_id"]: v for v in result["visual_validations"]}
    visual_candidates = []

    for c in narrative_candidates:
        hook_id = c["hook_id"]
        v = validations.get(hook_id)

        if not v:
            print(f"  [Visual] ⚠ No validation for s{hook_id} — passing through")
            visual_candidates.append({
                **c,
                "final_hook_id":   hook_id,
                "final_payoff_id": c["payoff_id"],
                "visual_energy":   "not validated",
                "visual_reject":   False,
            })
            continue

        if v.get("visual_reject"):
            print(f"  [Visual] ✗ s{hook_id} visually rejected: "
                  f"{v.get('visual_reject_reason', '')}")
            continue

        existing_drops     = c.get("drop_ranges", [])
        confirmed_drop_ids = set(v.get("confirmed_drops", []))
        additional_drop_ids = set(v.get("additional_drops", []))
        all_drop_ids       = confirmed_drop_ids | additional_drop_ids

        merged_drops = [d for d in existing_drops
                        if d["start"] in all_drop_ids or d["end"] in all_drop_ids]
        for did in additional_drop_ids:
            if not any(d["start"] == did for d in merged_drops):
                merged_drops.append({"start": did, "end": did,
                                     "reason": "visual dead zone"})

        adj = []
        if v.get("hook_adjusted"):   adj.append(f"hook→s{v['final_hook_id']}")
        if v.get("payoff_adjusted"): adj.append(f"payoff→s{v['final_payoff_id']}")
        adj_str = f" [{', '.join(adj)}]" if adj else ""

        print(f"  [Visual] ✓ s{hook_id}{adj_str}: "
              f"{v.get('visual_energy_at_hook', '')[:60]}")

        visual_candidates.append({
            **c,
            "hook_id":         int(v.get("final_hook_id", hook_id)),
            "payoff_id":       int(v.get("final_payoff_id", c["payoff_id"])),
            "final_hook_id":   int(v.get("final_hook_id", hook_id)),
            "final_payoff_id": int(v.get("final_payoff_id", c["payoff_id"])),
            "drop_ranges":     merged_drops,
            "visual_energy":   v.get("visual_energy_at_hook", ""),
            "visual_reject":   False,
        })

    print(f"\n  [Visual] Done: {len(visual_candidates)}/"
          f"{len(narrative_candidates)} candidates visually validated")
    return visual_candidates


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT 4 — SUPERVISOR
# ═══════════════════════════════════════════════════════════════════════════════

def _build_supervisor_prompt(visual_candidates: list, sent_by_id: dict,
                              video_id: str, refinement_pass: int) -> str:
    clip_prefix = video_id or "clip"

    candidates_block = ""
    for c in visual_candidates:
        hook_s   = sent_by_id.get(c["hook_id"])
        payoff_s = sent_by_id.get(c["payoff_id"])

        drops = sorted(c.get("drop_ranges", []), key=lambda x: x["start"])
        if drops:
            segments_hint = f"segments array needed — drop ranges: {drops}"
        else:
            segments_hint = f"single segment: s{c['hook_id']}→s{c['payoff_id']}"

        candidates_block += f"""
CANDIDATE (hook=s{c['hook_id']}):
  Hook:    s{c['hook_id']} — "{hook_s['text'] if hook_s else '?'}"
  Payoff:  s{c['payoff_id']} — "{payoff_s['text'] if payoff_s else '?'}"
  Trigger: {c.get('primary_trigger')} strength={c.get('trigger_strength')}
  Evidence: {c.get('trigger_evidence', '')}
  Arc:     valid={c.get('arc_result', {}).get('arc_valid')} 
           builds={c.get('arc_result', {}).get('builds_correctly')}
           resolves={c.get('arc_result', {}).get('resolves_cleanly')}
  Dropoff: watches_till_end={c.get('dropoff_result', {}).get('would_watch_till_end')}
           retention={c.get('dropoff_result', {}).get('retention_score')}
  Visual:  {c.get('visual_energy', '')}
  Segments: {segments_hint}
"""

    rerun_note = ""
    if refinement_pass > 1:
        rerun_note = f"""━━━ REFINEMENT PASS {refinement_pass} ━━━
This is your second review. Be STRICT. Only ship clips you are 
genuinely confident about. Set needs_refinement=false now — 
accept the best available clips.

"""

    return f"""{rerun_note}You are the Executive Supervisor for a Telugu Reels production team.
You are the FINAL decision maker. What you output ships.

Refinement pass: {refinement_pass}
Quality floor: {QUALITY_SCORE_FLOOR}/10

You have full evidence from Scout (triggers), Narrative (arc), 
and Visual (energy) for each candidate.

YOUR JOB:
1. Build final segments arrays applying drop_ranges
2. Reject duplicates — same trigger, same topic → keep stronger
3. Reject overlapping sentence IDs — keep higher quality
4. Score HONESTLY using the evidence provided:
   hook_score (1-10): based on trigger_strength + cold_open confidence
   coherence_score (1-10): based on arc validity + builds/resolves
   cultural_score (1-10): based on trigger type + Telugu relevance
   engagement_score (1-10): based on retention_score + would_watch_till_end
5. Rank: 1 = post first
6. DECIDE: if any clip scores below {QUALITY_SCORE_FLOOR} AND 
   refinement_pass < 2 → set needs_refinement=true

SEGMENTS RULE:
- No drops: [{{"start_sent_id": hook, "end_sent_id": payoff}}]
- With drops: split into multiple segments around the drop ranges

CANDIDATES:
{candidates_block}

Return ONLY valid JSON:
{{
  "needs_refinement": false,
  "refine_hook_ids": [],
  "refinement_reason": "",
  "clips": [
    {{
      "clip_id": "{clip_prefix}_c1",
      "hook_id": 46,
      "segments": [{{"start_sent_id": 46, "end_sent_id": 53}}],
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
      "psychological_trigger": "<primary trigger name>",
      "trimmed": false,
      "trim_reason": "",
      "notes": ""
    }}
  ]
}}"""


def run_supervisor(visual_candidates: list, sentences: list,
                   sent_by_id: dict, junk_ids: set,
                   file_uri: str, cache_name: Optional[str],
                   video_id: str, client, tracker,
                   refinement_pass: int = 1) -> dict:
    pass_label = f"pass {refinement_pass}"
    print(f"\n{'━'*60}")
    print(f"  AGENT 4 — Supervisor ({pass_label})")
    print(f"{'━'*60}")

    prompt = _build_supervisor_prompt(
        visual_candidates, sent_by_id, video_id, refinement_pass
    )
    raw = _agent_call(prompt, cache_name, file_uri,
                      sentences, junk_ids, client, tracker,
                      "Supervisor", max_tokens=32768)

    result = parse_json_response(raw, "supervisor")
    if not result:
        raise RuntimeError("Supervisor returned unparseable response")

    clips            = result.get("clips", [])
    needs_refinement = result.get("needs_refinement", False)

    print(f"  [Supervisor] {len(clips)} clips, "
          f"needs_refinement={needs_refinement}")

    for clip in clips:
        print(f"    rank={clip.get('confidence_rank')} "
              f"hook_score={clip.get('hook_score')} "
              f"hook='{clip.get('hook_text', '')[:60]}'")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Post-processing
# ═══════════════════════════════════════════════════════════════════════════════

def _postprocess_clips(supervisor_result: dict, sent_by_id: dict,
                       junk_ids: set, video_id: str) -> list:
    gemini_clips = supervisor_result.get("clips", [])
    if not gemini_clips: return []
    final_clips = []

    for gc in gemini_clips:
        clip_segments = gc.get("segments")
        if not clip_segments:
            s_id, e_id = gc.get("start_sent_id"), gc.get("end_sent_id")
            if s_id is not None and e_id is not None:
                clip_segments = [{"start_sent_id": int(s_id),
                                   "end_sent_id":   int(e_id)}]
            else:
                continue

        n_sents = max(sent_by_id.keys()) + 1 if sent_by_id else 0
        resolved = []
        for seg in clip_segments:
            try:
                s = max(0, min(int(seg["start_sent_id"]), n_sents-1))
                e = max(0, min(int(seg["end_sent_id"]),   n_sents-1))
                if e > s: resolved.append({"start_sent_id": s, "end_sent_id": e})
            except (KeyError, ValueError, TypeError):
                continue

        if not resolved: continue

        clip_start, clip_end, duration, is_valid = segments_to_timestamps(
            resolved, sent_by_id
        )
        if not is_valid or duration < 5: continue

        hook_sent_id   = int(resolved[0]["start_sent_id"])
        payoff_sent_id = int(resolved[-1]["end_sent_id"])
        hook_sent      = sent_by_id.get(hook_sent_id)
        payoff_sent    = sent_by_id.get(payoff_sent_id)

        if hook_sent_id in junk_ids: continue

        hook_text   = strip_hook_prefix(
            gc.get("hook_text") or (hook_sent["text"] if hook_sent else ""))
        payoff_text = gc.get("payoff_text") or \
                      (payoff_sent["text"] if payoff_sent else "")

        hook_score       = float(gc.get("hook_score",       5.0))
        coherence_score  = float(gc.get("coherence_score",  5.0))
        cultural_score   = float(gc.get("cultural_score",   5.0))
        engagement_score = float(gc.get("engagement_score", 5.0))
        engagement_type  = gc.get("engagement_type", "Insight")
        virality_score   = compute_virality_score(
            hook_score, coherence_score, cultural_score,
            engagement_score, engagement_type
        )

        clip = {
            "clip_id":               gc.get("clip_id",
                                            f"{video_id}_c{len(final_clips)+1}"),
            "start": clip_start, "end": clip_end, "duration": duration,
            "segments":              resolved,
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
        print(f"  [Post] rank={clip['confidence_rank']} "
              f"[{clip_start:.1f}s→{clip_end:.1f}s] "
              f"content={duration:.1f}s virality={virality_score} "
              f"hook='{hook_text[:50]}'")
        final_clips.append(clip)

    final_clips.sort(key=lambda c: c["confidence_rank"])

    used: set = set()
    ranked = []
    for clip in final_clips:
        ids = set()
        for seg in clip["segments"]:
            ids.update(range(int(seg["start_sent_id"]),
                             int(seg["end_sent_id"])+1))
        if ids & used:
            print(f"  [Overlap] Dropping rank={clip['confidence_rank']}")
            continue
        used |= ids
        ranked.append(clip)

    return ranked[:MAX_CLIPS]


# ═══════════════════════════════════════════════════════════════════════════════
# Attach transcripts
# ═══════════════════════════════════════════════════════════════════════════════

def attach_transcripts(clips, all_sentences, word_timestamps=None):
    sent_by_id = {s["id"]: s for s in all_sentences}
    for clip in clips:
        transcript = []
        for seg_idx, seg in enumerate(clip.get("segments", [])):
            s_id, e_id = int(seg["start_sent_id"]), int(seg["end_sent_id"])
            for s in [sent_by_id[i] for i in range(s_id, e_id+1)
                      if i in sent_by_id]:
                transcript.append({
                    "start": round(s["start"],2),
                    "end":   round(s["end"],2),
                    "text":  s["text"]
                })
            if seg_idx < len(clip["segments"]) - 1:
                transcript.append({"start":-1,"end":-1,"text":"[CUT]"})
        clip["transcript"] = transcript
        clip["transcript_text"] = " ".join(
            s["text"] for s in transcript if s["text"] != "[CUT]")
    return clips


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def run_pipeline(sentences: list, junk_ids: set, video_duration: float,
                 file_uri: str, video_id: str, client, tracker) -> list:
    sent_by_id = {s["id"]: s for s in sentences}

    print(f"\n  [Cache] Creating context cache...")
    cache_name = create_cache(file_uri, sentences, junk_ids, client)

    try:
        # ── Agent 1: Scout ────────────────────────────────────────────────────
        scout_candidates = run_scout(
            sentences, sent_by_id, junk_ids, video_duration,
            file_uri, cache_name, client, tracker
        )
        if not scout_candidates:
            raise RuntimeError("Scout found no confirmed candidates")

        time.sleep(3)

        # ── Refinement loop: Narrative → Visual → Supervisor ──────────────────
        narrative_candidates  = None
        visual_candidates     = None
        supervisor_result     = None
        # PATCH 3: accumulator so good pass-1 candidates survive refinement
        all_visual_candidates = []

        for refinement_pass in range(1, MAX_REFINEMENT_LOOPS + 2):
            print(f"\n  [Pipeline] Refinement pass {refinement_pass}/"
                  f"{MAX_REFINEMENT_LOOPS + 1}")

            refine_ids = None
            if supervisor_result and supervisor_result.get("needs_refinement"):
                refine_ids = supervisor_result.get("refine_hook_ids", [])
                print(f"  [Pipeline] Re-running Narrative on "
                      f"hook_ids: {refine_ids}")

            narrative_candidates = run_narrative(
                scout_candidates, sentences, sent_by_id,
                junk_ids, file_uri, cache_name, client, tracker,
                refinement_pass=refinement_pass,
                refine_hook_ids=refine_ids
            )

            if not narrative_candidates:
                print(f"  [Pipeline] ✗ Narrative rejected all — "
                      f"no clips to ship")
                break

            time.sleep(3)

            visual_candidates = run_visual(
                narrative_candidates, sentences, sent_by_id,
                junk_ids, file_uri, cache_name, client, tracker
            )

            if not visual_candidates:
                print(f"  [Pipeline] ✗ Visual rejected all")
                break

            # PATCH 3: carry forward non-refined good candidates from pass 1
            if refinement_pass > 1 and all_visual_candidates:
                existing_hooks = {c["hook_id"] for c in visual_candidates}
                carried = [c for c in all_visual_candidates
                           if c["hook_id"] not in existing_hooks]
                if carried:
                    print(f"  [Pipeline] Carrying {len(carried)} pass-1 "
                          f"candidate(s) forward")
                visual_candidates = carried + visual_candidates

            # Update accumulator with full current set
            all_visual_candidates = visual_candidates

            time.sleep(3)

            supervisor_result = run_supervisor(
                visual_candidates, sentences, sent_by_id,
                junk_ids, file_uri, cache_name, video_id,
                client, tracker, refinement_pass
            )

            if (not supervisor_result.get("needs_refinement") or
                    refinement_pass >= MAX_REFINEMENT_LOOPS + 1):
                print(f"  [Pipeline] ✓ Supervisor satisfied — "
                      f"finalising clips")
                break

            time.sleep(3)

        if not supervisor_result or not supervisor_result.get("clips"):
            return []

        clips = _postprocess_clips(
            supervisor_result, sent_by_id, junk_ids, video_id
        )

    finally:
        if cache_name:
            delete_cache(cache_name, client)

    return clips


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def select_clips(transcript_path: str) -> dict:
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
    print(f"✓ Video duration : {video_duration:.1f}s ({video_duration/60:.1f} min)")
    print(f"✓ Sentences      : {len(sentences)}")

    print(f"\n📦 Stage 1: Segmentation + junk detection...")
    segments = segment_transcript(sentences)
    if not segments: raise RuntimeError("No segments found")
    segments = filter_junk(segments, video_duration)
    junk_ids = get_junk_sentence_ids(segments)
    print(f"  ✓ {len(junk_ids)} junk sentence IDs")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: raise RuntimeError("GEMINI_API_KEY not found")
    client = google_genai.Client(api_key=api_key)

    uri_cache_path = transcript_path.replace(
        "_audio_transcript.json", "_file_uri.txt")
    if os.path.exists(uri_cache_path):
        with open(uri_cache_path) as f:
            file_uri = f.read().strip()
        print(f"\n📤 Stage 2: Reusing cached URI: {file_uri}")
    else:
        print(f"\n📤 Stage 2: Uploading video...")
        file_uri = upload_video_to_file_api(video_path, client)
        with open(uri_cache_path, "w") as f:
            f.write(file_uri)

    print(f"\n🧠 Stage 3: Real Multi-Agent Pipeline (v20)")
    print(f"   Agents: Scout → Narrative → Visual → Supervisor")
    print(f"   Tools:  psychological_trigger + cold_open + "
          f"payoff_strength + emotional_arc + viewer_dropoff")
    print(f"   Models: {AGENT_MODEL} (agents) | {TOOL_MODEL} (tools)")

    tracker = TokenTracker(
        model=AGENT_MODEL,
        pipeline_name=f"v20 — {video_id}"
    )

    clips = run_pipeline(
        sentences, junk_ids, video_duration,
        file_uri, video_id, client, tracker
    )

    if not clips:
        raise RuntimeError("Pipeline returned no clips")

    clips = attach_transcripts(clips, sentences, word_timestamps)

    elapsed = time.time() - pipeline_start
    tracker.print_summary()

    print(f"\n{'='*65}")
    print(f"SELECTED CLIPS  ({elapsed:.1f}s total)")
    print(f"{'='*65}")

    for i, clip in enumerate(clips, 1):
        seg_summary = " + ".join(
            f"s{s['start_sent_id']}-s{s['end_sent_id']}"
            for s in clip.get("segments", [])
        )
        print(f"\n🎬 Clip {i} [rank={clip['confidence_rank']}]: "
              f"{clip.get('why', '')}")
        print(f"   Segments : {seg_summary}")
        print(f"   Time     : {clip['start']:.1f}s → {clip['end']:.1f}s "
              f"(content={clip['duration']:.1f}s)")
        print(f"   Virality : {clip.get('virality_score', '?')}/10 "
              f"[{clip.get('engagement_type', '?')}]")
        print(f"   Trigger  : {clip.get('psychological_trigger', '?')}")
        print(f"   Hook     : {clip.get('hook_text', '')[:80]}")
        print(f"   Payoff   : {clip.get('payoff_text', '')[:80]}")
        print(f"   Visual   : {clip.get('visual_note', '')}")

    output = {
        "video_id":        video_id,
        "video_duration":  video_duration,
        "total_sentences": len(sentences),
        "total_segments":  len(segments),
        "clips":           clips,
        "token_report":    tracker.get_report(),
        "metadata": {
            "pipeline":        "ClipForge-v20-RealMultiAgent",
            "approach":        (
                "junk-detection → video-upload → context-cache → "
                "Scout[trigger+cold_open tools] → "
                "Narrative[payoff+arc+dropoff tools] → "
                "Visual[native Gemini vision] → "
                "Supervisor[scores+ranks+loops]"
            ),
            "language":        "Telugu/Codemix",
            "agent_model":     AGENT_MODEL,
            "tool_model":      TOOL_MODEL,
            "thinking_level":  "HIGH (agents) | none (tools)",
            "max_refinements": MAX_REFINEMENT_LOOPS,
            "quality_floor":   QUALITY_SCORE_FLOOR,
            "trigger_floor":   TRIGGER_STRENGTH_FLOOR,
            "file_uri":        file_uri,
        }
    }

    output_path = transcript_path.replace(
        "_audio_transcript.json", "_audio_clips_v20.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Saved: {output_path}")

    return output


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python services/clip_selector_v20.py <transcript_json>")
        print("Example: python services/clip_selector_v20.py "
              "storage/uploads/9QAZl1djrUA_audio_transcript.json")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"✗ File not found: {path}")
        sys.exit(1)

    try:
        result = select_clips(path)
        report = result.get("token_report", {})
        total  = report.get("totals", {}).get("grand_total_usd", 0)
        print(f"\n🎉 Done! {len(result['clips'])} clips | "
              f"Total cost: ${total:.4f}")
    except Exception as e:
        print(f"\n✗ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()