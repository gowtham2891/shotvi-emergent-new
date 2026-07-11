"""
ClipForge AI — Psychological Clip Tools (v20)
=============================================
5 focused LLM tools used by agents to make grounded decisions.

All tools:
  - Use gemini-3.1-flash-lite (cheap, fast, no thinking needed)
  - Take full transcript as context (never blind)
  - Ask ONE focused question about ONE specific moment
  - Return structured JSON (not free text)
  - Are registered with TokenTracker automatically

Tool summary:
  cold_open_test             → would viewer stop scrolling at this sentence?
  payoff_strength_test       → does payoff resolve hook's tension?
  psychological_trigger_test → which viral trigger fires? how strongly?
  emotional_arc_test         → does tension build and resolve correctly?
  viewer_dropoff_test        → where would viewer stop watching?
"""

import json
import re
from typing import Optional

from google import genai as google_genai
from google.genai import types as genai_types

# ── Tool model — cheap, fast, no thinking ────────────────────────────────────
TOOL_MODEL = "gemini-3.1-flash-lite"


# ── The 6 Telugu viral psychological triggers ─────────────────────────────────
TELUGU_TRIGGERS = """
1. Loss Aversion
   "I might be losing something / making a mistake right now"
   Example: "ఈ ఒక్క mistake వల్ల మీ career అయిపోతుంది"

2. Identity Threat
   "This is about someone exactly like me and something is wrong"
   Example: "చదువుకున్న వాళ్ళు కూడా ఈ trap లో పడతారు"

3. Curiosity Gap
   "I need to know how this ends — brain can't rest"
   Example: "దీని వెనక అసలు కారణం ఎవరూ చెప్పరు"

4. Social Currency
   "Sharing this makes me look smart/caring to my network"
   Example: "మీ friends కి ఇది తెలిసే chance లేదు"

5. Pattern Interrupt
   "This breaks what I expected — forces my attention"
   Example: Calm explanation suddenly followed by shocking fact

6. Middle Class Relatability
   "This is exactly my life — job pressure, family, savings, health"
   Example: Middle class Telugu family struggles, monthly salary tension
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _build_transcript_context(sentences: list, junk_ids: set) -> str:
    lines = ""
    for s in sentences:
        marker = " ⚠JUNK" if s["id"] in junk_ids else ""
        lines += f"  {s['id']} [{s['start']:.1f}s-{s['end']:.1f}s]: {s['text']}{marker}\n"
    return lines


def _get_sentence_text(sentence_id: int, sent_by_id: dict) -> str:
    s = sent_by_id.get(sentence_id)
    return s["text"] if s else ""


def _get_clip_text(start_id: int, end_id: int, sent_by_id: dict) -> str:
    lines = []
    for i in range(start_id, end_id + 1):
        s = sent_by_id.get(i)
        if s:
            lines.append(f"s{i}: {s['text']}")
    return "\n".join(lines)


def _call_tool(prompt: str, client, tracker=None,
               tool_name: str = "tool") -> Optional[dict]:
    """
    Make a cheap focused tool call using flash-lite.
    No thinking. Short output. Structured JSON only.
    """
    try:
        response = client.models.generate_content(
            model=TOOL_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=256,
                response_mime_type="application/json",
            ),
        )

        if tracker:
            tracker.record(response, agent_name=tool_name, call_type="tool")

        # Guard against None response.text
        raw = (response.text or "").strip()
        if not raw:
            print(f"  [Tool:{tool_name}] ⚠ Empty response from model")
            return None

        cleaned = re.sub(r"^```json\s*", "", raw)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        return json.loads(cleaned)

    except json.JSONDecodeError as e:
        print(f"  [Tool:{tool_name}] ⚠ JSON parse error: {e} — raw: {raw[:100]}")
        return None
    except Exception as e:
        print(f"  [Tool:{tool_name}] ⚠ API call failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 1 — cold_open_test
# ═══════════════════════════════════════════════════════════════════════════════

def cold_open_test(sentence_id: int,
                   sentences: list,
                   sent_by_id: dict,
                   junk_ids: set,
                   client,
                   tracker=None) -> dict:
    """
    Simulates a real viewer seeing ONE sentence for the first time
    with zero prior context.

    Tests whether a Telugu viewer scrolling Instagram at 11pm
    would stop at this exact sentence.

    Returns:
        {
          "stops_scrolling": true/false,
          "feeling": "shocked|curious|confused|indifferent|pulled_in",
          "reason": "one sentence why",
          "confidence": 1-10
        }
    """
    sentence_text = _get_sentence_text(sentence_id, sent_by_id)
    if not sentence_text:
        return {"stops_scrolling": False, "feeling": "unknown",
                "reason": "sentence not found", "confidence": 0}

    transcript_context = _build_transcript_context(sentences, junk_ids)

    prompt = f"""You are simulating a Telugu viewer (18-35, urban, middle class) 
scrolling Instagram Reels at 11pm. They are bored and scrolling fast.

Full video transcript for context:
{transcript_context}

THE SENTENCE TO TEST (s{sentence_id}):
"{sentence_text}"

IMPORTANT: The viewer has NOT seen anything before this sentence.
This is the VERY FIRST thing they see. Zero prior context.

Question: If this sentence appears as the opening of a Reel,
does the viewer STOP scrolling or KEEP scrolling?

They stop scrolling only if they immediately feel:
- Shocked ("wait what?")
- Curious ("I need to know more")
- Personally threatened ("this is about me")
- Pulled in ("I can't look away")

They keep scrolling if they feel:
- Confused (no context, can't understand)
- Indifferent (common knowledge, boring)
- Nothing special

Return ONLY valid JSON:
{{
  "stops_scrolling": true,
  "feeling": "shocked|curious|confused|indifferent|pulled_in",
  "reason": "<one sentence why a Telugu viewer would/wouldn't stop>",
  "confidence": 8
}}"""

    result = _call_tool(prompt, client, tracker, tool_name="cold_open_test")

    if result:
        print(f"  [cold_open_test] s{sentence_id}: "
              f"stops={result.get('stops_scrolling')} "
              f"feeling={result.get('feeling')} "
              f"confidence={result.get('confidence')} "
              f"— {result.get('reason', '')[:60]}")

    return result or {"stops_scrolling": False, "feeling": "unknown",
                      "reason": "tool failed", "confidence": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 2 — payoff_strength_test
# ═══════════════════════════════════════════════════════════════════════════════

def payoff_strength_test(hook_id: int,
                         payoff_id: int,
                         sentences: list,
                         sent_by_id: dict,
                         junk_ids: set,
                         client,
                         tracker=None) -> dict:
    """
    Tests whether the payoff sentence satisfactorily resolves
    the tension or curiosity the hook sentence created.

    Returns:
        {
          "satisfied": true/false,
          "tension_resolved": true/false,
          "reason": "one sentence why",
          "confidence": 1-10
        }
    """
    hook_text   = _get_sentence_text(hook_id, sent_by_id)
    payoff_text = _get_sentence_text(payoff_id, sent_by_id)
    clip_text   = _get_clip_text(hook_id, payoff_id, sent_by_id)

    if not hook_text or not payoff_text:
            return {"satisfied": False, "tension_resolved": False,
                    "reason": "sentences not found", "confidence": 0}

    # Single sentence can't have an arc
    if hook_id == payoff_id:
        return {"satisfied": False, "tension_resolved": False,
                "reason": "hook and payoff are the same sentence — no arc possible",
                "confidence": 0}

    transcript_context = _build_transcript_context(sentences, junk_ids)

    prompt = f"""You are evaluating whether a Telugu Reel has a satisfying ending.

Full video transcript for context:
{transcript_context}

THE CLIP:
{clip_text}

HOOK sentence (s{hook_id}) — what made the viewer stop scrolling:
"{hook_text}"

PAYOFF sentence (s{payoff_id}) — the last sentence of the clip:
"{payoff_text}"

A viewer stopped scrolling because of the hook.
They watched the entire clip until the payoff.

Question: Does the payoff SATISFY what the hook promised?

The payoff satisfies if:
- It answers the question the hook raised
- It delivers the consequence the hook threatened
- It resolves the tension the hook created
- The viewer feels "okay I got what I came for"

The payoff fails if:
- It ends mid-thought ("చెప్తాను", "చూద్దాం", "will explain later")
- It redirects to another topic without resolution
- The viewer still feels unresolved after watching
- It ends on a CTA (subscribe, follow, etc.)

Return ONLY valid JSON:
{{
  "satisfied": true,
  "tension_resolved": true,
  "reason": "<one sentence: did the payoff deliver what the hook promised?>",
  "confidence": 8
}}"""

    result = _call_tool(prompt, client, tracker, tool_name="payoff_strength_test")

    if result:
        print(f"  [payoff_strength_test] s{hook_id}→s{payoff_id}: "
              f"satisfied={result.get('satisfied')} "
              f"confidence={result.get('confidence')} "
              f"— {result.get('reason', '')[:60]}")

    return result or {"satisfied": False, "tension_resolved": False,
                      "reason": "tool failed", "confidence": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 3 — psychological_trigger_test
# ═══════════════════════════════════════════════════════════════════════════════

def psychological_trigger_test(start_id: int,
                                end_id: int,
                                sentences: list,
                                sent_by_id: dict,
                                junk_ids: set,
                                client,
                                tracker=None) -> dict:
    """
    Identifies which human psychological trigger the clip activates
    and how strongly for a Telugu 18-35 urban audience.

    Returns:
        {
          "primary_trigger": "Loss Aversion",
          "trigger_strength": 8,
          "secondary_trigger": "Identity Threat",
          "evidence": "one sentence of specific evidence",
          "viral_potential": "high|medium|low"
        }
    """
    clip_text = _get_clip_text(start_id, end_id, sent_by_id)
    if not clip_text:
        return {"primary_trigger": "None", "trigger_strength": 0,
                "secondary_trigger": "None", "evidence": "no content",
                "viral_potential": "low"}

    transcript_context = _build_transcript_context(sentences, junk_ids)

    prompt = f"""You are a viral content analyst specializing in Telugu social media.

Full video transcript for context:
{transcript_context}

THE CLIP TO ANALYZE (s{start_id} to s{end_id}):
{clip_text}

Telugu viral psychological triggers:
{TELUGU_TRIGGERS}

Question: Which psychological trigger does this clip activate most strongly
for a Telugu 18-35 urban middle-class viewer?

Trigger strength scale:
1-3: Barely activates — viewer might notice but won't stop scrolling
4-6: Moderate — viewer pauses but might not watch till end
7-8: Strong — viewer stops and watches
9-10: Exceptional — viewer watches AND shares

Return ONLY valid JSON:
{{
  "primary_trigger": "<one of the 6 triggers above>",
  "trigger_strength": 8,
  "secondary_trigger": "<second strongest trigger or 'None'>",
  "evidence": "<one sentence: specific part of clip that activates the trigger>",
  "viral_potential": "high|medium|low"
}}"""

    result = _call_tool(prompt, client, tracker,
                        tool_name="psychological_trigger_test")

    if result:
        print(f"  [psychological_trigger_test] s{start_id}-s{end_id}: "
              f"trigger={result.get('primary_trigger')} "
              f"strength={result.get('trigger_strength')} "
              f"viral={result.get('viral_potential')} "
              f"— {result.get('evidence', '')[:60]}")

    return result or {"primary_trigger": "None", "trigger_strength": 0,
                      "secondary_trigger": "None",
                      "evidence": "tool failed", "viral_potential": "low"}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 4 — emotional_arc_test
# ═══════════════════════════════════════════════════════════════════════════════

def emotional_arc_test(start_id: int,
                       end_id: int,
                       sentences: list,
                       sent_by_id: dict,
                       junk_ids: set,
                       client,
                       tracker=None) -> dict:
    """
    Checks if the clip has the right emotional shape:
    tension builds → peaks → resolves.

    Returns:
        {
          "arc_valid": true/false,
          "builds_correctly": true/false,
          "peak_sentence_id": 47,
          "resolves_cleanly": true/false,
          "weak_points": [
            {"sentence_id": 45, "issue": "energy drops, repetition"}
          ],
          "confidence": 1-10
        }
    """
    clip_text = _get_clip_text(start_id, end_id, sent_by_id)
    if not clip_text:
            return {"arc_valid": False, "builds_correctly": False,
                    "peak_sentence_id": start_id, "resolves_cleanly": False,
                    "weak_points": [], "confidence": 0}

    # Single sentence can't have an arc
    if end_id <= start_id:
        return {"arc_valid": False, "builds_correctly": False,
                "peak_sentence_id": start_id, "resolves_cleanly": False,
                "weak_points": [{"sentence_id": start_id,
                                 "issue": "single sentence — no arc possible"}],
                "confidence": 0}

    transcript_context = _build_transcript_context(sentences, junk_ids)

    prompt = f"""You are analyzing the emotional shape of a Telugu Reel clip.

Full video transcript for context:
{transcript_context}

THE CLIP (s{start_id} to s{end_id}):
{clip_text}

A good Reel has this emotional shape:
  START: Hook creates tension/curiosity/fear immediately
  MIDDLE: Tension builds — evidence, story, escalation
  END: Payoff resolves the tension — answer, revelation, conclusion

A bad Reel has:
  - Flat energy throughout (no tension build)
  - Energy drops in the middle (viewer loses interest)
  - Unresolved ending (viewer feels cheated)
  - Repetitive middle (same point said multiple ways)

Analyze this clip sentence by sentence.
Identify the peak moment and any weak points.

Return ONLY valid JSON:
{{
  "arc_valid": true,
  "builds_correctly": true,
  "peak_sentence_id": {start_id},
  "resolves_cleanly": true,
  "weak_points": [
    {{"sentence_id": {start_id}, "issue": "describe the problem"}}
  ],
  "confidence": 8
}}

weak_points should be empty array [] if no weak points found.
peak_sentence_id must be a sentence ID within s{start_id} to s{end_id}."""

    result = _call_tool(prompt, client, tracker, tool_name="emotional_arc_test")

    if result:
        weak = result.get("weak_points", [])
        print(f"  [emotional_arc_test] s{start_id}-s{end_id}: "
              f"arc_valid={result.get('arc_valid')} "
              f"builds={result.get('builds_correctly')} "
              f"resolves={result.get('resolves_cleanly')} "
              f"weak_points={len(weak)}")

    return result or {"arc_valid": False, "builds_correctly": False,
                      "peak_sentence_id": start_id, "resolves_cleanly": False,
                      "weak_points": [], "confidence": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 5 — viewer_dropoff_test
# ═══════════════════════════════════════════════════════════════════════════════

def viewer_dropoff_test(start_id: int,
                        end_id: int,
                        sentences: list,
                        sent_by_id: dict,
                        junk_ids: set,
                        client,
                        tracker=None) -> dict:
    """
    Predicts where a real viewer would stop watching and why.

    Returns:
        {
          "would_watch_till_end": true/false,
          "dropoff_sentence_id": null or sentence_id,
          "dropoff_reason": "one sentence why they stopped",
          "retention_score": 1-10
        }
    """
    clip_text = _get_clip_text(start_id, end_id, sent_by_id)
    if not clip_text:
        return {"would_watch_till_end": False,
                "dropoff_sentence_id": start_id,
                "dropoff_reason": "no content", "retention_score": 0}

    transcript_context = _build_transcript_context(sentences, junk_ids)

    prompt = f"""You are a Telugu viewer (25 years old, urban, middle class)
watching a Reel on Instagram. You stopped scrolling because the opening caught
your attention. Now you are watching the rest of the clip.

Full video transcript for context:
{transcript_context}

THE CLIP YOU ARE WATCHING (s{start_id} to s{end_id}):
{clip_text}

Read this clip sentence by sentence AS THE VIEWER.
At each sentence ask yourself: "Do I keep watching or do I swipe away?"

You swipe away when:
- The content becomes repetitive (same point again)
- It gets too technical or boring
- You already got what you came for
- It redirects to unrelated content
- Energy drops and you lose interest

You keep watching when:
- Each sentence adds something new
- Tension keeps building
- You still need the answer to the hook's question
- The content is surprising or relatable

Return ONLY valid JSON:
{{
  "would_watch_till_end": true,
  "dropoff_sentence_id": null,
  "dropoff_reason": "<if dropped: one sentence why. if watched till end: 'watched completely'>",
  "retention_score": 8
}}

dropoff_sentence_id must be null if would_watch_till_end is true.
dropoff_sentence_id must be a sentence ID between {start_id} and {end_id} if false."""

    result = _call_tool(prompt, client, tracker, tool_name="viewer_dropoff_test")

    if result:
        print(f"  [viewer_dropoff_test] s{start_id}-s{end_id}: "
              f"watches_till_end={result.get('would_watch_till_end')} "
              f"retention={result.get('retention_score')} "
              f"dropoff_at=s{result.get('dropoff_sentence_id', 'null')} "
              f"— {result.get('dropoff_reason', '')[:60]}")

    return result or {"would_watch_till_end": False,
                      "dropoff_sentence_id": start_id,
                      "dropoff_reason": "tool failed", "retention_score": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# run_all_tools — convenience runner for full validation on one candidate
# ═══════════════════════════════════════════════════════════════════════════════

def run_all_tools(start_id: int,
                  end_id: int,
                  hook_id: int,
                  payoff_id: int,
                  sentences: list,
                  sent_by_id: dict,
                  junk_ids: set,
                  client,
                  tracker=None) -> dict:
    """
    Runs all 5 tools on one candidate and returns combined evidence dict.
    Used by agents when they want full validation on a candidate.
    """
    print(f"\n  [Tools] Running full validation on s{start_id}-s{end_id} "
          f"(hook=s{hook_id}, payoff=s{payoff_id})...")

    cold_open = cold_open_test(hook_id, sentences, sent_by_id,
                               junk_ids, client, tracker)
    payoff    = payoff_strength_test(hook_id, payoff_id, sentences,
                                     sent_by_id, junk_ids, client, tracker)
    trigger   = psychological_trigger_test(start_id, end_id, sentences,
                                           sent_by_id, junk_ids, client, tracker)
    arc       = emotional_arc_test(start_id, end_id, sentences,
                                   sent_by_id, junk_ids, client, tracker)
    dropoff   = viewer_dropoff_test(start_id, end_id, sentences,
                                    sent_by_id, junk_ids, client, tracker)

    hook_confidence  = cold_open.get("confidence", 0)
    stops_scrolling  = cold_open.get("stops_scrolling", False)
    satisfied        = payoff.get("satisfied", False)
    trigger_strength = trigger.get("trigger_strength", 0)
    arc_valid        = arc.get("arc_valid", False)
    watches_till_end = dropoff.get("would_watch_till_end", False)
    retention        = dropoff.get("retention_score", 0)

    passes_all = (
        stops_scrolling and
        satisfied and
        trigger_strength >= 6 and
        arc_valid and
        watches_till_end
    )

    quality_score = round(
        (hook_confidence  * 0.3 +
         trigger_strength * 0.3 +
         retention        * 0.2 +
         (8 if arc_valid  else 3) * 0.1 +
         (8 if satisfied  else 3) * 0.1),
        1
    )

    print(f"  [Tools] ✓ Validation complete: "
          f"passes_all={passes_all} quality_score={quality_score}/10")

    return {
        "start_id":         start_id,
        "end_id":           end_id,
        "hook_id":          hook_id,
        "payoff_id":        payoff_id,
        "passes_all":       passes_all,
        "quality_score":    quality_score,
        "cold_open":        cold_open,
        "payoff":           payoff,
        "trigger":          trigger,
        "arc":              arc,
        "dropoff":          dropoff,
        "stops_scrolling":  stops_scrolling,
        "satisfied":        satisfied,
        "trigger_strength": trigger_strength,
        "primary_trigger":  trigger.get("primary_trigger", "Unknown"),
        "arc_valid":        arc_valid,
        "weak_points":      arc.get("weak_points", []),
        "watches_till_end": watches_till_end,
        "dropoff_sentence": dropoff.get("dropoff_sentence_id"),
        "retention_score":  retention,
    }