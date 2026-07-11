import React from "react";
import { useNavigate } from "react-router-dom";
import { FileVideo } from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { USE_MOCKS } from "@/api/client";
import { EDITOR } from "@/constants/testIds";
import { getClipsForProject } from "@/data/mockData";

/**
 * LeftClips — clip list panel for the current job.
 * Navigates via the route so Editor's openClip effect reloads transcript+draft.
 */
export const LeftClips = () => {
  const navigate = useNavigate();
  const currentClipId = useAppStore((s) => s.currentClipId);
  const currentJobId = useAppStore((s) => s.currentJobId);
  const storeClips = useAppStore((s) => (currentJobId ? s.clipsByJob[currentJobId] : null));
  const project = useAppStore((s) => s.getProject(currentJobId));

  const clips = USE_MOCKS ? getClipsForProject("prj_001") : storeClips || [];
  const projectTitle = USE_MOCKS ? "AI Tools Podcast" : project?.title || "Project";

  return (
    <aside className="border-r border-[#1c1c24] bg-[#0a0a0f] flex flex-col overflow-hidden">
      <div className="px-4 pt-4 pb-2 flex items-center justify-between">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.22em] text-[#5a5a66]">
            Project
          </p>
          <p className="text-sm font-semibold mt-0.5 truncate">{projectTitle}</p>
        </div>
        <div className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#7c3aed]/15 text-[#c4b5fd] border border-[#7c3aed]/30 shrink-0">
          {clips.length} clips
        </div>
      </div>

      <div className="px-3 py-2 border-b border-[#1c1c24]">
        <p className="text-[10px] uppercase tracking-widest text-[#71717a] px-1 mb-1.5">
          Sorted by virality
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {clips.map((clip, i) => {
          const isActive = clip.id === currentClipId;
          return (
            <button
              key={clip.id}
              data-testid={EDITOR.clipListItem(clip.id)}
              onClick={() => navigate(`/editor/${clip.id}`)}
              className={`w-full text-left rounded-lg border p-2.5 flex gap-2.5 items-center transition-all ${
                isActive
                  ? "bg-[#7c3aed]/12 border-[#7c3aed]/50"
                  : "bg-[#111116] border-transparent hover:border-[#2a2a35]"
              }`}
            >
              <div className="relative w-12 h-16 rounded overflow-hidden shrink-0 bg-black">
                {clip.thumbnail ? (
                  <img
                    src={clip.thumbnail}
                    alt=""
                    className="w-full h-full object-cover opacity-80"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <FileVideo size={14} className="text-[#2a2a35]" />
                  </div>
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                <span className="absolute bottom-0.5 left-0.5 text-[9px] font-mono font-bold px-1 rounded bg-black/70 text-[#22ff9c]">
                  {clip.virality}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[10px] font-mono text-[#71717a] mb-0.5">
                  #{String(i + 1).padStart(2, "0")} · {clip.duration}s
                </p>
                <p className="text-xs font-medium text-white leading-snug line-clamp-2">
                  {clip.hook}
                </p>
              </div>
            </button>
          );
        })}
        {clips.length === 0 && (
          <p className="text-xs text-[#5a5a66] px-2 py-4 text-center">
            No clips loaded
          </p>
        )}
      </div>
    </aside>
  );
};

export default LeftClips;
