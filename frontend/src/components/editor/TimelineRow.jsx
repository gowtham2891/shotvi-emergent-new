import React from "react";
import {
  Play,
  Pause,
  Scissors,
  Rewind,
  FastForward,
} from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { EDITOR } from "@/constants/testIds";

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
  const transcript = useAppStore((s) => s.transcript);
  const transcriptStatus = useAppStore((s) => s.transcriptStatus);
  const transcriptError = useAppStore((s) => s.transcriptError);
  const transcriptWarning = useAppStore((s) => s.transcriptWarning);
  const retryTranscript = useAppStore((s) => s.retryTranscript);

  const activeIdx = transcript.findIndex(
    (w) => currentTime >= w.start && currentTime < w.end
  );

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
          <div className="h-4 w-px bg-[#2a2a35] mx-2" />
          <button
            data-testid={EDITOR.splitBtn}
            className="inline-flex items-center gap-1.5 text-xs text-[#a1a1aa] hover:text-white bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed]/50 px-2.5 py-1.5 rounded-md transition-colors"
          >
            <Scissors size={12} /> Split
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

      {/* Waveform / playhead scrubber */}
      <div className="relative h-12 border-b border-[#1c1c24] px-4 flex items-center">
        <div className="relative flex-1 h-8 bg-[#111116] rounded overflow-hidden">
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
        </div>
      </div>

      {/* Word-level track */}
      <div className="px-4 py-3 min-h-[76px] max-h-[100px] overflow-y-auto">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10px] uppercase tracking-[0.22em] text-[#5a5a66]">
            Transcript · Word-level
          </p>
          <span className="text-[10px] text-[#71717a]">
            Click a word to jump
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
        <div className="flex flex-wrap gap-1">
          {transcript.map((w, i) => {
            const isActive = i === activeIdx;
            const isPast = i < activeIdx;
            return (
              <button
                key={i}
                data-testid={EDITOR.timelineWord(i)}
                onClick={() => seek(w.start + 0.02)}
                className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium transition-all border ${
                  isActive
                    ? "bg-[#7c3aed] text-white border-[#7c3aed] scale-110 shadow-[0_0_12px_rgba(124,58,237,0.6)]"
                    : isPast
                      ? "bg-[#1a1a24] text-[#a1a1aa] border-[#2a2a35] hover:border-[#7c3aed]/40"
                      : "bg-[#111116] text-[#71717a] border-[#2a2a35] hover:text-white hover:border-[#7c3aed]/40"
                }`}
              >
                <span className="font-mono text-[9px] mr-1 opacity-60">
                  {w.start.toFixed(1)}s
                </span>
                {w.text}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default TimelineRow;
