import { client, toApiError, outputFileUrl, thumbnailFileUrl, downloadFileUrl } from "@/api/client";

// ── ClipOut → UI shape ───────────────────────────────────────────

const pad2 = (n) => String(n).padStart(2, "0");

export function formatTimecode(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0 ? `${h}:${pad2(m)}:${pad2(sec)}` : `${m}:${pad2(sec)}`;
}

// Map a backend ClipOut (api/models.py) onto the shape the gallery/editor
// components render. Keeps the raw backend paths around — the export flow
// needs them verbatim (download endpoint takes full server paths).
export function mapClipToUi(clipOut, index, jobId) {
  return {
    id: clipOut.clip_id,
    index, // clip_index for rerender/metadata endpoints
    jobId,
    hook: clipOut.hook_text || "",
    hookEn: clipOut.why || "",
    engagementType: clipOut.engagement_type || "",
    virality: Math.round(clipOut.virality_score || 0),
    rank: clipOut.rank,
    duration: Math.round(clipOut.duration || 0),
    start: clipOut.start,
    end: clipOut.end,
    // Sentence-id ranges for multi-segment clips (dead zone cut out of the
    // middle). Required for correct clip-local transcript remap. Empty until
    // the backend exposes segments on ClipOut — see proposed diff.
    segments: clipOut.segments || [],
    startAt: formatTimecode(clipOut.start),
    thumbnail: thumbnailFileUrl(clipOut.thumbnail_path),
    // Playable URLs via the static /outputs mount
    previewUrl: outputFileUrl(clipOut.captioned_path || clipOut.vertical_path || clipOut.raw_path),
    videoUrl: outputFileUrl(clipOut.vertical_path || clipOut.raw_path),
    // Raw server paths (needed for download + sidecar lookup)
    rawPath: clipOut.raw_path || "",
    verticalPath: clipOut.vertical_path || "",
    captionedPath: clipOut.captioned_path || "",
  };
}

export const clipDownloadUrl = (serverPath) => downloadFileUrl(serverPath);

// ── Editor drafts (7-day Redis TTL server-side) ──────────────────

export async function saveDraft(jobId, clipId, draft) {
  try {
    const { data } = await client.patch(
      `/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(clipId)}/draft`,
      draft
    );
    return data;
  } catch (err) {
    throw toApiError(err, "Could not save draft");
  }
}

export async function loadDraft(jobId, clipId) {
  try {
    const { data } = await client.get(
      `/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(clipId)}/draft`
    );
    return data?.draft ?? null;
  } catch (err) {
    throw toApiError(err, "Could not load draft");
  }
}

// ── AI metadata (title / description / hashtags) ─────────────────

export async function generateClipMetadata(jobId, clipIndex, transcriptText) {
  try {
    const { data } = await client.post(
      `/jobs/${encodeURIComponent(jobId)}/clips/${clipIndex}/metadata`,
      { transcript_text: transcriptText }
    );
    return data; // { title, description, hashtags[] }
  } catch (err) {
    throw toApiError(err, "Metadata generation failed");
  }
}
