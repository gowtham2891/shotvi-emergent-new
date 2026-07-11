import axios from "axios";
import { client, toApiError, outputFileUrl, pathBasename } from "@/api/client";

// ── Fetchers ─────────────────────────────────────────────────────

// Full transcript JSON for a source video. Sarvam shape:
//   { word_timestamps: [{word, start, end}], sentences: [{id, text, start, end}], ... }
// All times are on the ORIGINAL video's global timeline.
export async function getTranscript(videoId) {
  try {
    const { data } = await client.get(`/transcript/${encodeURIComponent(videoId)}`);
    return data;
  } catch (err) {
    throw toApiError(err, "Transcript not available yet");
  }
}

// xfade segment sidecar written by the pipeline next to *_vertical.mp4 files,
// served by the static /outputs mount. Returns null when the clip has no
// sidecar (single-segment clips, canvas/rerender outputs).
export async function getSegmentSidecar(verticalPath) {
  const base = pathBasename(verticalPath);
  if (!base || !base.includes("_vertical.mp4")) return null;
  const url = outputFileUrl(base.replace("_vertical.mp4", "_vertical_segments.json"));
  try {
    const { data } = await axios.get(url);
    return data; // { segments: [{input_start, input_end, output_start}], total_output_duration }
  } catch {
    return null; // 404 is the normal case for single-segment clips
  }
}

// ── Pure remap helpers (mirror services/caption_renderer.py) ─────
//
// CRITICAL: Telugu word strings are passed through verbatim — never split,
// tokenized, or re-segmented. Backend word boundaries are authoritative.

// caption_renderer.get_words_for_clip: words overlapping [clipStart, clipEnd],
// clamped and shifted to clip-local time.
export function getWordsForRange(transcript, clipStart, clipEnd) {
  let rawWords = transcript?.word_timestamps || [];
  if (!rawWords.length) {
    // Whisper-format fallback: words nested inside segments
    rawWords = (transcript?.segments || []).flatMap((s) => s.words || []);
  }
  const words = [];
  for (const w of rawWords) {
    if (w.end > clipStart && w.start < clipEnd) {
      const text = (w.word ?? w.text ?? "").trim();
      if (!text) continue;
      words.push({
        text,
        start: round3(Math.max(w.start, clipStart) - clipStart),
        end: round3(Math.min(w.end, clipEnd) - clipStart),
      });
    }
  }
  return words;
}

// caption_renderer.get_words_for_multisegment_clip: non-contiguous segments
// (dead zone cut out) are stacked back-to-back on the output timeline.
// clip.segments entries are sentence-id ranges resolved via transcript.sentences.
export function getClipWords(transcript, clip) {
  const segments = clip?.segments || [];
  if (segments.length <= 1) {
    return getWordsForRange(transcript, clip.start, clip.end);
  }
  const sentById = new Map((transcript?.sentences || []).map((s) => [s.id, s]));
  const all = [];
  let outputOffset = 0;
  for (const seg of segments) {
    const sStart = sentById.get(Number(seg.start_sent_id))?.start ?? 0;
    const sEnd = sentById.get(Number(seg.end_sent_id))?.end ?? 0;
    for (const w of getWordsForRange(transcript, sStart, sEnd)) {
      all.push({ text: w.text, start: round3(outputOffset + w.start), end: round3(outputOffset + w.end) });
    }
    outputOffset += sEnd - sStart;
  }
  return all;
}

// caption_renderer remap_time: xfade stitching removes (n-1)*xfade_duration
// seconds, so clip-local times must be remapped onto the sidecar's output
// timeline. No-op when sidecar is null.
export function remapTime(t, sidecar) {
  if (!sidecar?.segments?.length) return t;
  const segs = sidecar.segments;
  for (const seg of segs) {
    if (seg.input_start <= t && t < seg.input_end) {
      return seg.output_start + (t - seg.input_start);
    }
  }
  if (t < segs[0].input_start) return 0.0;
  return sidecar.total_output_duration;
}

export function applySidecarRemap(words, sidecar) {
  if (!sidecar) return words;
  return words.map((w) => ({
    ...w,
    start: round3(remapTime(w.start, sidecar)),
    end: round3(remapTime(w.end, sidecar)),
  }));
}

// One-call convenience: fetch nothing, just combine the pure steps.
export function buildClipTranscript(transcript, clip, sidecar = null) {
  return applySidecarRemap(getClipWords(transcript, clip), sidecar);
}

// A multi-segment clip has a dead zone cut out of the middle, so the actual
// (stitched) video is shorter than its full source span. We can DETECT this
// from ClipOut alone — duration (sum of kept segments) < end-start (full
// span) — even when we can't correctly REMAP it (that needs the segment
// sentence-id ranges, which ClipOut does not yet expose).
const MULTI_SEGMENT_GAP_TOLERANCE_S = 0.75;

export function isMultiSegmentClip(clip) {
  if ((clip?.segments?.length || 0) > 1) return true;
  const span = (clip?.end ?? 0) - (clip?.start ?? 0);
  const dur = clip?.duration ?? span;
  return span - dur > MULTI_SEGMENT_GAP_TOLERANCE_S;
}

// True only when we actually have the segment ranges needed to remap.
export function canRemapMultiSegment(clip) {
  return (clip?.segments?.length || 0) > 1;
}

const round3 = (n) => Math.round(n * 1000) / 1000;
