import { create } from "zustand";
import { toast } from "sonner";
import {
  PROJECTS as MOCK_PROJECTS,
  getClipsForProject as getMockClips,
  WORD_TRANSCRIPT,
  CLIP_DURATION,
  CAPTION_PRESETS,
  INITIAL_ELEMENTS,
  PILL_DEFAULTS_BY_PRESET,
} from "@/data/mockData";
import { USE_MOCKS, outputFileUrl } from "@/api/client";
import { createJobFromUrl, createJobFromFile, getJob } from "@/api/uploads";
import { mapClipToUi, saveDraft, loadDraft, generateClipMetadata } from "@/api/clips";
import {
  getTranscript,
  getSegmentSidecar,
  buildClipTranscript,
  isMultiSegmentClip,
  canRemapMultiSegment,
} from "@/api/transcripts";
import { buildRerenderRequest, startRerender, DEFAULT_STYLE_ID, isKnownStyle } from "@/api/renders";
import {
  listProjects as registryList,
  upsertProject as registryUpsert,
  removeProject as registryRemove,
  getProjectEntry,
} from "@/lib/projectRegistry";
import { assertEditDocumentNormalized } from "@/lib/editDocumentValidation";

// Utility: clamp
const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

let elementIdCounter = 100;
const nextElementId = (type) => `el_${type}_${++elementIdCounter}`;

// JobStatus (backend enum) → dashboard project status keys (STATUS_META)
const JOB_TO_PROJECT_STATUS = {
  pending: "uploading",
  downloading: "uploading",
  transcribing: "transcribing",
  selecting: "selecting_clips",
  cutting: "selecting_clips",
  cropping: "selecting_clips",
  captioning: "selecting_clips",
  done: "ready",
  failed: "failed",
};

const timeAgo = (ts) => {
  if (!ts) return "";
  const mins = Math.floor((Date.now() - ts) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hour${hrs > 1 ? "s" : ""} ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
};

// JobOut + registry entry → dashboard project card shape
function jobToProject(job, entry) {
  const firstClip = job.clips?.[0];
  return {
    id: job.job_id,
    title: entry?.title || job.video_id || `Job ${job.job_id.slice(0, 8)}`,
    thumbnail: firstClip ? mapClipToUi(firstClip, 0, job.job_id).thumbnail : null,
    duration: "",
    createdAt: timeAgo(entry?.createdAt),
    status: JOB_TO_PROJECT_STATUS[job.status] || "uploading",
    progress: job.progress,
    clipsCount: job.clips?.length || 0,
    language: entry?.language || "te",
    videoId: job.video_id || entry?.videoId || null,
    error: job.error || null,
    currentStage: job.current_stage || "",
  };
}

const surfaceError = (err, fallback) => {
  const msg = err?.message || fallback;
  toast.error(msg);
  return msg;
};

export const useAppStore = create((set, get) => ({
  // ============ AUTH (mocked sign-in stays as-is) ============
  user: null,
  signIn: (email) =>
    set({
      user: {
        email: email || "creator@shotvi.app",
        name: (email || "Rahul K").split("@")[0],
        plan: "Creator",
      },
    }),
  signOut: () => set({ user: null }),

  // ============ PROJECTS (localStorage registry + GET /jobs/{id}) ============
  projects: USE_MOCKS ? MOCK_PROJECTS : [],
  projectsLoading: false,
  currentProjectId: null,
  setCurrentProject: (id) => set({ currentProjectId: id }),
  getProject: (id) => get().projects.find((p) => p.id === id),
  addProject: (project) => set((s) => ({ projects: [project, ...s.projects] })),

  // Hydrate the dashboard: each registry entry → GET /jobs/{id}.
  // 404 = expired (24h Redis TTL) — shown, not silently dropped.
  loadProjects: async () => {
    if (USE_MOCKS) {
      set({ projects: MOCK_PROJECTS, projectsLoading: false });
      return;
    }
    set({ projectsLoading: true });
    const entries = registryList();
    const projects = await Promise.all(
      entries.map(async (entry) => {
        try {
          const job = await getJob(entry.jobId);
          if (job.video_id && job.video_id !== entry.videoId) {
            registryUpsert({ jobId: entry.jobId, videoId: job.video_id });
          }
          return jobToProject(job, entry);
        } catch (err) {
          return {
            id: entry.jobId,
            title: entry.title || entry.jobId.slice(0, 8),
            thumbnail: null,
            duration: "",
            createdAt: timeAgo(entry.createdAt),
            status: err.status === 404 ? "expired" : "failed",
            clipsCount: 0,
            language: entry.language || "te",
            videoId: entry.videoId || null,
            error: err.status === 404 ? "Job expired — jobs are kept for 24 hours" : err.message,
          };
        }
      })
    );
    set({ projects, projectsLoading: false });
  },

  removeProjectEntry: (jobId) => {
    registryRemove(jobId);
    set((s) => ({ projects: s.projects.filter((p) => p.id !== jobId) }));
  },

  // ============ JOB SUBMISSION (Upload page) ============
  // The Upload page drives live progress via useJobPolling(activeJobId).
  activeJobId: null,
  activeJob: null,
  uploadPercent: 0, // browser→server transfer (axios), not pipeline progress
  submitError: null,

  submitYouTubeUrl: async ({ url, language }) => {
    set({ submitError: null, uploadPercent: 100 });
    try {
      const job = await createJobFromUrl({ url, language });
      registryUpsert({
        jobId: job.job_id,
        title: `YouTube import ${job.video_id || ""}`.trim(),
        language,
        source: "youtube",
        url,
        videoId: job.video_id || null,
      });
      set({ activeJobId: job.job_id, activeJob: job });
      return job;
    } catch (err) {
      set({ submitError: surfaceError(err, "Could not submit the YouTube URL") });
      throw err;
    }
  },

  submitFile: async ({ file, language }) => {
    set({ submitError: null, uploadPercent: 0 });
    try {
      const job = await createJobFromFile({
        file,
        language,
        onUploadProgress: (e) => {
          if (e.total) set({ uploadPercent: Math.round((e.loaded / e.total) * 100) });
        },
      });
      registryUpsert({
        jobId: job.job_id,
        title: file.name,
        language,
        source: "upload",
        videoId: job.video_id || null,
      });
      set({ activeJobId: job.job_id, activeJob: job, uploadPercent: 100 });
      return job;
    } catch (err) {
      set({ submitError: surfaceError(err, "Upload failed") });
      throw err;
    }
  },

  // Poll callback: keep activeJob + the matching project card fresh
  applyJobUpdate: (job) => {
    set((s) => ({
      activeJob: s.activeJobId === job.job_id ? job : s.activeJob,
      projects: s.projects.map((p) =>
        p.id === job.job_id ? jobToProject(job, getProjectEntry(job.job_id)) : p
      ),
    }));
    if (job.status === "done") {
      const entry = getProjectEntry(job.job_id);
      if (entry && job.video_id && entry.videoId !== job.video_id) {
        registryUpsert({ jobId: job.job_id, videoId: job.video_id });
      }
      get().cacheJobClips(job);
    }
  },

  resetSubmission: () =>
    set({ activeJobId: null, activeJob: null, uploadPercent: 0, submitError: null }),

  // ============ CLIPS (per job) ============
  clipsByJob: {}, // jobId → [uiClip]
  clipsLoading: false,
  clipsError: null,
  currentJobId: null,

  cacheJobClips: (job) => {
    if (!job.clips?.length) return;
    set((s) => ({
      clipsByJob: {
        ...s.clipsByJob,
        [job.job_id]: job.clips.map((c, i) => mapClipToUi(c, i, job.job_id)),
      },
    }));
  },

  // Load a project's clips for the gallery (and cache the job meta)
  loadProjectClips: async (jobId) => {
    if (USE_MOCKS) {
      set((s) => ({
        currentJobId: jobId,
        clipsByJob: { ...s.clipsByJob, [jobId]: getMockClips(jobId) },
      }));
      return;
    }
    set({ clipsLoading: true, clipsError: null, currentJobId: jobId });
    try {
      const job = await getJob(jobId);
      get().cacheJobClips(job);
      set((s) => ({
        clipsLoading: false,
        projects: s.projects.some((p) => p.id === jobId)
          ? s.projects.map((p) => (p.id === jobId ? jobToProject(job, getProjectEntry(jobId)) : p))
          : [jobToProject(job, getProjectEntry(jobId)), ...s.projects],
      }));
    } catch (err) {
      set({
        clipsLoading: false,
        clipsError:
          err.status === 404
            ? "This project has expired (jobs are kept for 24 hours). Re-submit the video to regenerate clips."
            : surfaceError(err, "Could not load clips"),
      });
    }
  },

  getClips: (jobId) => get().clipsByJob[jobId] || [],

  // ============ EDITOR — CURRENT CLIP ============
  currentClipId: USE_MOCKS ? "clip_001" : null,
  currentClip: null,
  setCurrentClip: (id) => set({ currentClipId: id }),

  // Resolve a clip id to its clip + job (deep links: /editor/:clipId).
  // Checks loaded jobs first, then hydrates registry jobs (videoId prefix
  // match narrows the search — clip ids are `${video_id}_c${n}`).
  resolveClip: async (clipId) => {
    const { clipsByJob } = get();
    for (const [jobId, clips] of Object.entries(clipsByJob)) {
      const hit = clips.find((c) => c.id === clipId);
      if (hit) return { clip: hit, jobId };
    }
    if (USE_MOCKS) return null;
    const entries = registryList();
    const ranked = [
      ...entries.filter((e) => e.videoId && clipId.startsWith(e.videoId)),
      ...entries.filter((e) => !e.videoId || !clipId.startsWith(e.videoId)),
    ];
    for (const entry of ranked) {
      try {
        const job = await getJob(entry.jobId);
        if (!job.clips?.length) continue;
        get().cacheJobClips(job);
        const clips = job.clips.map((c, i) => mapClipToUi(c, i, job.job_id));
        const hit = clips.find((c) => c.id === clipId);
        if (hit) return { clip: hit, jobId: job.job_id };
      } catch {
        // expired/unreachable entry — keep searching
      }
    }
    return null;
  },

  // Open a clip in the editor: resolve it, load its Telugu word-level
  // transcript (backend word boundaries are authoritative — rendered
  // verbatim), and restore any saved draft.
  openClip: async (clipId) => {
    if (USE_MOCKS) {
      set({
        currentClipId: clipId,
        transcript: WORD_TRANSCRIPT,
        duration: CLIP_DURATION,
        transcriptStatus: "ready",
      });
      return;
    }
    set({
      currentClipId: clipId,
      currentClip: null,
      transcript: [],
      transcriptStatus: "loading",
      transcriptError: null,
      transcriptWarning: null,
      exportWarnings: [],
    });
    const found = await get().resolveClip(clipId);
    if (!found) {
      set({
        transcriptStatus: "error",
        transcriptError: "Clip not found — the job may have expired (24h retention).",
      });
      return;
    }
    const { clip, jobId } = found;
    set({ currentClip: clip, currentJobId: jobId, duration: clip.end - clip.start });

    try {
      const project = get().projects.find((p) => p.id === jobId);
      const videoId = project?.videoId || getProjectEntry(jobId)?.videoId;
      if (!videoId) throw new Error("No video id on this job — cannot load transcript");

      const transcript = await getTranscript(videoId);
      // Sidecar is legacy-defensive: nothing currently writes it; multi-segment
      // clips are plain concat, so sentence-time stacking matches the video.
      const sidecar = await getSegmentSidecar(clip.verticalPath);
      const words = buildClipTranscript(transcript, clip, sidecar);
      const duration = words.length ? Math.max(clip.duration || 0, words[words.length - 1].end) : clip.duration;

      // Multi-segment safety net: if a dead zone was cut out but ClipOut did
      // not carry the segment ranges, getClipWords falls back to the full
      // span — which would include the cut region and drift every word after
      // it. Detect that case and warn rather than show a silently-wrong
      // overlay. (Correct remap kicks in automatically once segments arrive.)
      let transcriptWarning = null;
      if (isMultiSegmentClip(clip) && !canRemapMultiSegment(clip)) {
        transcriptWarning =
          "This clip is stitched from multiple segments (a section was cut out). " +
          "Word-level caption timing may be misaligned in the editor until multi-segment " +
          "transcript support is enabled on the backend. Playback and export are unaffected.";
      }
      set({ transcript: words, transcriptStatus: "ready", duration, transcriptWarning });
    } catch (err) {
      set({
        transcriptStatus: "error",
        transcriptError: err.message,
      });
      surfaceError(err, "Could not load the transcript");
    }

    // Restore draft (non-fatal if it fails)
    try {
      const draft = await loadDraft(jobId, clipId);
      if (draft?.elements?.length) {
        set({ elements: draft.elements });
      }
      if (draft?.exportSettings) {
        set((s) => ({ exportSettings: { ...s.exportSettings, ...draft.exportSettings } }));
      }
    } catch {
      // draft restore is best-effort
    }
  },

  retryTranscript: () => {
    const id = get().currentClipId;
    if (id) get().openClip(id);
  },

  // ============ TRANSCRIPT ============
  transcript: USE_MOCKS ? WORD_TRANSCRIPT : [],
  transcriptStatus: USE_MOCKS ? "ready" : "idle", // idle|loading|ready|error
  transcriptError: null,
  transcriptWarning: null, // multi-segment alignment caveat (see openClip)
  getActiveWordIndex: () => {
    const t = get().currentTime;
    return get().transcript.findIndex((w) => t >= w.start && t < w.end);
  },

  // ============ PLAYBACK ============
  isPlaying: false,
  togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
  setPlaying: (v) => set({ isPlaying: v }),
  currentTime: 0,
  duration: USE_MOCKS ? CLIP_DURATION : 0,
  seek: (t) => set({ currentTime: clamp(t, 0, get().duration) }),
  setDuration: (d) => set({ duration: d }),

  // ============ DRAFTS (PATCH/GET /jobs/{job}/clips/{clip}/draft) ============
  draftStatus: "idle", // idle|saving|saved|error
  saveDraftNow: async () => {
    const s = get();
    if (USE_MOCKS || !s.currentClip) return;
    set({ draftStatus: "saving" });
    try {
      await saveDraft(s.currentJobId, s.currentClipId, s.getEditDocument());
      set({ draftStatus: "saved" });
    } catch (err) {
      set({ draftStatus: "error" });
      surfaceError(err, "Could not save draft");
    }
  },

  // ============ EDIT DOCUMENT ============
  // The canonical outgoing payload (drafts + export). COORDINATES STAY
  // NORMALIZED 0–1 end-to-end — never pixels. The only unit conversion in
  // the entire frontend is caption_position (0–1 → percent) inside
  // buildRerenderRequest, per the backend's documented contract.
  getEditDocument: () => {
    const s = get();
    const caption = s.getCaptionElement();
    return {
      version: 1,
      clipId: s.currentClipId,
      elements: s.elements.map((el) => ({ ...el, props: { ...el.props } })),
      exportSettings: { ...s.exportSettings },
      style: caption?.props?.presetId || DEFAULT_STYLE_ID,
      captionX: caption ? caption.x : 0.5,
      captionY: caption ? caption.y : 0.82,
      // BUG-001 partial fix: expose the caption's fontSize (0–1 canvas
      // fraction — same units the preview scales by) and pill so they can
      // reach the burn. Nulls when there is no caption element so the
      // backend can fall back to preset defaults; otherwise straight
      // pass-through of the Inspector state.
      captionFontSize: caption?.props?.fontSize ?? null,
      captionPill: caption?.props?.pill ?? null,
    };
  },

  // ============ EXPORT ============
  exportSettings: {
    format: "9:16", // FORMAT_CONFIG keys in api/worker.py
    background: "blur", // blur | black | white | color
    bgColor: "#000000",
    useAutocrop: true,
    burnInCaptions: true,
  },
  setExportSetting: (key, val) =>
    set((s) => ({ exportSettings: { ...s.exportSettings, [key]: val } })),

  exportJobId: null,
  exportStatus: "idle", // idle|submitting|rendering|done|failed
  exportJob: null,
  exportError: null,
  exportWarnings: [],
  exportResultPath: null, // server path of the rendered file (for /clips/download)
  exportTargetClipId: null, // which clip this export is for — so applyExportUpdate knows what to refresh

  startExport: async (clip) => {
    const s = get();
    const target = clip || s.currentClip;
    if (!target) {
      toast.error("No clip selected to export");
      return null;
    }
    set({
      exportStatus: "submitting",
      exportError: null,
      exportResultPath: null,
      exportWarnings: [],
      exportTargetClipId: target.id,
    });
    const doc = s.getEditDocument();
    try {
      // Pixel-consistency invariant: refuse to export a document that has
      // drifted from normalized 0–1 coordinates.
      assertEditDocumentNormalized(doc);
    } catch (err) {
      set({ exportStatus: "failed", exportError: err.message });
      toast.error(err.message);
      return null;
    }
    const req = buildRerenderRequest({
      style: doc.style,
      format: s.exportSettings.format,
      background: s.exportSettings.background,
      bgColor: s.exportSettings.bgColor,
      useAutocrop: s.exportSettings.useAutocrop,
      captionX: doc.captionX,
      captionY: doc.captionY,
      // BUG-001 partial fix — thread the caption Size + Background Pill.
      captionFontSize: doc.captionFontSize,
      captionPill: doc.captionPill,
      elements: doc.elements,
    });
    try {
      const rerenderJobId = await startRerender(target.jobId, target.index, req);
      set({ exportJobId: rerenderJobId, exportStatus: "rendering", exportJob: null });
      return rerenderJobId;
    } catch (err) {
      set({ exportStatus: "failed", exportError: surfaceError(err, "Could not start the export") });
      return null;
    }
  },

  // Poll callback for the export rerender job
  applyExportUpdate: (job) => {
    const patch = { exportJob: job };
    if (job.status === "done") {
      patch.exportStatus = "done";
      patch.exportResultPath = job.captioned_path || job.vertical_path || null;
      patch.exportWarnings = job.warnings || [];
      if (job.warnings?.includes("transcript_edits_skipped_multi_segment")) {
        toast.warning(
          "Caption line merges/splits were skipped: this clip is stitched from multiple segments and the backend cannot apply them yet."
        );
      }
    } else if (job.status === "failed") {
      patch.exportStatus = "failed";
      patch.exportError = job.error || "Render failed";
      toast.error(`Export failed: ${job.error || "unknown error"}`);
    }

    set((s) => {
      if (job.status !== "done" || !s.exportTargetClipId) return patch;

      // Root cause of "preview shows stale video": the clip's previewUrl was
      // computed once from the ORIGINAL pipeline ClipOut and never refreshed
      // after a rerender — the export page read that same clip object, so it
      // never saw the newly rendered file. Refresh previewUrl here so every
      // consumer picks it up.
      //
      // Also cache-busted: the backend derives rerender output filenames
      // deterministically from export settings (format/background/style),
      // so re-exporting with identical settings overwrites the same path —
      // same URL, browser serves the cached old video without this.
      //
      // Editor canvas bug fix (return-from-export "double sticker"): the
      // editor's `videoUrl` MUST stay pointed at the pipeline's ORIGINAL
      // raw 9:16 crop (no overlays, no captions burned in). The rerender's
      // `job.vertical_path` is the POST-overlay pre-caption composite, so
      // refreshing `videoUrl` to it meant the editor canvas showed the
      // sticker/progress-bar/logo TWICE — once burned into the pixels of
      // the video the browser played, once as the live overlay element on
      // top. Only refresh previewUrl (used by the Export page's captioned
      // preview) + captionedPath/verticalPath (path bookkeeping for the
      // download endpoint); videoUrl stays immutable across rerenders.
      const bust = job.job_id;
      const newPreviewUrl = outputFileUrl(job.captioned_path || job.vertical_path || null);
      const bustedPreview = newPreviewUrl ? `${newPreviewUrl}?v=${bust}` : undefined;

      const refreshClip = (c) =>
        c.id === s.exportTargetClipId
          ? {
              ...c,
              captionedPath: job.captioned_path || c.captionedPath,
              verticalPath: job.vertical_path || c.verticalPath,
              previewUrl: bustedPreview || c.previewUrl,
              // videoUrl intentionally NOT refreshed — see comment above.
            }
          : c;

      return {
        ...patch,
        currentClip: s.currentClip ? refreshClip(s.currentClip) : s.currentClip,
        clipsByJob: Object.fromEntries(
          Object.entries(s.clipsByJob).map(([jobId, clips]) => [jobId, clips.map(refreshClip)])
        ),
      };
    });
  },

  failExport: (message) => set({ exportStatus: "failed", exportError: message }),
  resetExport: () =>
    set({
      exportJobId: null,
      exportStatus: "idle",
      exportJob: null,
      exportError: null,
      exportWarnings: [],
      exportResultPath: null,
      exportTargetClipId: null,
    }),

  // ============ METADATA (AI title/description/hashtags) ============
  clipMetadata: null,
  metadataStatus: "idle",
  generateMetadata: async (clip) => {
    const s = get();
    const target = clip || s.currentClip;
    if (!target || USE_MOCKS) return;
    const text = s.transcript.map((w) => w.text).join(" ");
    if (!text) return;
    set({ metadataStatus: "loading" });
    try {
      const meta = await generateClipMetadata(target.jobId, target.index, text);
      set({ clipMetadata: meta, metadataStatus: "ready" });
    } catch (err) {
      set({ metadataStatus: "error" });
      surfaceError(err, "Metadata generation failed");
    }
  },

  // ============ CANVAS ELEMENTS ============
  elements: INITIAL_ELEMENTS,
  selectedElementId: "el_caption_1",

  setSelected: (id) => set({ selectedElementId: id }),
  clearSelection: () => set({ selectedElementId: null }),

  // BUG-005 containment: keep `rotation` at 0 for element types whose
  // rotation the export path cannot render yet (progress). This is a UI-only
  // guard — the composite filtergraph is unchanged. When rotation is wired
  // through the composite path, drop the type from this Set.
  //
  // Applied at the store boundary (not just the TransformBox UI) so keyboard
  // nudges, mock data, and any future callers all funnel through here.

  updateElement: (id, patch) =>
    set((s) => ({
      elements: s.elements.map((el) => {
        if (el.id !== id) return el;
        const next = { ...el, ...patch };
        if (ROTATION_LOCKED_TYPES.has(next.type)) next.rotation = 0;
        return next;
      }),
    })),

  updateElementProps: (id, propsPatch) =>
    set((s) => ({
      elements: s.elements.map((el) =>
        el.id === id ? { ...el, props: { ...el.props, ...propsPatch } } : el
      ),
    })),

  addElement: (type, overrides = {}) => {
    const defaults = defaultElementForType(type);
    const el = { ...defaults, ...overrides, id: nextElementId(type) };
    set((s) => ({
      elements: [...s.elements, el],
      selectedElementId: el.id,
    }));
    return el.id;
  },

  removeElement: (id) =>
    set((s) => ({
      elements: s.elements.filter((el) => el.id !== id),
      selectedElementId:
        s.selectedElementId === id ? null : s.selectedElementId,
    })),

  toggleElementVisibility: (id) =>
    set((s) => ({
      elements: s.elements.map((el) =>
        el.id === id ? { ...el, visible: !el.visible } : el
      ),
    })),

  bringForward: (id) =>
    set((s) => {
      const idx = s.elements.findIndex((el) => el.id === id);
      if (idx === -1 || idx === s.elements.length - 1) return s;
      const next = [...s.elements];
      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      return { elements: next };
    }),
  sendBackward: (id) =>
    set((s) => {
      const idx = s.elements.findIndex((el) => el.id === id);
      if (idx <= 0) return s;
      const next = [...s.elements];
      [next[idx], next[idx - 1]] = [next[idx - 1], next[idx]];
      return { elements: next };
    }),

  // Element convenience getters
  getElement: (id) => get().elements.find((el) => el.id === id),
  getCaptionElement: () =>
    get().elements.find((el) => el.type === "caption"),

  // ============ CAPTION PRESET SHORTCUTS ============
  // These act on the current caption element for backwards compat.
  setCaptionPreset: (presetId) => {
    const caption = get().getCaptionElement();
    if (!caption) return;
    const pillDefaults = PILL_DEFAULTS_BY_PRESET[presetId] || {};
    get().updateElementProps(caption.id, {
      presetId,
      pill: { ...caption.props.pill, ...pillDefaults },
    });
  },
  getPresetClass: () => {
    const caption = get().getCaptionElement();
    const id = caption?.props?.presetId;
    // Backend style ids map to preview CSS classes (caption-<id> in
    // index.css); legacy mock preset ids keep working via CAPTION_PRESETS.
    if (isKnownStyle(id)) return `caption-${id}`;
    return (
      CAPTION_PRESETS.find((p) => p.id === id)?.className ||
      "caption-clean-white"
    );
  },

  // ============ POSITION PRESETS (for the selected element) ============
  applyPositionPreset: (name) => {
    const id = get().selectedElementId;
    if (!id) return;
    let x = 0.5,
      y = 0.5;
    switch (name) {
      case "top":
        y = 0.08;
        break;
      case "center":
        y = 0.5;
        break;
      case "lower-third":
        y = 0.66;
        break;
      case "bottom-safe":
        y = 0.78; // above the bottom-20% safe-zone
        break;
      default:
        break;
    }
    get().updateElement(id, { x, y });
  },

  // ============ SAFE ZONES ============
  safeZoneMode: "off", // 'off' | 'instagram' | 'youtube'
  setSafeZoneMode: (m) => set({ safeZoneMode: m }),

  // ============ SMART GUIDES (during drag) ============
  activeGuides: { vertical: [], horizontal: [] },
  setActiveGuides: (g) => set({ activeGuides: g }),

  // ============ CANVAS ZOOM & PAN ============
  canvasZoom: 1,
  setCanvasZoom: (z) => set({ canvasZoom: clamp(z, 0.4, 3) }),
  zoomIn: () => set((s) => ({ canvasZoom: clamp(s.canvasZoom + 0.1, 0.4, 3) })),
  zoomOut: () => set((s) => ({ canvasZoom: clamp(s.canvasZoom - 0.1, 0.4, 3) })),
  // CanvasArea owns the actual viewport measurement (it holds the DOM ref);
  // bumping this counter is how the toolbar's "Fit" button asks it to
  // recompute, without coupling the store to the DOM.
  fitRequestId: 0,
  fitScreen: () => set((s) => ({ fitRequestId: s.fitRequestId + 1 })),
  canvasPan: { x: 0, y: 0 },
  setCanvasPan: (p) => set({ canvasPan: p }),

  // ============ MUSIC ============
  selectedTrackId: null,
  setSelectedTrack: (id) => set({ selectedTrackId: id }),
  musicVolume: 40,
  setMusicVolume: (v) => set({ musicVolume: v }),
}));

// -----------------------------------------------------------------
// Element type factory — defaults per type
// -----------------------------------------------------------------

// BUG-005 containment: element types whose editor rotation the export path
// cannot render yet. Store-level guard: any updateElement patch on these
// types silently coerces `rotation` to 0. Progress bar has computed-but-
// unapplied rotation in services/overlay_renderer.py.
const ROTATION_LOCKED_TYPES = new Set(["progress"]);

function defaultElementForType(type) {
  const base = {
    x: 0.5,
    y: 0.5,
    scale: 1,
    rotation: 0,
    visible: true,
    locked: false,
    props: {},
  };
  switch (type) {
    case "caption":
      return {
        ...base,
        type: "caption",
        y: 0.82,
        props: {
          presetId: "bold-yellow",
          font: "Outfit",
          fontSize: 0.055, // fraction of canvas height
          animation: "karaoke", // 'none'|'pop'|'fade'|'bounce'|'karaoke'
          pill: {
            enabled: false,
            color: "#000000",
            opacity: 0.55,
            padding: 8,
            radius: 8,
          },
        },
      };
    case "headline":
      return {
        ...base,
        type: "headline",
        y: 0.14,
        props: {
          text: "94 · VIRAL",
          font: "Outfit",
          fontSize: 0.06,
          color: "#22ff9c",
          weight: 900,
          italic: false,
          uppercase: true,
          stroke: true,
        },
      };
    case "progress":
      return {
        ...base,
        type: "progress",
        y: 0.965,
        props: {
          color: "#7c3aed",
          width: 0.92,
          height: 0.006,
        },
      };
    case "logo":
      return {
        ...base,
        type: "logo",
        x: 0.16,
        y: 0.07,
        props: {
          text: "@rahul_creator",
          avatar: "R",
          font: "Manrope",
          fontSize: 0.02,
        },
      };
    case "sticker":
      return {
        ...base,
        type: "sticker",
        x: 0.78,
        y: 0.6,
        rotation: -12,
        props: {
          emoji: "🔥",
          fontSize: 0.13,
        },
      };
    default:
      return base;
  }
}

export { clamp };
