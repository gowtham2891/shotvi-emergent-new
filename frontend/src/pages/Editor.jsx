import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Undo2, Redo2, Save, Download, Check, Loader2 } from "lucide-react";
import { Logo } from "@/components/shotvi/Logo";
import { useAppStore } from "@/store/useAppStore";
import { USE_MOCKS } from "@/api/client";
import { getClipsForProject } from "@/data/mockData";
import { EDITOR } from "@/constants/testIds";
import { LeftClips } from "@/components/editor/LeftClips";
import { CanvasArea } from "@/components/editor/CanvasArea";
import { Inspector } from "@/components/editor/Inspector";
import { TimelineRow } from "@/components/editor/TimelineRow";

const AUTOSAVE_MS = 2500;

/**
 * Editor — thin composition layer.
 * Layout: TopBar / [ LeftClips | CanvasArea + TimelineRow | Inspector ]
 * All state lives in useAppStore; each panel subscribes to its own slice.
 */
export default function Editor() {
  const { clipId } = useParams();
  const navigate = useNavigate();

  const currentClipId = useAppStore((s) => s.currentClipId);
  const currentClip = useAppStore((s) => s.currentClip);
  const openClip = useAppStore((s) => s.openClip);
  const saveDraftNow = useAppStore((s) => s.saveDraftNow);
  const draftStatus = useAppStore((s) => s.draftStatus);
  const elements = useAppStore((s) => s.elements);

  // Route param → open the clip (resolves job, loads transcript + draft)
  useEffect(() => {
    if (clipId) openClip(clipId);
  }, [clipId, openClip]);

  // Mock-only playback loop: with a real clip, the <video> element in
  // CanvasArea drives currentTime instead.
  useEffect(() => {
    if (!USE_MOCKS) return undefined;
    const id = setInterval(() => {
      const s = useAppStore.getState();
      if (!s.isPlaying) return;
      const next = s.currentTime + 0.1;
      s.seek(next >= s.duration ? 0 : next);
    }, 100);
    return () => clearInterval(id);
  }, []);

  // Debounced draft autosave on element changes
  const autosaveTimer = useRef(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (USE_MOCKS || !currentClip) return undefined;
    setDirty(true);
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      saveDraftNow();
      setDirty(false);
    }, AUTOSAVE_MS);
    return () => clearTimeout(autosaveTimer.current);
  }, [elements, currentClip, saveDraftNow]);

  // Title: real clip hook, else mock fallback
  const mockClip = USE_MOCKS
    ? getClipsForProject("prj_001").find((c) => c.id === currentClipId) ||
      getClipsForProject("prj_001")[0]
    : null;
  const title = currentClip?.hook || currentClip?.hookEn || mockClip?.hookEn || "Clip";

  return (
    <div
      data-testid={EDITOR.root}
      className="h-screen flex flex-col bg-[#060608] text-white overflow-hidden"
    >
      {/* Top bar */}
      <header className="h-14 border-b border-[#1c1c24] bg-[#0a0a0f] flex items-center justify-between px-4 shrink-0 z-30">
        <div className="flex items-center gap-4">
          <button
            data-testid={EDITOR.backBtn}
            onClick={() => navigate(-1)}
            className="w-8 h-8 rounded-md border border-[#2a2a35] hover:border-[#7c3aed] text-[#a1a1aa] hover:text-white flex items-center justify-center transition-colors"
          >
            <ArrowLeft size={14} />
          </button>
          <Logo size="sm" />
          <div className="h-4 w-px bg-[#2a2a35]" />
          <div className="text-sm max-w-[380px] truncate">
            <span className="text-[#71717a]">Editing:</span>{" "}
            <span className="font-medium">{title}</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button className="w-8 h-8 rounded-md hover:bg-white/5 text-[#a1a1aa] hover:text-white flex items-center justify-center transition-colors">
            <Undo2 size={14} />
          </button>
          <button className="w-8 h-8 rounded-md hover:bg-white/5 text-[#a1a1aa] hover:text-white flex items-center justify-center transition-colors">
            <Redo2 size={14} />
          </button>
          <div className="h-4 w-px bg-[#2a2a35] mx-1" />
          <button
            onClick={saveDraftNow}
            className="inline-flex items-center gap-1.5 text-xs bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed]/50 px-3 py-1.5 rounded-md transition-colors"
          >
            {draftStatus === "saving" ? (
              <Loader2 size={12} className="animate-spin" />
            ) : draftStatus === "saved" && !dirty ? (
              <Check size={12} className="text-[#10b981]" />
            ) : (
              <Save size={12} />
            )}
            {draftStatus === "saving" ? "Saving…" : draftStatus === "saved" && !dirty ? "Saved" : "Save draft"}
          </button>
          <button
            data-testid={EDITOR.exportBtn}
            onClick={() => navigate(`/export/${currentClipId || clipId}`)}
            className="inline-flex items-center gap-1.5 text-xs bg-[#7c3aed] hover:bg-[#6d28d9] text-white font-semibold px-4 py-1.5 rounded-md transition-colors shadow-[0_6px_20px_-6px_rgba(124,58,237,0.7)]"
          >
            <Download size={12} /> Export
          </button>
        </div>
      </header>

      {/* Main 3-panel grid */}
      <div className="flex-1 min-h-0 grid grid-cols-[240px_1fr_300px]">
        <LeftClips />
        <main className="flex flex-col min-h-0 min-w-0">
          <CanvasArea currentClip={currentClip || mockClip} />
          <TimelineRow />
        </main>
        <Inspector />
      </div>
    </div>
  );
}
