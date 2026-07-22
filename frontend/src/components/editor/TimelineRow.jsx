import React, { useRef } from "react";
import {
  Play,
  Pause,
  Rewind,
  FastForward,
  Scissors,
} from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { EDITOR } from "@/constants/testIds";
import EditableTranscript from "@/components/editor/EditableTranscript";

const clamp01 = (v) => Math.max(0, Math.min(1, v));

const formatTime = (t) => {
  const m = Math.floor(t / 60)
    .toString()
    .padStart(2, "0");
  const s = Math.floor(t % 60)
    .toString()
    .padStart(2, "0");
  const ms = Math.floor((t % 1) * 10);
  return `${m}:${s}.${ms}`;
};

/**
 * TimelineRow — transport controls + waveform scrubber + word-level chips.
 */
export const TimelineRow = () => {
  const currentTime = useAppStore((s) => s.currentTime);
  const duration = useAppStore((s) => s.duration);
  const isPlaying = useAppStore((s) => s.isPlaying);
  const togglePlay = useAppStore((s) => s.togglePlay);
  const seek = useAppStore((s) => s.seek);
  const transcriptStatus = useAppStore((s) => s.transcriptStatus);
  const transcriptError = useAppStore((s) => s.transcriptError);
  const transcriptWarning = useAppStore((s) => s.transcriptWarning);
  const retryTranscript = useAppStore((s) => s.retryTranscript);
  const trimStart = useAppStore((s) => s.exportSettings.trimStart);
  const trimEnd = useAppStore((s) => s.exportSettings.trimEnd);
  const resetTrim = useAppStore((s) => s.resetTrim);

  const barRef = useRef(null);

  // Effective trim window (trimEnd -1 sentinel → clip end) — same math as
  // the store's getTrimBounds, kept local for render.
  const effStart = duration ? Math.min(Math.max(trimStart || 0, 0), duration) : 0;
  const effEnd = duration ? (trimEnd > 0 ? Math.min(trimEnd, duration) : duration) : 0;
  const trimmed = effStart > 0 || (duration > 0 && effEnd < duration);
  const startPct = duration ? (effStart / duration) * 100 : 0;
  const endPct = duration ? (effEnd / duration) * 100 : 100;

  // Drag a trim handle: pointer x → clip time → store (clamped there). The
  // whole drag coalesces into ONE undo frame; pointerup closes the gesture.
  const startTrimDrag = (which) => (e) => {
    if (!duration) return;
    e.preventDefault();
    e.stopPropagation();
    const rect = barRef.current?.getBoundingClientRect();
    if (!rect) return;
    const move = (ev) => {
      const t = clamp01((ev.clientX - rect.left) / rect.width) * duration;
      const s = useAppStore.getState();
      const { start, end } = s.getTrimBounds();
      if (which === "start") s.setTrimRange(t, end);
      else s.setTrimRange(start, t);
    };
    const up = () => {
      useAppStore.getState().endHistoryCoalescing();
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    move(e); // apply the grab position immediately
  };

  const playheadPct = Math.max(
    0,
    Math.min(100, (currentTime / duration) * 100)
  );

  return (
    <div className="border-t border-[#1c1c24] bg-[#0a0a0f] shrink-0">
      {/* Transport */}
      <div className="h-12 flex items-center justify-between px-4 border-b border-[#1c1c24]">
        <div className="flex items-center gap-1">
          <button
            data-testid={EDITOR.seekBackBtn}
            onClick={() => seek(currentTime - 1)}
            className="w-8 h-8 rounded-md hover:bg-white/5 text-[#a1a1aa] hover:text-white flex items-center justify-center transition-colors"
          >
            <Rewind size={14} />
          </button>
          <button
            data-testid={EDITOR.playBtn}
            onClick={togglePlay}
            className="w-10 h-10 rounded-full bg-[#7c3aed] hover:bg-[#6d28d9] text-white flex items-center justify-center transition-colors shadow-[0_0_20px_rgba(124,58,237,0.5)]"
          >
            {isPlaying ? (
              <Pause size={16} fill="white" />
            ) : (
              <Play size={16} fill="white" className="ml-0.5" />
            )}
          </button>
          <button
            data-testid={EDITOR.seekFwdBtn}
            onClick={() => seek(currentTime + 1)}
            className="w-8 h-8 rounded-md hover:bg-white/5 text-[#a1a1aa] hover:text-white flex items-center justify-center transition-colors"
          >
            <FastForward size={14} />
          </button>
        </div>

        <div className="font-mono text-xs text-[#a1a1aa]">
          <span className="text-white">{formatTime(currentTime)}</span>
          <span className="text-[#5a5a66] mx-1.5">/</span>
          {formatTime(duration)}
        </div>

        <div className="text-[11px] text-[#71717a] flex items-center gap-2">
          <kbd className="px-1.5 py-0.5 rounded bg-[#111116] border border-[#2a2a35] font-mono text-[9px]">
            Space
          </kbd>
          <span>Play</span>
          <kbd className="px-1.5 py-0.5 rounded bg-[#111116] border border-[#2a2a35] font-mono text-[9px]">
            ← →
          </kbd>
          <span>Nudge</span>
        </div>
      </div>

      {/* Waveform / playhead scrubber + trim handles */}
      <div className="relative h-12 border-b border-[#1c1c24] px-4 flex items-center">
        <div ref={barRef} className="relative flex-1 h-8 bg-[#111116] rounded overflow-hidden">
          <div className="absolute inset-0 flex items-center gap-[2px] px-1">
            {Array.from({ length: 120 }).map((_, i) => {
              const h =
                20 + Math.abs(Math.sin(i * 0.35) * 60) + (i * 7) % 30;
              return (
                <div
                  key={i}
                  className="wave-bar flex-1"
                  style={{
                    height: `${Math.min(100, h)}%`,
                    opacity: (i / 120) * 100 < playheadPct ? 1 : 0.35,
                  }}
                />
              );
            })}
          </div>
          <div
            data-testid={EDITOR.timelinePlayhead}
            className="absolute top-0 bottom-0 w-0.5 bg-[#7c3aed] pointer-events-none z-10"
            style={{
              left: `${playheadPct}%`,
              boxShadow: "0 0 12px rgba(124,58,237,1)",
            }}
          >
            <div className="absolute -top-1 -left-1.5 w-3.5 h-3.5 bg-[#7c3aed] rounded-sm rotate-45 shadow-[0_0_10px_rgba(124,58,237,0.9)]" />
          </div>
          <div
            className="absolute inset-0 cursor-pointer"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const x = (e.clientX - rect.left) / rect.width;
              seek(x * duration);
            }}
          />

          {/* Trimmed-out regions (excluded from playback + export) */}
          {startPct > 0 && (
            <div
              className="absolute top-0 bottom-0 left-0 bg-black/60 pointer-events-none z-10"
              style={{ width: `${startPct}%` }}
            />
          )}
          {endPct < 100 && (
            <div
              className="absolute top-0 bottom-0 right-0 bg-black/60 pointer-events-none z-10"
              style={{ width: `${100 - endPct}%` }}
            />
          )}

          {/* Trim handles — drag to contract the clip's start/end. The
              backend re-cuts the clip's own file (trim_start/trim_end in
              api/renders.js), so handles only move inward from the bounds. */}
          {duration > 0 && (
            <>
              <div
                data-testid={EDITOR.trimStartHandle}
                onPointerDown={startTrimDrag("start")}
                title="Drag to trim the clip start"
                className="absolute top-0 bottom-0 w-2 -ml-1 z-20 cursor-ew-resize group"
                style={{ left: `${startPct}%` }}
              >
                <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-1 rounded bg-[#22ff9c] group-hover:bg-white transition-colors" />
              </div>
              <div
                data-testid={EDITOR.trimEndHandle}
                onPointerDown={startTrimDrag("end")}
                title="Drag to trim the clip end"
                className="absolute top-0 bottom-0 w-2 -ml-1 z-20 cursor-ew-resize group"
                style={{ left: `${endPct}%` }}
              >
                <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-1 rounded bg-[#22ff9c] group-hover:bg-white transition-colors" />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Trim readout — only when a trim is active */}
      {trimmed && (
        <div className="flex items-center gap-2 px-4 py-1.5 border-b border-[#1c1c24] text-[11px] text-[#9a9aa6]">
          <Scissors size={11} className="text-[#22ff9c]" />
          <span>
            Trimmed: <span className="font-mono text-white">{formatTime(effStart)}</span>
            {" – "}
            <span className="font-mono text-white">{formatTime(effEnd)}</span>
            {" · exports "}
            <span className="font-mono text-white">{(effEnd - effStart).toFixed(1)}s</span>
          </span>
          <button
            data-testid={EDITOR.trimReset}
            onClick={resetTrim}
            className="ml-auto text-[10px] font-semibold text-[#c4b5fd] hover:text-white transition-colors"
          >
            Reset trim
          </button>
        </div>
      )}

      {/* Editable transcript (caption lines = preview/export grouping) */}
      <div className="px-4 py-3 min-h-[76px] max-h-[132px] overflow-y-auto">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10px] uppercase tracking-[0.22em] text-[#5a5a66]">
            Transcript · Editable
          </p>
          <span className="text-[10px] text-[#71717a]">
            <kbd className="px-1 py-0.5 rounded bg-[#111116] border border-[#2a2a35] font-mono text-[9px] mr-1">Enter</kbd>
            split
            <span className="mx-1.5 text-[#3a3a44]">·</span>
            <kbd className="px-1 py-0.5 rounded bg-[#111116] border border-[#2a2a35] font-mono text-[9px] mr-1">⌫</kbd>
            merge
            <span className="mx-1.5 text-[#3a3a44]">·</span>
            type to fix
          </span>
        </div>
        {transcriptStatus === "loading" && (
          <p className="text-xs text-[#71717a] py-2">Loading transcript…</p>
        )}
        {transcriptStatus === "error" && (
          <div className="flex items-center gap-3 py-2">
            <p className="text-xs text-[#fca5a5]">{transcriptError}</p>
            <button
              onClick={retryTranscript}
              className="text-[11px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] px-2.5 py-1 rounded-md transition-colors"
            >
              Retry
            </button>
          </div>
        )}
        {transcriptStatus === "ready" && transcriptWarning && (
          <div className="mb-2 rounded-md border border-[#f59e0b]/40 bg-[#f59e0b]/10 px-2.5 py-1.5 text-[11px] text-[#fcd34d] leading-snug">
            {transcriptWarning}
          </div>
        )}
        {transcriptStatus === "ready" && <EditableTranscript />}
      </div>
    </div>
  );
};

export default TimelineRow;
