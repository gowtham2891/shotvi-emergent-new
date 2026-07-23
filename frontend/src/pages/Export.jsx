import React, { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  Download,
  Sparkles,
  Loader2,
  FileVideo,
  Ratio,
  Type as TypeIcon,
  Share2,
  Instagram,
  Youtube,
  AlertTriangle,
  RotateCcw,
  Palette,
  Wand2,
  Copy,
} from "lucide-react";
import { AppShell } from "@/components/shotvi/AppShell";
import { useAppStore } from "@/store/useAppStore";
import { useJobPolling } from "@/hooks/useJobPolling";
import { USE_MOCKS } from "@/api/client";
import { downloadClip } from "@/api/clips";
import { toast } from "sonner";
import { BACKGROUND_OPTIONS } from "@/api/renders";
import { EXPORT } from "@/constants/testIds";
import { getClipsForProject } from "@/data/mockData";
import { StaticElementLayer } from "@/components/editor/StaticElementLayer";
import {
  OUTPUT_ASPECTS,
  inferMasterAspect,
  initialWindowForAspect,
  cropVideoLayout,
} from "@/lib/cropWindow";

const ASPECTS = [
  { v: "9:16", label: "Vertical", desc: "Reels, Shorts, TikTok" },
  { v: "1:1", label: "Square", desc: "Instagram Feed" },
  { v: "16:9", label: "Landscape", desc: "YouTube" },
];

// Backend renders mp4 only, at fixed 1080-based canvas sizes per aspect —
// resolution and container pickers are shown but disabled (not faked).
const RESOLUTIONS = [
  { v: "1080p", label: "1080p Full HD", note: "Fixed by render pipeline" },
];
const DISABLED_FORMATS = ["mov", "webm"];

export default function Export() {
  const { clipId } = useParams();
  const navigate = useNavigate();

  const currentClip = useAppStore((s) => s.currentClip);
  const openClip = useAppStore((s) => s.openClip);
  const exportSettings = useAppStore((s) => s.exportSettings);
  const setExportSetting = useAppStore((s) => s.setExportSetting);
  const startExport = useAppStore((s) => s.startExport);
  const exportStatus = useAppStore((s) => s.exportStatus);
  const exportJobId = useAppStore((s) => s.exportJobId);
  const exportJob = useAppStore((s) => s.exportJob);
  const exportError = useAppStore((s) => s.exportError);
  const exportWarnings = useAppStore((s) => s.exportWarnings);
  const exportResultPath = useAppStore((s) => s.exportResultPath);
  const applyExportUpdate = useAppStore((s) => s.applyExportUpdate);
  const failExport = useAppStore((s) => s.failExport);
  const resetExport = useAppStore((s) => s.resetExport);
  const getEditDocument = useAppStore((s) => s.getEditDocument);
  const clipMetadata = useAppStore((s) => s.clipMetadata);
  const metadataStatus = useAppStore((s) => s.metadataStatus);
  const generateMetadata = useAppStore((s) => s.generateMetadata);

  const [clip, setClip] = useState(null);
  const [mockProgress, setMockProgress] = useState(0);
  const [mockStatus, setMockStatus] = useState("idle");

  // Measures the actual rendered preview box height so StaticElementLayer's
  // font sizes (fraction-of-canvas-height, same convention as the editor
  // canvas) scale correctly — the box is aspect-ratio-driven (Tailwind
  // aspect-[9/16]), not a fixed pixel size like the editor's 360x640 stage.
  const previewBoxRef = useRef(null);
  const [canvasH, setCanvasH] = useState(640);
  useEffect(() => {
    const el = previewBoxRef.current;
    if (!el) return undefined;
    const measure = () => setCanvasH(el.getBoundingClientRect().height || 640);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Resolve the clip for this route (works for deep links too). Uses
  // openClip — not just resolveClip — so the live draft preview below has
  // real transcript/elements/draft data even when landing directly on
  // Export without visiting the editor first (e.g. the gallery's Export
  // button, which only sets currentClipId).
  useEffect(() => {
    if (USE_MOCKS) {
      const mocks = getClipsForProject("prj_001");
      setClip(mocks.find((c) => c.id === clipId) || mocks[0]);
      return;
    }
    if (currentClip?.id === clipId) {
      setClip(currentClip);
      return;
    }
    openClip(clipId);
  }, [clipId, currentClip, openClip]);

  // Reset export state when entering for a different clip
  useEffect(() => {
    resetExport();
    return () => resetExport();
  }, [clipId, resetExport]);

  // Poll the rerender job
  const { error: pollError } = useJobPolling(exportJobId, {
    enabled: !USE_MOCKS && exportStatus === "rendering" && !!exportJobId,
    onUpdate: applyExportUpdate,
  });

  useEffect(() => {
    if (pollError) failExport(pollError.message);
  }, [pollError, failExport]);

  // Mock-mode simulated render
  useEffect(() => {
    if (!USE_MOCKS || mockStatus !== "rendering") return undefined;
    const id = setInterval(() => {
      setMockProgress((p) => {
        if (p >= 100) {
          clearInterval(id);
          setMockStatus("done");
          return 100;
        }
        return p + 4;
      });
    }, 180);
    return () => clearInterval(id);
  }, [mockStatus]);

  const status = USE_MOCKS ? mockStatus : exportStatus === "submitting" ? "rendering" : exportStatus;
  const progress = USE_MOCKS ? mockProgress : exportJob?.progress ?? 0;
  const stage = USE_MOCKS ? "Rendering" : exportJob?.current_stage || "Queued";

  // Before a completed export in THIS visit, the preview is a live draft:
  // clean base video + the same caption/element overlay the editor canvas
  // renders, so draft edits (style, position, elements) are visible
  // immediately instead of looking lost until a rerender burns them in.
  // resetExport() on mount/unmount (below) means this naturally reverts to
  // "live draft" every time the page is (re)entered, and only flips to the
  // actual rendered file once done within this visit.
  const showLiveDraft = !USE_MOCKS && status !== "done";
  const hasCleanVideo = !!clip?.videoUrl;

  // Sprint 4: videoUrl is the 16:9 MASTER, so the live-draft preview must
  // view it through the same per-aspect crop window the editor canvas (and
  // the burn's _prepare_source) uses — otherwise the master shows up
  // letterboxed here while the export correctly crops. Same parity-tested
  // math (lib/cropWindow.js), at this preview box's own scale. The box's CSS
  // enforces the output aspect exactly, so its width derives from the
  // measured height.
  const storedWindow = useAppStore(
    (s) => s.exportSettings.cropWindows?.[s.exportSettings.format]
  );
  const masterDims = useAppStore((s) => s.masterDims);
  const previewFormat = exportSettings.format || "9:16";
  const masterAR = inferMasterAspect(clip?.defaultCropBox, masterDims);
  const cropBox =
    storedWindow || initialWindowForAspect(previewFormat, masterAR, clip?.defaultCropBox);
  const previewW = canvasH * (OUTPUT_ASPECTS[previewFormat] || OUTPUT_ASPECTS["9:16"]);
  const draftLayout = cropVideoLayout(cropBox, previewW, canvasH, masterAR);
  // Aspect-locked windows fill the canvas; bars only exist in edge cases
  // (legacy media, rounding) — the fill note below shows only then.
  const draftHasBars =
    draftLayout.box.width < previewW - 1 || draftLayout.box.height < canvasH - 1;

  const onStartExport = () => {
    if (USE_MOCKS) {
      setMockProgress(0);
      setMockStatus("rendering");
      return;
    }
    startExport(clip);
  };

  const onRetry = () => {
    resetExport();
    onStartExport();
  };

  // Burn-in toggle picks which rendered file to download: the rerender job
  // produces both the captioned output and the pre-caption canvas.
  const downloadPath = exportSettings.burnInCaptions
    ? exportResultPath
    : exportJob?.vertical_path || exportResultPath;

  // Authenticated download — a bare <a href> navigation can't carry the
  // Supabase bearer token, so /clips/download 401'd. downloadClip fetches
  // through the authed API client and saves the blob (api/clips.js).
  const [downloading, setDownloading] = useState(false);
  const onDownload = async () => {
    if (USE_MOCKS || !downloadPath || downloading) return;
    setDownloading(true);
    try {
      await downloadClip(downloadPath);
    } catch (err) {
      toast.error(err.message || "Could not download the clip");
    } finally {
      setDownloading(false);
    }
  };

  const captionStyle = getEditDocument().style;

  if (!USE_MOCKS && !clip) {
    return (
      <AppShell title="Export Clip" subtitle="Loading…">
        <div className="p-8 flex justify-center">
          <Loader2 size={28} className="text-[#c4b5fd] animate-spin mt-16" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Export Clip"
      subtitle={clip?.hookEn || clip?.hook || ""}
      actions={
        <button
          onClick={() => navigate(`/editor/${clip?.id || clipId}`)}
          className="inline-flex items-center gap-1.5 bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed] text-white text-sm px-3 py-2 rounded-md transition-colors"
        >
          <ArrowLeft size={14} /> Back to editor
        </button>
      }
    >
      <div
        data-testid={EXPORT.root}
        className="p-8 max-w-6xl mx-auto grid lg:grid-cols-[420px_1fr] gap-8"
      >
        {/* Left: preview */}
        <div>
          <div className="rounded-2xl border border-[#2a2a35] bg-[#0b0b10] p-4 sticky top-24">
            <p className="text-[10px] uppercase tracking-[0.22em] text-[#71717a] mb-3">
              Preview
            </p>
            <div
              ref={previewBoxRef}
              className="rounded-xl overflow-hidden relative bg-black"
              style={{ aspectRatio: (exportSettings.format || "9:16").replace(":", " / ") }}
            >
              {showLiveDraft && hasCleanVideo ? (
                <>
                  {/* Live draft: the clean 16:9 MASTER viewed through the
                      per-aspect crop window (same lib/cropWindow.js layout
                      the editor canvas and the burn use — Sprint 4), plus
                      the same element overlay the editor canvas renders,
                      reused via StaticElementLayer/ElementBody — not
                      duplicated. Native controls are clipped by the crop
                      viewport, so tap-to-play replaces them. */}
                  <div
                    data-testid={EXPORT.livePreviewViewport}
                    className="absolute overflow-hidden"
                    style={{
                      left: draftLayout.box.left,
                      top: draftLayout.box.top,
                      width: draftLayout.box.width,
                      height: draftLayout.box.height,
                    }}
                  >
                    <video
                      data-testid={EXPORT.livePreviewVideo}
                      src={clip.videoUrl}
                      style={{
                        position: "absolute",
                        left: draftLayout.video.left,
                        top: draftLayout.video.top,
                        width: draftLayout.video.width,
                        height: draftLayout.video.height,
                        maxWidth: "none",
                        maxHeight: "none",
                        objectFit: "fill",
                        cursor: "pointer",
                      }}
                      playsInline
                      preload="metadata"
                      onClick={(e) => {
                        const v = e.currentTarget;
                        if (v.paused) v.play().catch(() => {});
                        else v.pause();
                      }}
                      onLoadedMetadata={(e) => {
                        const v = e.currentTarget;
                        if (v.videoWidth > 0 && v.videoHeight > 0) {
                          useAppStore.getState().setMasterDims({ w: v.videoWidth, h: v.videoHeight });
                        }
                      }}
                      onTimeUpdate={(e) => useAppStore.getState().seek(e.currentTarget.currentTime)}
                    />
                  </div>
                  <StaticElementLayer canvasH={canvasH} />
                  <div className="absolute top-3 right-3 text-[10px] px-2 py-1 rounded-full bg-black/60 backdrop-blur-sm border border-white/10 text-white/80 font-medium">
                    Preview (live draft) · tap to play
                  </div>
                  {draftHasBars && (
                    <div className="absolute bottom-3 inset-x-3 text-center text-[10px] px-2 py-1 rounded-md bg-black/70 text-[#fcd34d]">
                      Bars fill with "{exportSettings.background}" at render — see the
                      editor canvas for the live fill preview
                    </div>
                  )}
                </>
              ) : showLiveDraft && !hasCleanVideo ? (
                <>
                  {/* No clean base video reachable for this clip — fall
                      back to last render instead of a blank preview. */}
                  {clip?.previewUrl ? (
                    <video
                      src={clip.previewUrl}
                      className="absolute inset-0 w-full h-full object-contain"
                      controls
                      playsInline
                      preload="metadata"
                    />
                  ) : clip?.thumbnail ? (
                    <img src={clip.thumbnail} alt="" className="absolute inset-0 w-full h-full object-cover" />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <FileVideo size={32} className="text-[#2a2a35]" />
                    </div>
                  )}
                  <div className="absolute top-3 right-3 text-[10px] px-2 py-1 rounded-full bg-[#f59e0b]/90 backdrop-blur-sm font-mono font-semibold text-black">
                    Showing last render — your current edits will apply on export
                  </div>
                </>
              ) : clip?.previewUrl && !USE_MOCKS ? (
                <>
                  {/* Export completed in this visit — ground truth. */}
                  <video
                    src={clip.previewUrl}
                    className="absolute inset-0 w-full h-full object-contain"
                    controls
                    playsInline
                    preload="metadata"
                  />
                  <div className="absolute top-3 right-3 text-[10px] px-2 py-1 rounded-full bg-[#10b981]/90 backdrop-blur-sm font-mono font-bold text-black">
                    Rendered result
                  </div>
                </>
              ) : clip?.thumbnail ? (
                <>
                  <img
                    src={clip.thumbnail}
                    alt=""
                    className="absolute inset-0 w-full h-full object-cover"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-black/30" />
                  <div className="absolute inset-x-4 bottom-14 text-center">
                    <div className="caption-bold-yellow text-xl leading-tight">
                      {clip.hook}
                    </div>
                  </div>
                </>
              ) : (
                <div className="absolute inset-0 flex items-center justify-center">
                  <FileVideo size={32} className="text-[#2a2a35]" />
                </div>
              )}
              {clip && (
                <div className="absolute top-3 left-3 text-[10px] px-2 py-1 rounded-full bg-[#7c3aed]/90 backdrop-blur-sm font-mono font-bold">
                  {clip.virality} · VIRAL
                </div>
              )}
            </div>

            <div className="mt-4 space-y-2 text-xs">
              <div className="flex items-center justify-between text-[#a1a1aa]">
                <span>Aspect</span>
                <span className="text-white font-mono">{exportSettings.format}</span>
              </div>
              <div className="flex items-center justify-between text-[#a1a1aa]">
                <span>Caption style</span>
                <span className="text-white font-mono">{captionStyle}</span>
              </div>
              <div className="flex items-center justify-between text-[#a1a1aa]">
                <span>Background</span>
                <span className="text-white font-mono">{exportSettings.background}</span>
              </div>
              <div className="flex items-center justify-between text-[#a1a1aa]">
                <span>Container</span>
                <span className="text-white font-mono uppercase">mp4</span>
              </div>
              <div className="flex items-center justify-between text-[#a1a1aa]">
                <span>Burn-in captions</span>
                <span className="text-white font-mono">
                  {exportSettings.burnInCaptions ? "ON" : "OFF"}
                </span>
              </div>
              <div className="flex items-center justify-between text-[#a1a1aa]">
                <span>Duration</span>
                <span className="text-white font-mono">{clip?.duration}s</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right: options */}
        <div className="space-y-6">
          {/* Aspect ratio — chosen IN THE EDITOR (canvas shape is WYSIWYG
              there); shown read-only here so this page can never be the
              place the aspect is set. */}
          <section className="rounded-2xl border border-[#2a2a35] bg-[#0b0b10] p-6">
            <div className="flex items-center gap-2 mb-4">
              <Ratio size={14} className="text-[#c4b5fd]" />
              <h3 className="font-display font-semibold text-sm tracking-wide">
                Aspect ratio
              </h3>
              <span className="ml-auto text-[11px] text-[#71717a]">
                Set in the editor
              </span>
            </div>
            <div className="grid sm:grid-cols-3 gap-3">
              {ASPECTS.map((a) => {
                const active = exportSettings.format === a.v;
                return (
                  <div
                    key={a.v}
                    data-testid={EXPORT.aspectBtn(a.v)}
                    aria-disabled="true"
                    className={`rounded-lg border p-4 text-left ${
                      active
                        ? "border-[#7c3aed] bg-[#7c3aed]/10"
                        : "border-[#2a2a35] bg-[#111116] opacity-50"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-mono text-sm font-bold">{a.v}</span>
                      {active && <Check size={13} className="text-[#7c3aed]" />}
                    </div>
                    <p className="text-sm text-white mb-1">{a.label}</p>
                    <p className="text-[11px] text-[#71717a]">{a.desc}</p>
                  </div>
                );
              })}
            </div>
            <button
              onClick={() => navigate(`/editor/${clip?.id || clipId}`)}
              className="mt-3 text-[11px] font-semibold text-[#c4b5fd] hover:text-white transition-colors"
            >
              Change canvas shape in the editor →
            </button>
          </section>

          {/* Background (letterbox fill for 1:1 / 16:9) */}
          <section className="rounded-2xl border border-[#2a2a35] bg-[#0b0b10] p-6">
            <div className="flex items-center gap-2 mb-4">
              <Palette size={14} className="text-[#c4b5fd]" />
              <h3 className="font-display font-semibold text-sm tracking-wide">
                Canvas background
              </h3>
            </div>
            <div className="flex gap-2 flex-wrap">
              {BACKGROUND_OPTIONS.map((b) => (
                <button
                  key={b}
                  onClick={() => setExportSetting("background", b)}
                  className={`px-4 py-2.5 rounded-md border text-sm capitalize transition-colors ${
                    exportSettings.background === b
                      ? "bg-[#7c3aed]/15 border-[#7c3aed]/50 text-white"
                      : "bg-[#111116] border-[#2a2a35] text-[#a1a1aa] hover:text-white"
                  }`}
                >
                  {b}
                </button>
              ))}
              {exportSettings.background === "color" && (
                <input
                  type="color"
                  value={exportSettings.bgColor}
                  onChange={(e) => setExportSetting("bgColor", e.target.value)}
                  className="w-11 h-11 rounded-md bg-[#111116] border border-[#2a2a35] cursor-pointer"
                />
              )}
            </div>
          </section>

          {/* Resolution — fixed by the backend, shown disabled */}
          <section className="rounded-2xl border border-[#2a2a35] bg-[#0b0b10] p-6">
            <div className="flex items-center gap-2 mb-4">
              <FileVideo size={14} className="text-[#c4b5fd]" />
              <h3 className="font-display font-semibold text-sm tracking-wide">
                Resolution & format
              </h3>
            </div>
            <div className="grid sm:grid-cols-2 gap-3 mb-3">
              {RESOLUTIONS.map((r) => (
                <div
                  key={r.v}
                  data-testid={EXPORT.resolutionBtn(r.v)}
                  className="rounded-lg border border-[#7c3aed] bg-[#7c3aed]/10 p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold">{r.label}</span>
                    <Check size={13} className="text-[#7c3aed]" />
                  </div>
                  <p className="text-[11px] text-[#71717a]">{r.note}</p>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <button
                data-testid={EXPORT.formatBtn("mp4")}
                className="flex-1 py-2.5 rounded-md border text-sm font-mono uppercase bg-[#7c3aed]/15 border-[#7c3aed]/50 text-white"
              >
                mp4
              </button>
              {DISABLED_FORMATS.map((f) => (
                <button
                  key={f}
                  data-testid={EXPORT.formatBtn(f)}
                  disabled
                  title="Not supported by the render pipeline"
                  className="flex-1 py-2.5 rounded-md border text-sm font-mono uppercase bg-[#111116] border-[#2a2a35] text-[#4a4a55] cursor-not-allowed"
                >
                  {f}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-[#71717a] mt-3">
              The render pipeline outputs 1080-based MP4 (H.264 + AAC) at the
              selected aspect ratio.
            </p>
          </section>

          {/* Burn-in captions toggle */}
          <section className="rounded-2xl border border-[#2a2a35] bg-[#0b0b10] p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-md bg-[#7c3aed]/15 border border-[#7c3aed]/30 flex items-center justify-center">
                  <TypeIcon size={16} className="text-[#c4b5fd]" />
                </div>
                <div>
                  <p className="text-sm font-semibold">Burn-in captions</p>
                  <p className="text-xs text-[#71717a] mt-0.5">
                    ON downloads the captioned render; OFF downloads the clean
                    canvas render (no captions).
                  </p>
                </div>
              </div>
              <button
                data-testid={EXPORT.burnToggle}
                onClick={() =>
                  setExportSetting("burnInCaptions", !exportSettings.burnInCaptions)
                }
                className={`w-12 h-7 rounded-full relative transition-colors shrink-0 ml-4 ${
                  exportSettings.burnInCaptions ? "bg-[#7c3aed]" : "bg-[#2a2a35]"
                }`}
              >
                <span
                  className={`absolute top-0.5 w-6 h-6 bg-white rounded-full transition-transform ${
                    exportSettings.burnInCaptions ? "translate-x-5" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>
          </section>

          {/* Feature #17-20 — tier status: watermark, render-minute meter, expiry. */}
          <TierStrip />

          {/* Progress / Start / Done / Failed */}
          {(status === "idle" || !status) && (
            <button
              data-testid={EXPORT.startBtn}
              onClick={onStartExport}
              disabled={!USE_MOCKS && !clip}
              className="w-full inline-flex items-center justify-center gap-2 bg-[#7c3aed] hover:bg-[#6d28d9] disabled:bg-[#2a2a35] disabled:text-[#71717a] text-white font-semibold py-4 rounded-lg transition-colors shadow-[0_10px_40px_-10px_rgba(124,58,237,0.7)] text-base"
            >
              <Sparkles size={16} /> Start export
            </button>
          )}

          {(status === "rendering" || status === "submitting") && (
            <section className="rounded-2xl border border-[#7c3aed]/40 bg-gradient-to-br from-[#7c3aed]/10 to-[#0b0b10] p-6">
              <div className="flex items-center gap-3 mb-4">
                <Loader2 size={18} className="text-[#c4b5fd] animate-spin" />
                <div className="flex-1">
                  <p className="text-sm font-semibold">Rendering your clip...</p>
                  <p className="text-[11px] text-[#a1a1aa]">
                    {stage} · {exportSettings.format} · MP4
                  </p>
                </div>
                <span className="font-mono text-sm text-white">{progress}%</span>
              </div>
              <div className="h-2 rounded-full bg-[#1a1a24] overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-[#7c3aed] to-[#c026d3] rounded-full transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </section>
          )}

          {status === "failed" && (
            <section className="rounded-2xl border border-[#ef4444]/40 bg-gradient-to-br from-[#ef4444]/10 to-[#0b0b10] p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-11 h-11 rounded-full bg-[#ef4444]/20 border border-[#ef4444]/40 flex items-center justify-center">
                  <AlertTriangle size={20} className="text-[#ef4444]" />
                </div>
                <div>
                  <p className="text-lg font-display font-semibold">Export failed</p>
                  <p className="text-xs text-[#a1a1aa] break-words max-w-md">
                    {exportError || "The render pipeline reported an error."}
                  </p>
                </div>
              </div>
              <button
                onClick={onRetry}
                className="inline-flex items-center gap-2 bg-[#7c3aed] hover:bg-[#6d28d9] text-white font-semibold px-5 py-2.5 rounded-md transition-colors"
              >
                <RotateCcw size={14} /> Retry export
              </button>
            </section>
          )}

          {status === "done" && (
            <section className="rounded-2xl border border-[#10b981]/40 bg-gradient-to-br from-[#10b981]/10 to-[#0b0b10] p-6">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-11 h-11 rounded-full bg-[#10b981]/20 border border-[#10b981]/40 flex items-center justify-center">
                  <Check size={20} className="text-[#10b981]" />
                </div>
                <div>
                  <p className="text-lg font-display font-semibold">Export ready!</p>
                  <p className="text-xs text-[#a1a1aa]">
                    Your clip is packaged and ready to go viral.
                  </p>
                </div>
              </div>
              {exportWarnings?.includes("transcript_edits_skipped_multi_segment") && (
                <div className="mb-4 rounded-md border border-[#f59e0b]/40 bg-[#f59e0b]/10 p-3 text-xs text-[#fcd34d] flex items-start gap-2">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                  <span>
                    Caption line merges/splits were skipped — this clip is
                    stitched from multiple segments and the backend can't apply
                    them there yet. Word-level edits were applied.
                  </span>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <button
                  data-testid={EXPORT.download}
                  onClick={onDownload}
                  disabled={downloading || !downloadPath}
                  className="inline-flex items-center gap-2 bg-white text-black font-semibold px-5 py-2.5 rounded-md hover:bg-[#e5e5e5] disabled:opacity-60 transition-colors"
                >
                  {downloading ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Download size={14} />
                  )}
                  {downloading ? "Downloading…" : "Download MP4"}
                </button>
                <button className="inline-flex items-center gap-2 bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed]/50 text-white font-medium px-4 py-2.5 rounded-md transition-colors">
                  <Instagram size={14} /> Share to Instagram
                </button>
                <button className="inline-flex items-center gap-2 bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed]/50 text-white font-medium px-4 py-2.5 rounded-md transition-colors">
                  <Youtube size={14} /> Post as Short
                </button>
                <button className="inline-flex items-center gap-2 bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed]/50 text-white font-medium px-4 py-2.5 rounded-md transition-colors">
                  <Share2 size={14} /> Copy link
                </button>
              </div>

              {!USE_MOCKS && (
                <div className="mt-5 pt-5 border-t border-[#10b981]/20">
                  {!clipMetadata && metadataStatus !== "loading" && (
                    <button
                      data-testid={EXPORT.generateMetadata}
                      onClick={() => generateMetadata(clip)}
                      className="inline-flex items-center gap-2 bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed]/50 text-white text-sm font-medium px-4 py-2.5 rounded-md transition-colors"
                    >
                      <Wand2 size={14} /> Generate title & hashtags
                    </button>
                  )}

                  {metadataStatus === "loading" && (
                    <div className="inline-flex items-center gap-2 text-sm text-[#a1a1aa]">
                      <Loader2 size={14} className="animate-spin" /> Asking Gemini for a title, description & hashtags…
                    </div>
                  )}

                  {metadataStatus === "error" && !clipMetadata && (
                    <div className="flex items-center gap-3">
                      <p className="text-xs text-[#fca5a5]">Metadata generation failed.</p>
                      <button
                        onClick={() => generateMetadata(clip)}
                        className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] px-2.5 py-1.5 rounded-md transition-colors"
                      >
                        <RotateCcw size={11} /> Retry
                      </button>
                    </div>
                  )}

                  {clipMetadata && (
                    <div className="space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-[10px] uppercase tracking-widest text-[#71717a] mb-1">Title</p>
                          <p className="text-sm text-white font-medium">{clipMetadata.title}</p>
                        </div>
                        <button
                          title="Copy title"
                          onClick={() => navigator.clipboard?.writeText(clipMetadata.title || "")}
                          className="text-[#71717a] hover:text-white p-1.5 shrink-0"
                        >
                          <Copy size={13} />
                        </button>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase tracking-widest text-[#71717a] mb-1">Description</p>
                        <p className="text-xs text-[#d4d4d8]">{clipMetadata.description}</p>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase tracking-widest text-[#71717a] mb-1.5">Hashtags</p>
                        <div className="flex flex-wrap gap-1.5">
                          {(clipMetadata.hashtags || []).map((h) => (
                            <span
                              key={h}
                              className="text-[11px] font-mono text-[#c4b5fd] bg-[#7c3aed]/10 border border-[#7c3aed]/30 px-2 py-0.5 rounded-full"
                            >
                              #{h}
                            </span>
                          ))}
                        </div>
                      </div>
                      <button
                        onClick={() => generateMetadata(clip)}
                        className="text-[11px] text-[#71717a] hover:text-white underline underline-offset-2"
                      >
                        Regenerate
                      </button>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </AppShell>
  );
}

// Feature #17-20 — compact tier status shown above the export button: the
// free-tier watermark notice, the monthly render-minute meter (#18), and the
// published-clip expiry (#20). Reads the live entitlements from billingStatus.
function TierStrip() {
  const billing = useAppStore((s) => s.billingStatus);
  const loadBillingStatus = useAppStore((s) => s.loadBillingStatus);
  useEffect(() => {
    if (!billing) loadBillingStatus();
  }, [billing, loadBillingStatus]);
  if (!billing) return null;

  const used = billing.render_minutes_used ?? 0;
  const budget = billing.render_minutes_budget ?? 0;
  const pct = budget > 0 ? Math.min(100, (used / budget) * 100) : 0;
  const near = pct >= 85;
  const expiry = billing.expiry_hours;
  const expiryLabel =
    expiry == null ? "never expires" : expiry >= 48 ? `${Math.round(expiry / 24)} days` : `${expiry}h`;

  return (
    <div className="rounded-xl border border-[#1c1c24] bg-[#0b0b10] p-3 mb-3 space-y-2">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-[#9a9aa6]">
          Render minutes this month
          <span className="text-[#5a5a66]"> · resets monthly</span>
        </span>
        <span className={`font-mono ${near ? "text-amber-400" : "text-white"}`}>
          {used.toFixed(1)} / {budget.toFixed(0)}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-[#1c1c24] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${near ? "bg-amber-400" : "bg-[#7c3aed]"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[10px] text-[#71717a] pt-0.5">
        <span>
          {billing.watermark ? (
            <span className="text-amber-400/90">● Watermarked (free tier)</span>
          ) : (
            <span className="text-[#22ff9c]">● No watermark</span>
          )}
        </span>
        <span>Clips expire: <span className="text-[#9a9aa6]">{expiryLabel}</span></span>
      </div>
      {billing.watermark && (
        <p className="text-[10px] text-[#5a5a66] leading-snug">
          Upgrade to Creator or Studio to remove the watermark, unlock PRO caption
          presets, get more render minutes, and keep clips longer.
        </p>
      )}
    </div>
  );
}
